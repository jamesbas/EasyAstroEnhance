"""Shared API plumbing: app-state accessors, error type, serializers."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from ..config import Config
from ..db import Database
from ..processing.readers import evaluate_intake
from ..services.queue import Coordinator, TaskError
from ..services.results import current_run


class ApiError(HTTPException):
    """HTTP error with a stable code and a readable message (never a traceback as the main message)."""

    def __init__(self, status: int, code: str, message: str, detail: Any = None):
        super().__init__(status_code=status, detail={"code": code, "message": message, "detail": detail})


def cfg_of(request: Request) -> Config:
    return request.app.state.cfg


def db_of(request: Request) -> Database:
    return request.app.state.db


def coord_of(request: Request) -> Coordinator:
    return request.app.state.coordinator


def get_asset(request: Request, asset_id: str) -> dict[str, Any]:
    a = db_of(request).one("SELECT * FROM assets WHERE id=?", (asset_id,))
    if not a:
        raise ApiError(404, "ASSET_NOT_FOUND", "That image is no longer in the app.")
    return a


async def run_worker_task(request: Request, kind: str, payload: dict[str, Any], timeout: float = 180.0) -> dict[str, Any]:
    fut = coord_of(request).run_task(kind, payload)
    try:
        return await asyncio.wait_for(asyncio.wrap_future(fut), timeout)
    except TaskError as exc:
        e = exc.error
        raise ApiError(422, e.get("code", "TASK_FAILED"), e.get("message", "The operation failed."), e.get("detail")) from exc
    except asyncio.TimeoutError as exc:
        raise ApiError(504, "TIMEOUT", "The operation took too long. Try again.") from exc
    except asyncio.CancelledError:
        raise


def settings_snapshot(db: Database, cfg: Config) -> dict[str, Any]:
    return {
        "device": "cpu" if cfg.cpu_only else db.get_setting("compute.device", "auto"),
        "gpu_memory_fraction": min(float(db.get_setting("compute.gpu_memory_fraction", cfg.gpu_memory_fraction)), 0.7),
        "ram_fraction": float(db.get_setting("compute.ram_fraction", cfg.ram_fraction)),
        "gpu_threshold_pixels": cfg.gpu_threshold_pixels,
        "strip_location": bool(db.get_setting("strip_location", True)),
    }


STATUS_LABELS = {
    "succeeded": "Complete",
    "succeeded_with_notes": "Complete with notes",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "interrupted": "Interrupted",
    "queued": "Queued",
    "running": "Processing",
}


def serialize_run(run: dict[str, Any]) -> dict[str, Any]:
    ex = [{**e, "url": f"/api/v1/runs/{run['id']}/exports/{e['kind']}"} for e in (run.get("exports") or [])]
    return {
        "id": run["id"], "asset_id": run["asset_id"], "created_at": run["created_at"], "state": run["state"], "serial": run["serial"],
        "recipe": run["recipe"], "recipe_hash": run["recipe_hash"], "summary": (run.get("summary") or {}).get("text"),
        "operations": (run.get("summary") or {}).get("operations", []), "run_name": (run.get("summary") or {}).get("run_name"),
        "seconds": (run.get("summary") or {}).get("seconds"), "needs_review": bool(run.get("needs_review")),
        "backend_label": run.get("backend_label"), "exports": ex,
        "preview_url": f"/api/v1/runs/{run['id']}/preview",
    }


def serialize_item(db: Database, coord: Coordinator, item: dict[str, Any]) -> dict[str, Any]:
    live = coord.live.get(item["id"], {})
    asset = db.one("SELECT filename FROM assets WHERE id=?", (item["asset_id"],))
    return {
        "id": item["id"], "asset_id": item["asset_id"], "filename": asset["filename"] if asset else None, "state": item["state"],
        "status_label": STATUS_LABELS.get(item["state"], item["state"]), "stage": live.get("stage") or item.get("stage"),
        "backend_label": live.get("label") or item.get("backend_label"), "notes": item.get("notes") or [], "run_id": item.get("run_id"),
        "error": item.get("error"),
    }


def serialize_job(db: Database, coord: Coordinator, job: dict[str, Any]) -> dict[str, Any]:
    items = db.all("SELECT * FROM job_items WHERE job_id=? ORDER BY position", (job["id"],))
    out_items = [serialize_item(db, coord, i) for i in items]
    running = next((i for i in out_items if i["state"] == "running"), None)
    return {
        "id": job["id"], "state": job["state"], "status_label": STATUS_LABELS.get(job["state"], job["state"]),
        "created_at": job["created_at"], "items": out_items, "processing_label": running["backend_label"] if running else None,
        "recipe": job["recipe"],
    }


def asset_hubble_input(a: dict[str, Any]) -> str:
    prepared = a.get("prepared") or {}
    if (a["status"] != "ready" or a["format"] != "fits" or prepared.get("state") != "linear"
            or prepared.get("channel_layout") != "rgb"):
        return "unsupported"
    detected = prepared.get("hubble_input", "unknown")
    if detected == "unknown" and (a.get("interpretation") or {}).get("dualband_confirmed") is True:
        return "dualband"
    return detected


def serialize_asset(db: Database, coord: Coordinator, cfg: Config, a: dict[str, Any]) -> dict[str, Any]:
    insp = a.get("inspection") or {}
    prepared = a.get("prepared") or {}
    intake = None
    if insp and a["status"] != "failed":
        intake = evaluate_intake(insp, a["interpretation"] or {})
    item = db.one(
        "SELECT i.* FROM job_items i JOIN jobs j ON j.id=i.job_id WHERE i.asset_id=? ORDER BY j.created_at DESC, i.position DESC LIMIT 1", (a["id"],)
    )
    run = current_run(db, a["id"])
    stk = db.one("SELECT id, name, report FROM stacks WHERE asset_id=?", (a["id"],))
    stack_info = None
    if stk and stk.get("report"):
        r = stk["report"]
        stack_info = {
            "id": stk["id"], "name": stk["name"], "mode": r.get("mode"), "frames_used": r.get("frames_used"),
            "frames_total": r.get("frames_total"), "rejected_frames": r.get("rejected_frames", []),
            "total_exposure_s": (r.get("lights") or {}).get("total_exposure_s"), "drizzle": bool(r.get("drizzle")),
            "seconds": r.get("seconds"), "calibration": {k: (r.get("calibration") or {}).get(k, 0) for k in ("darks", "flats", "bias", "dark_flats")},
            "defective_pixels": ((r.get("calibration") or {}).get("defective_pixels") or {}).get("count"),
            "mosaic_canvas": (r.get("mosaic") or {}).get("canvas"),
            "saturation_warning": (r.get("saturation") or {}).get("warning"),
            "color_balance": r.get("color_balance"),
        }
    status = a["status"]
    if status == "failed":
        label = "Failed"
    elif status == "inspecting":
        label = "Inspecting"
    elif status == "needs_input":
        label = "Needs input"
    elif item and item["state"] in ("queued", "running"):
        label = STATUS_LABELS[item["state"]]
    elif item:
        label = STATUS_LABELS.get(item["state"], "Ready")
    else:
        label = "Ready"
    return {
        "id": a["id"], "filename": a["filename"], "format": a["format"], "size_bytes": a["size_bytes"], "sha256": a["sha256"],
        "status": status, "status_label": label, "error": a.get("error"),
        "hubble_input": asset_hubble_input(a),
        "width": prepared.get("width") or insp.get("width"), "height": prepared.get("height") or insp.get("height"),
        "channel_layout": prepared.get("channel_layout") or insp.get("channel_layout"), "bit_depth": insp.get("bit_depth"),
        "questions": (intake or {}).get("questions", []), "interpretation": a["interpretation"] or {},
        "resolved": (intake or {}).get("resolved"), "can_process": bool(intake and intake["can_process"] and status == "ready"),
        "intake_message": (intake or {}).get("message"),
        "candidates": [
            {"index": c["index"], "name": c["name"], "shape": c["shape"], "kind": c["kind"],
             "thumb_url": (f"/api/v1/assets/{a['id']}/files/hdu-{c['index']}.jpg" if str(c["index"]) in (prepared.get("hdu_thumbs") or {}) else None)}
            for c in insp.get("candidates", []) if c.get("supported")
        ],
        "baseline": {
            "label": prepared.get("label"), "preview_only": prepared.get("preview_only"), "frame": prepared.get("frame"),
            "histogram": prepared.get("histogram"), "invalid_pixels": prepared.get("invalid_pixels"), "domain": prepared.get("domain"),
            "orientation_transform": prepared.get("orientation_transform"), "notes": prepared.get("notes", []),
            "has_sensitive_metadata": prepared.get("has_sensitive_metadata", False),
        } if prepared.get("label") else None,
        "regions": a["regions"] or [], "background": a["background"],
        "thumb_url": f"/api/v1/assets/{a['id']}/thumb" if prepared.get("label") else None,
        "preview_url": f"/api/v1/assets/{a['id']}/preview" if prepared.get("label") else None,
        "latest_item": serialize_item(db, coord, item) if item else None,
        "latest_run": serialize_run(run) if run else None,  # the current result (newest unless the user went back)
        "run_count": db.one("SELECT COUNT(*) AS n FROM runs WHERE asset_id=?", (a["id"],))["n"],
        "stack": stack_info,
        "sky_solution": sky_solution_summary(cfg, a),
        "created_at": a["created_at"],
    }


SKY_SUMMARY_KEYS = ("status", "source", "reason", "center", "center_ra", "center_dec", "scale_arcsec", "north_angle_deg", "field_deg",
                    "mirrored", "sip", "matches", "rms_px", "brightest_fraction", "detected_stars", "seconds", "header_note", "hints")


def sky_solution_summary(cfg: Config, a: dict[str, Any]) -> dict[str, Any] | None:
    """The stored sky solution for the asset's current HDU (an intake change makes an older one stale), without WCS cards."""
    import json

    try:
        sol = json.loads((cfg.assets_dir / a["id"] / "sky-solution.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if sol.get("hdu") != (a.get("interpretation") or {}).get("hdu") or sol.get("source_sha256") != a.get("sha256"):
        return None
    return {k: sol.get(k) for k in SKY_SUMMARY_KEYS}
