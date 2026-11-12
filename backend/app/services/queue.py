"""Coordinator: owns SQLite writes, the durable job queue and the single worker process.

* Jobs and per-file items are persisted; a restarted server marks previously queued/running items
  ``interrupted`` and offers manual retry (nothing is resumed implicitly).
* Exactly one worker process runs at a time (spawn start method; Windows-safe). Small intake/analysis
  tasks are dispatched ahead of the next queued enhancement item (a running item is never preempted).
* Messages from the worker are bounded progress/result dictionaries.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import queue
import shutil
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from ..config import Config
from ..db import Database, new_id, now
from ..processing.pipeline import ExecutionOptions, choose_backend
from ..processing.recipe import PIPELINE_VERSION, parse_recipe
from ..processing.report import dependency_versions
from .worker import worker_main


class TaskError(Exception):
    def __init__(self, error: dict[str, Any]):
        super().__init__(error.get("message", "task failed"))
        self.error = error


class Coordinator:
    def __init__(self, cfg: Config, db: Database) -> None:
        self.cfg = cfg
        self.db = db
        self._ctx = mp.get_context("spawn")
        self._proc = None
        self._task_q = None
        self._result_q = None
        self._cancel = None
        self._cond = threading.Condition()
        self._small: list[tuple[dict[str, Any], Future]] = []
        self._current: dict[str, Any] | None = None
        self._stop = False
        self._threads: list[threading.Thread] = []
        self.probe_info: dict[str, Any] | None = None
        self.live: dict[str, dict[str, Any]] = {}  # item_id -> live stage/label

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._recover()
        self._spawn()
        for target in (self._reader_loop, self._scheduler_loop):
            t = threading.Thread(target=target, daemon=True, name=target.__name__)
            t.start()
            self._threads.append(t)
        for a in self.db.all("SELECT * FROM assets WHERE status='inspecting'"):
            self.enqueue_prepare(a["id"])

    def stop(self) -> None:
        self._stop = True
        with self._cond:
            self._cond.notify_all()
        try:
            if self._task_q is not None:
                self._task_q.put(None)
        except Exception:
            pass
        if self._proc is not None:
            self._proc.join(timeout=5)
            if self._proc.is_alive():
                self._proc.terminate()
        for t in self._threads:
            t.join(timeout=2)

    def _spawn(self) -> None:
        self._task_q = self._ctx.Queue()
        self._result_q = self._ctx.Queue()
        self._cancel = self._ctx.Event()
        self._proc = self._ctx.Process(
            target=worker_main, args=(self._task_q, self._result_q, self._cancel, self.cfg), daemon=True, name="eae-worker"
        )
        self._proc.start()

    def _recover(self) -> None:
        t = now()
        self.db.execute("UPDATE job_items SET state='interrupted', finished_at=? WHERE state IN ('running','queued')", (t,))
        self.db.execute("UPDATE jobs SET state='interrupted', updated_at=? WHERE state IN ('running','queued')", (t,))
        for p in self.cfg.runs_dir.glob("*.partial"):
            shutil.rmtree(p, ignore_errors=True)

    # ------------------------------------------------------------------ small tasks (futures)
    def run_task(self, kind: str, payload: dict[str, Any]) -> Future:
        fut: Future = Future()
        task = {"task_id": new_id("t_"), "kind": kind, **payload}
        with self._cond:
            self._small.append((task, fut))
            self._cond.notify_all()
        return fut

    def enqueue_prepare(self, asset_id: str) -> None:
        asset = self.db.one("SELECT * FROM assets WHERE id=?", (asset_id,))
        if not asset:
            return
        payload = {"asset": self._asset_payload(asset), "asset_dir": str(self.cfg.assets_dir / asset_id), "asset_id": asset_id}
        fut = self.run_task("prepare", payload)
        fut.add_done_callback(lambda f, aid=asset_id: self._on_prepare_done(aid, f))

    def _asset_payload(self, asset: dict[str, Any]) -> dict[str, Any]:
        d = self.cfg.assets_dir / asset["id"]
        return {
            "id": asset["id"], "filename": asset["filename"], "path": str(d / asset["original_name"]), "sha256": asset["sha256"],
            "inspection": asset["inspection"], "interpretation": asset["interpretation"] or {}, "regions": asset["regions"] or [],
            "background": asset["background"], "prepared": asset["prepared"],
        }

    def _on_prepare_done(self, asset_id: str, fut: Future) -> None:
        if not self.db.one("SELECT id FROM assets WHERE id=?", (asset_id,)):
            return
        try:
            res = fut.result()
        except TaskError as exc:
            self.db.update("assets", asset_id, {"status": "failed", "error": exc.error})
            return
        except BaseException as exc:  # cancelled/unexpected
            self.db.update("assets", asset_id, {"status": "failed", "error": {"code": "INTERNAL_ERROR", "message": str(exc) or "Intake was interrupted."}})
            return
        intake = res["intake"]
        if intake["status"] == "unsupported":
            self.db.update("assets", asset_id, {"status": "failed", "error": {"code": intake.get("code", "UNSUPPORTED"), "message": intake["message"]}})
            return
        prepared = res.get("meta") or {"hdu_thumbs": res.get("hdu_thumbs", {})}
        self.db.update("assets", asset_id, {"status": intake["status"], "prepared": prepared, "error": None})

    # ------------------------------------------------------------------ jobs
    def wake(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def recompute_job(self, job_id: str) -> None:
        states = [i["state"] for i in self.db.all("SELECT state FROM job_items WHERE job_id=?", (job_id,))]
        if any(s == "running" for s in states):
            new = "running"
        elif any(s == "queued" for s in states):
            started = any(s in ("succeeded", "succeeded_with_notes", "failed", "cancelled") for s in states)
            new = "running" if started else "queued"
        elif states and all(s == "cancelled" for s in states):
            new = "cancelled"
        elif states and all(s == "failed" for s in states):
            new = "failed"
        elif any(s == "interrupted" for s in states):
            new = "interrupted"
        elif any(s in ("failed", "cancelled", "succeeded_with_notes") for s in states):
            new = "succeeded_with_notes"
        else:
            new = "succeeded"
        self.db.update("jobs", job_id, {"state": new, "updated_at": now()})

    def cancel_job(self, job_id: str) -> bool:
        if not self.db.one("SELECT id FROM jobs WHERE id=?", (job_id,)):
            return False
        self.db.execute("UPDATE job_items SET state='cancelled', finished_at=? WHERE job_id=? AND state='queued'", (now(), job_id))
        cur = self._current
        if cur and cur["kind"] == "enhance" and cur["job_id"] == job_id:
            self._cancel.set()  # cooperative: honored between stages/tiles
        self.recompute_job(job_id)
        self.wake()
        return True

    def retry_items(self, job_id: str) -> None:
        self.db.execute("UPDATE job_items SET state='queued', stage=NULL, error=NULL, finished_at=NULL WHERE job_id=? AND state IN ('interrupted','failed','cancelled')", (job_id,))
        self.db.execute("UPDATE jobs SET state='queued', updated_at=? WHERE id=?", (now(), job_id))
        self.wake()

    def cache_key(self, asset: dict[str, Any], recipe: dict[str, Any], settings: dict[str, Any], planned_backend: str) -> str:
        bg = asset.get("background") if recipe.get("background", {}).get("enabled") else None
        material = {
            "source": asset["sha256"], "engine": PIPELINE_VERSION, "deps": dependency_versions()["packages"],
            "recipe": parse_recipe(recipe).model_dump(), "interpretation": asset["interpretation"],
            "regions": asset["regions"] if recipe.get("protect_regions", True) else [],
            "background": bg if bg and bg.get("confirmed") else None,
            "frame": (asset.get("prepared") or {}).get("frame"), "backend": planned_backend, "precision": "float32",
            "strip_location": bool(settings.get("strip_location", True)),
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()

    def planned_backend(self, settings: dict[str, Any], asset: dict[str, Any]) -> str:
        prepared = asset.get("prepared") or {}
        h, w = int(prepared.get("height", 0) or 0), int(prepared.get("width", 0) or 0)
        opts = ExecutionOptions(
            device=settings.get("device", "auto"),
            gpu_available=bool(self.probe_info and self.probe_info.get("ok")),
            gpu_threshold_pixels=int(settings.get("gpu_threshold_pixels", self.cfg.gpu_threshold_pixels)),
        )
        return choose_backend(opts, h, w, 3)[0] if h * w else "cpu"

    # ------------------------------------------------------------------ scheduling
    def _next_item(self) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT i.*, j.recipe AS j_recipe, j.preset_snapshot AS j_preset, j.settings_snapshot AS j_settings, j.force AS j_force "
            "FROM job_items i JOIN jobs j ON j.id=i.job_id WHERE i.state='queued' ORDER BY j.created_at, i.position LIMIT 1"
        )

    def _has_work(self) -> bool:
        return bool(self._small) or self._next_item() is not None

    def _scheduler_loop(self) -> None:
        while not self._stop:
            with self._cond:
                while not self._stop and (self._current is not None or not self._has_work()):
                    self._cond.wait(0.5)
                if self._stop:
                    return
                if self._small:
                    task, fut = self._small.pop(0)
                    self._dispatch({"task": task, "kind": task["kind"], "future": fut, "task_id": task["task_id"]})
                    continue
            item = self._next_item()
            if item is None:
                continue
            try:
                self._start_item(item)
            except Exception as exc:  # never kill the scheduler
                self._fail_item(item["id"], item["job_id"], {"code": "INTERNAL_ERROR", "message": "The job could not be started.", "detail": str(exc)})

    def _dispatch(self, cur: dict[str, Any]) -> None:
        self._current = cur
        self._cancel.clear()
        self._task_q.put(cur["task"])

    def _start_item(self, item: dict[str, Any]) -> None:
        asset = self.db.one("SELECT * FROM assets WHERE id=?", (item["asset_id"],))
        if not asset or asset["status"] != "ready":
            self._fail_item(item["id"], item["job_id"], {"code": "ASSET_NOT_READY", "message": "This image is not ready to be enhanced (confirm any open questions first)."})
            return
        recipe = item["j_recipe"]
        settings = item["j_settings"] or {}
        key = self.cache_key(asset, recipe, settings, self.planned_backend(settings, asset))
        if not item["j_force"]:
            hit = self.db.one("SELECT * FROM runs WHERE asset_id=? AND cache_key=? ORDER BY created_at DESC LIMIT 1", (asset["id"], key))
            if hit and (self.cfg.runs_dir / hit["id"] / "processing.json").exists():
                self.db.update("job_items", item["id"], {
                    "state": hit["state"], "run_id": hit["id"], "stage": None, "finished_at": now(),
                    "notes": [{"kind": "cache", "message": "An identical result already existed and was reused; no work was repeated."}],
                })
                self.recompute_job(item["job_id"])
                return
        serial = int(self.db.one("SELECT COUNT(*) AS n FROM runs WHERE asset_id=?", (asset["id"],))["n"]) + 1
        run_id = new_id("run_")
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(asset["filename"]).stem[:40]) or "image"
        run_name = f"{safe}__{asset['sha256'][:8]}__run-{serial:03d}"
        task = {
            "task_id": new_id("t_"), "kind": "enhance", "job_id": item["job_id"], "item_id": item["id"], "run_id": run_id,
            "run_name": run_name, "run_dir": str(self.cfg.runs_dir / run_id), "asset": self._asset_payload(asset),
            "recipe": recipe, "preset_snapshot": item["j_preset"],
            "settings": {**settings, "gpu_memory_fraction": self.cfg.gpu_memory_fraction}, "created_at": now(),
        }
        self.db.update("job_items", item["id"], {"state": "running", "started_at": now(), "stage": "Starting"})
        self.recompute_job(item["job_id"])
        cur = {"task": task, "kind": "enhance", "job_id": item["job_id"], "item_id": item["id"], "task_id": task["task_id"], "future": None,
               "cache_key": key, "serial": serial, "run_id": run_id, "asset_id": asset["id"], "recipe": recipe, "run_name": run_name}
        with self._cond:
            self._dispatch(cur)

    def _fail_item(self, item_id: str, job_id: str, error: dict[str, Any]) -> None:
        self.db.update("job_items", item_id, {"state": "failed", "error": error, "finished_at": now(), "stage": None})
        self.recompute_job(job_id)

    # ------------------------------------------------------------------ worker messages
    def _reader_loop(self) -> None:
        while not self._stop:
            try:
                msg = self._result_q.get(timeout=0.5)
            except queue.Empty:
                self._check_worker_alive()
                continue
            except Exception:
                continue
            try:
                self._on_message(msg)
            except Exception:  # keep reading
                pass

    def _check_worker_alive(self) -> None:
        if self._stop or self._proc is None or self._proc.is_alive():
            return
        cur = self._current
        code = self._proc.exitcode
        self._spawn()
        if cur is not None:
            self._finish(cur, "error", {"code": "WORKER_CRASHED", "message": "The processing worker stopped unexpectedly. The image was not changed; try again.", "detail": f"exit code {code}"})

    def _on_message(self, msg: tuple[str, str, Any]) -> None:
        kind, task_id, payload = msg
        cur = self._current
        if cur is None or cur["task_id"] != task_id:
            return
        if kind == "progress":
            if cur["kind"] == "enhance":
                live = self.live.setdefault(cur["item_id"], {})
                if "stage" in payload:
                    live["stage"] = payload["stage"]
                    self.db.update("job_items", cur["item_id"], {"stage": payload["stage"]})
                if "label" in payload:
                    live["label"] = payload["label"]
                    self.db.update("job_items", cur["item_id"], {"backend_label": payload["label"]})
            return
        self._finish(cur, kind, payload)

    def _finish(self, cur: dict[str, Any], kind: str, payload: Any) -> None:
        with self._cond:
            self._current = None
            self._cond.notify_all()
        if cur["kind"] != "enhance":
            fut: Future = cur["future"]
            if kind == "done":
                if cur["kind"] == "probe":
                    self.probe_info = payload
                fut.set_result(payload)
            elif kind == "error":
                fut.set_exception(TaskError(payload))
            else:
                fut.cancel()
            return
        item_id, job_id = cur["item_id"], cur["job_id"]
        self.live.pop(item_id, None)
        t = now()
        if kind == "done":
            notes = [{"kind": o["status"], "operation": o["name"], "message": o["reason"]} for o in payload["operations"] if o["status"] in ("skipped", "reduced")]
            notes += [{"kind": "fallback", "message": f"{f['from']}: {f['message']}"} for f in payload.get("fallbacks", [])]
            if payload["needs_review"]:
                notes.append({"kind": "review", "message": "New clipping stayed above the guardrail even after reducing strength; the conservative result was kept. Please review."})
            recipe_hash = hashlib.sha256(json.dumps(parse_recipe(cur["recipe"]).model_dump(), sort_keys=True).encode()).hexdigest()[:16]
            self.db.insert("runs", {
                "id": cur["run_id"], "asset_id": cur["asset_id"], "job_id": job_id, "created_at": t, "state": payload["state"], "serial": cur["serial"],
                "cache_key": cur["cache_key"], "recipe": cur["recipe"], "recipe_hash": recipe_hash,
                "summary": {"text": payload["summary"], "operations": payload["operations"], "seconds": payload["seconds"], "run_name": cur["run_name"]},
                "exports": payload["exports"], "report_path": payload["report_path"], "needs_review": int(payload["needs_review"]), "backend_label": payload["backend_label"],
            })
            self.db.update("job_items", item_id, {"state": payload["state"], "run_id": cur["run_id"], "notes": notes, "finished_at": t, "stage": None, "backend_label": payload["backend_label"]})
        elif kind == "cancelled":
            self.db.update("job_items", item_id, {"state": "cancelled", "finished_at": t, "stage": None})
        else:
            self.db.update("job_items", item_id, {"state": "failed", "error": payload, "finished_at": t, "stage": None})
        self.recompute_job(job_id)
