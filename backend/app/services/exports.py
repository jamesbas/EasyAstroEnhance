"""Batch ZIP export (built in a background thread; only allow-listed artifacts of completed runs) and on-request
rendering of deferred run exports."""
from __future__ import annotations

import hashlib
import json
import threading
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Config
from ..db import Database, new_id, now
from ..processing import export as exp

ALLOWED_KINDS = {"png", "tiff", "jpeg", "comparison", "report", "summary", "fits", "linear-tiff"}
DEFAULT_KINDS = ("png", "report", "summary")
_STORED = {".png", ".jpg", ".tif"}  # already compressed
_render_lock = threading.Lock()
_cancelled: set[str] = set()


class ExportCancelled(Exception):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(4 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def ensure_export(cfg: Config, db: Database, run: dict[str, Any], entry: dict[str, Any]) -> Path:
    """Path of a run export, rendering a deferred one first (once; atomic) and recording its size and SHA-256."""
    run_dir = cfg.runs_dir / run["id"]
    path = run_dir / entry["filename"]
    if path.exists() or not entry.get("deferred"):
        return path
    with _render_lock:
        if path.exists():
            return path
        if entry["filename"] != exp.DEFERRED_TIFF:
            raise FileNotFoundError(entry["filename"])
        report_path = run_dir / "processing.json"
        engine = json.loads(report_path.read_text(encoding="utf-8"))["applied"]["engine_version"] if report_path.exists() else exp.PIPELINE_VERSION
        tmp = path.with_name(path.name + ".partial")
        exp.write_tiff16_u16(tmp, np.load(run_dir / "display.npy", mmap_mode="r"), engine)
        tmp.replace(path)
        fresh = db.one("SELECT exports FROM runs WHERE id=?", (run["id"],))
        exports = [
            {**e, "bytes": path.stat().st_size, "sha256": _sha256(path)} if e["kind"] == entry["kind"] else e
            for e in ((fresh or {}).get("exports") or run["exports"] or [])
        ]
        db.update("runs", run["id"], {"exports": exports})
    return path


def start_batch(cfg: Config, db: Database, run_ids: list[str], include: list[str]) -> str:
    export_id = new_id("zip_")
    db.insert("exports", {"id": export_id, "state": "building", "created_at": now(), "path": None, "detail": {"done": 0, "total": len(run_ids)}})
    threading.Thread(target=_build, args=(cfg, db, export_id, run_ids, include), daemon=True).start()
    return export_id


def cancel_batch(db: Database, export_id: str) -> bool:
    """Request cancellation of a ZIP that is still building; the builder stops before its next file."""
    e = db.one("SELECT state FROM exports WHERE id=?", (export_id,))
    if not e or e["state"] != "building":
        return False
    _cancelled.add(export_id)
    return True


def _build(cfg: Config, db: Database, export_id: str, run_ids: list[str], include: list[str]) -> None:
    kinds = set(DEFAULT_KINDS) | (set(include) & ALLOWED_KINDS)
    out = cfg.exports_dir / f"{export_id}.zip"
    partial = out.with_suffix(".zip.partial")
    summary: list[dict[str, Any]] = []

    def check() -> None:
        if export_id in _cancelled:
            raise ExportCancelled()

    try:
        with zipfile.ZipFile(partial, "w") as zf:
            for i, rid in enumerate(run_ids, start=1):
                check()
                run = db.one("SELECT * FROM runs WHERE id=?", (rid,))
                if not run:
                    continue
                asset = db.one("SELECT filename FROM assets WHERE id=?", (run["asset_id"],))
                folder = (run["summary"] or {}).get("run_name") or rid
                files = []
                for e in run["exports"] or []:
                    if e["kind"] not in kinds:
                        continue
                    check()
                    try:
                        src = ensure_export(cfg, db, run, e)
                    except (OSError, KeyError, ValueError):
                        continue
                    if not src.exists():
                        continue
                    ext = Path(e["filename"]).suffix.lower()
                    zf.write(src, f"{folder}/{e['filename']}", compress_type=zipfile.ZIP_STORED if ext in _STORED else zipfile.ZIP_DEFLATED)
                    files.append(e["filename"])
                summary.append({"run_id": rid, "folder": folder, "source": asset["filename"] if asset else None, "state": run["state"], "result": (run["summary"] or {}).get("text"), "files": files})
                db.update("exports", export_id, {"detail": {"done": i, "total": len(run_ids)}})
            lines = ["EasyAstroEnhance batch summary", f"Created: {now()}", ""]
            for s in summary:
                lines += [f"{s['folder']}/  ({s['source']})", f"  {s['state']}: {s['result']}", f"  files: {', '.join(s['files'])}", ""]
            zf.writestr("batch-summary.txt", "\n".join(lines))
            zf.writestr("batch-summary.json", json.dumps(summary, indent=2))
        check()
        partial.replace(out)
        db.update("exports", export_id, {"state": "ready", "path": str(out), "detail": {"done": len(run_ids), "total": len(run_ids), "bytes": out.stat().st_size}})
    except ExportCancelled:
        partial.unlink(missing_ok=True)
        db.update("exports", export_id, {"state": "cancelled", "detail": {"done": 0, "total": len(run_ids)}})
    except Exception as exc:
        partial.unlink(missing_ok=True)
        db.update("exports", export_id, {"state": "failed", "detail": {"error": {"code": "ZIP_FAILED", "message": "The ZIP file could not be created.", "detail": str(exc)}}})
    finally:
        _cancelled.discard(export_id)
