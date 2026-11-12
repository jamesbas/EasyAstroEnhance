from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..db import new_id, now
from ..models.api import JobCreate
from .common import ApiError, cfg_of, coord_of, db_of, serialize_job, settings_snapshot

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=202)
async def create_job(request: Request, body: JobCreate) -> dict[str, Any]:
    db, coord, cfg = db_of(request), coord_of(request), cfg_of(request)
    existing = db.one("SELECT * FROM jobs WHERE request_key=?", (body.request_key,))
    if existing:  # idempotent retry: repeat clicks never duplicate expensive work
        return {**serialize_job(db, coord, existing), "idempotent_replay": True, "skipped": []}

    eligible, skipped = [], []
    seen: set[str] = set()
    for aid in body.asset_ids:
        if aid in seen:
            continue
        seen.add(aid)
        a = db.one("SELECT * FROM assets WHERE id=?", (aid,))
        if not a:
            skipped.append({"asset_id": aid, "code": "ASSET_NOT_FOUND", "message": "That image is no longer in the app."})
        elif a["status"] != "ready":
            msg = {
                "needs_input": "Answer the intake question for this image before enhancing it.",
                "inspecting": "This image is still being prepared.",
                "failed": "This file could not be read.",
            }.get(a["status"], "This image is not ready.")
            skipped.append({"asset_id": aid, "code": "ASSET_NOT_READY", "message": msg, "filename": a["filename"]})
        else:
            busy = db.one("SELECT 1 AS x FROM job_items WHERE asset_id=? AND state IN ('queued','running')", (aid,))
            if busy:
                skipped.append({"asset_id": aid, "code": "ALREADY_QUEUED", "message": "This image is already queued or processing.", "filename": a["filename"]})
            else:
                eligible.append(a)
    if not eligible:
        raise ApiError(422, "NOTHING_TO_PROCESS", "None of the selected images can be enhanced right now.", skipped)

    snapshot = None
    if body.preset_id:
        p = db.one("SELECT * FROM presets WHERE id=?", (body.preset_id,))
        if p:  # snapshot into the job: later preset edits never change past results
            snapshot = {"id": p["id"], "name": p["name"], "recipe": p["recipe"], "schema_version": p["schema_version"], "engine_version": p["engine_version"]}
    job_id = new_id("job_")
    t = now()
    with db.transaction():
        db.insert("jobs", {
            "id": job_id, "request_key": body.request_key, "created_at": t, "updated_at": t, "state": "queued",
            "recipe": body.recipe.model_dump(), "preset_snapshot": snapshot, "settings_snapshot": settings_snapshot(db, cfg), "force": int(body.force),
        })
        for pos, a in enumerate(eligible):
            db.insert("job_items", {"id": new_id("it_"), "job_id": job_id, "asset_id": a["id"], "position": pos, "state": "queued"})
    coord.wake()
    return {**serialize_job(db, coord, db.one("SELECT * FROM jobs WHERE id=?", (job_id,))), "idempotent_replay": False, "skipped": skipped}  # type: ignore[arg-type]


@router.get("")
async def list_jobs(request: Request, active: bool = False) -> dict[str, Any]:
    db, coord = db_of(request), coord_of(request)
    where = "WHERE state IN ('queued','running')" if active else ""
    rows = db.all(f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT 50")
    return {"jobs": [serialize_job(db, coord, j) for j in rows]}


@router.get("/{job_id}")
async def get_job(request: Request, job_id: str) -> dict[str, Any]:
    db = db_of(request)
    job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job:
        raise ApiError(404, "JOB_NOT_FOUND", "That job no longer exists.")
    return serialize_job(db, coord_of(request), job)


@router.post("/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    db, coord = db_of(request), coord_of(request)
    if not coord.cancel_job(job_id):
        raise ApiError(404, "JOB_NOT_FOUND", "That job no longer exists.")
    return serialize_job(db, coord, db.one("SELECT * FROM jobs WHERE id=?", (job_id,)))  # type: ignore[arg-type]


@router.post("/{job_id}/retry")
async def retry_job(request: Request, job_id: str) -> dict[str, Any]:
    db, coord = db_of(request), coord_of(request)
    if not db.one("SELECT id FROM jobs WHERE id=?", (job_id,)):
        raise ApiError(404, "JOB_NOT_FOUND", "That job no longer exists.")
    coord.retry_items(job_id)
    return serialize_job(db, coord, db.one("SELECT * FROM jobs WHERE id=?", (job_id,)))  # type: ignore[arg-type]
