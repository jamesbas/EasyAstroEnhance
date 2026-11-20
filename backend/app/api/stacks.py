"""Stacking: scan folders of frames (read-only), queue a stack, follow its progress, cancel or retry.

A finished stack becomes a new image in the app (a linear FITS). Enhancement then runs only when the user asked for
it when starting the stack ("Enhance automatically when stacking finishes"); otherwise the user adjusts and enhances.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from ..db import Database, new_id, now
from ..models.api import FolderBrowseIn, StackCreate, StackFolders
from ..processing.imagedata import ProcessingError
from ..processing.stacking.stack import StackRequest, plan
from ..services import folders
from ..services.queue import Coordinator
from .common import STATUS_LABELS, ApiError, cfg_of, coord_of, db_of, settings_snapshot

router = APIRouter(prefix="/stacks", tags=["stacks"])


def _request_of(body: StackFolders, **extra: Any) -> StackRequest:
    clean = lambda v: (v.strip().strip('"') or None) if v else None  # noqa: E731 - pasted Windows paths often carry quotes
    return StackRequest(folder=clean(body.folder) or "", mode=body.mode, darks=clean(body.darks), flats=clean(body.flats),
                        bias=clean(body.bias), darkflats=clean(body.darkflats), **extra)


async def _plan(req: StackRequest) -> dict[str, Any]:
    try:
        return await run_in_threadpool(plan, req)  # reads FITS headers only
    except ProcessingError as exc:
        raise ApiError(422, exc.code, exc.message) from exc


def _summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    keys = ("mode", "frames_used", "frames_total", "rejected_frames", "registration", "integration", "drizzle", "calibration",
            "normalization", "weights", "rejected_pixel_fraction", "seconds", "device", "device_note", "output", "lights", "excluded", "skipped")
    return {k: report[k] for k in keys if k in report}


def serialize_stack(db: Database, coord: Coordinator, s: dict[str, Any]) -> dict[str, Any]:
    live = coord.live.get(s["id"], {}) if s["state"] == "running" else {}
    asset = db.one("SELECT id, status, filename FROM assets WHERE id=?", (s["asset_id"],)) if s.get("asset_id") else None
    return {
        "id": s["id"], "name": s["name"], "state": s["state"], "status_label": STATUS_LABELS.get(s["state"], s["state"]),
        "created_at": s["created_at"], "finished_at": s.get("finished_at"),
        "stage": live.get("stage") or s.get("stage"), "progress": live.get("progress", s.get("progress")),
        "request": s["request"], "auto_enhance": bool(s["auto_enhance"]), "job_id": s.get("job_id"),
        "asset_id": asset["id"] if asset else None, "asset_status": asset["status"] if asset else None,
        "report": _summary(s.get("report")), "error": s.get("error"),
    }


def _name_for(req: StackRequest) -> str:
    stem = Path(req.folder).name or "Stack"
    return stem[:-4] if stem.lower().endswith("_sub") else stem


@router.post("/browse")
async def browse_folders(request: Request, body: FolderBrowseIn) -> dict[str, Any]:
    """List the subfolders of a folder (names and FITS counts only, read-only). Without a path: drives, common folders,
    recently stacked folders and their sibling ``*_sub`` folders."""
    recent = db_of(request).get_setting(folders.RECENT_SETTING, []) or []
    return await run_in_threadpool(folders.browse, body.path, recent)


@router.post("/scan")
async def scan(request: Request, body: StackFolders) -> dict[str, Any]:
    req = _request_of(body)
    return {**await _plan(req), "name": _name_for(req)}


@router.post("", status_code=202)
async def create_stack(request: Request, body: StackCreate) -> dict[str, Any]:
    db, coord, cfg = db_of(request), coord_of(request), cfg_of(request)
    existing = db.one("SELECT * FROM stacks WHERE request_key=?", (body.request_key,))
    if existing:
        return {**serialize_stack(db, coord, existing), "idempotent_replay": True}
    if body.auto_enhance and body.recipe is None:
        raise ApiError(422, "RECIPE_REQUIRED", "Choose the enhancement settings to use after stacking, or turn off automatic enhancement.")
    req = _request_of(body, scale=body.scale, grading=body.grading, rejection=body.rejection)
    p = await _plan(req)
    if not p["can_stack"]:
        raise ApiError(422, "NOTHING_TO_STACK", "This folder does not hold at least two light frames that can be stacked together.", p)
    if body.scale == 2 and not p["drizzle_available"]:
        req.scale = 1
    snapshot = None
    if body.auto_enhance and body.preset_id:
        pr = db.one("SELECT * FROM presets WHERE id=?", (body.preset_id,))
        if pr:
            snapshot = {"id": pr["id"], "name": pr["name"], "recipe": pr["recipe"], "schema_version": pr["schema_version"], "engine_version": pr["engine_version"]}
    req.mode = p["mode"]
    stack_id = new_id("stk_")
    t = now()
    db.insert("stacks", {
        "id": stack_id, "request_key": body.request_key, "created_at": t, "updated_at": t, "state": "queued", "name": _name_for(req),
        "request": req.to_dict(), "auto_enhance": int(body.auto_enhance),
        "recipe": body.recipe.model_dump() if body.auto_enhance and body.recipe else None,
        "preset_snapshot": snapshot, "settings_snapshot": settings_snapshot(db, cfg),
    })
    coord.wake()
    db.set_setting(folders.RECENT_SETTING, folders.remember(db.get_setting(folders.RECENT_SETTING, []) or [], req.folder))
    return {**serialize_stack(db, coord, db.one("SELECT * FROM stacks WHERE id=?", (stack_id,))), "idempotent_replay": False}  # type: ignore[arg-type]


@router.get("")
def list_stacks(request: Request, active: bool = False) -> dict[str, Any]:
    db, coord = db_of(request), coord_of(request)
    where = "WHERE state IN ('queued','running')" if active else ""
    return {"stacks": [serialize_stack(db, coord, s) for s in db.all(f"SELECT * FROM stacks {where} ORDER BY created_at DESC LIMIT 50")]}


def _get(request: Request, stack_id: str) -> dict[str, Any]:
    s = db_of(request).one("SELECT * FROM stacks WHERE id=?", (stack_id,))
    if not s:
        raise ApiError(404, "STACK_NOT_FOUND", "That stack no longer exists.")
    return s


@router.get("/{stack_id}")
def get_stack(request: Request, stack_id: str) -> dict[str, Any]:
    s = _get(request, stack_id)
    out = serialize_stack(db_of(request), coord_of(request), s)
    out["full_report"] = s.get("report")
    return out


@router.post("/{stack_id}/cancel")
def cancel_stack(request: Request, stack_id: str) -> dict[str, Any]:
    _get(request, stack_id)
    coord_of(request).cancel_stack(stack_id)
    return serialize_stack(db_of(request), coord_of(request), _get(request, stack_id))


@router.post("/{stack_id}/retry")
def retry_stack(request: Request, stack_id: str) -> dict[str, Any]:
    _get(request, stack_id)
    coord_of(request).retry_stack(stack_id)
    return serialize_stack(db_of(request), coord_of(request), _get(request, stack_id))
