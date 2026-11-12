from __future__ import annotations

import asyncio
import errno
import hashlib
import re
import shutil
import stat
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response

from ..db import new_id, now
from ..models.api import BackgroundIn, InterpretationIn, RegionsIn
from ..processing.imagedata import ProcessingError
from ..processing.masks import validate_regions
from ..processing.readers import detect_format, evaluate_intake, inspect_file
from ..services import previews
from .common import (
    ApiError, cfg_of, coord_of, db_of, get_asset, run_worker_task, serialize_asset,
)

router = APIRouter(prefix="/assets", tags=["assets"])
_EXT = {"jpeg": ".jpg", "tiff": ".tif", "fits": ".fits"}
_SAFE_FILE = re.compile(r"^(bgprev-[0-9a-f]+-\d+\.jpg|starmask-[0-9a-f]+\.png|hdu-\d+\.jpg|thumb\.jpg)$")


def clean_name(name: str | None) -> str:
    base = Path((name or "image").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", base).strip(". ") or "image"
    return base[:120]


async def _store_upload(request: Request, upload: UploadFile, asset_dir: Path) -> tuple[Path, str, int]:
    """Stream an upload to disk, hashing as we go; enforce byte limit and free-space floor."""
    cfg = cfg_of(request)
    tmp = asset_dir / "upload.part"
    if shutil.disk_usage(asset_dir).free < cfg.min_free_bytes:
        raise ProcessingError("DISK_FULL", "The disk is nearly full; free some space and try again.")
    h = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > cfg.max_file_bytes:
                    raise ProcessingError("FILE_TOO_LARGE", f"This file is larger than the {cfg.max_file_bytes // (1024 * 1024)} MiB limit.")
                h.update(chunk)
                out.write(chunk)
                if size % (64 * 1024 * 1024) < 1024 * 1024 and shutil.disk_usage(asset_dir).free < cfg.min_free_bytes:
                    raise ProcessingError("DISK_FULL", "The disk is nearly full; free some space and try again.")
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            raise ProcessingError("DISK_FULL", "The disk is full; free some space and try again.") from exc
        raise
    except ProcessingError:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, h.hexdigest(), size


@router.post("")
async def upload_assets(request: Request, files: list[UploadFile]) -> dict[str, Any]:
    cfg, db, coord = cfg_of(request), db_of(request), coord_of(request)
    if len(files) > cfg.max_files:
        raise ApiError(413, "TOO_MANY_FILES", f"Add at most {cfg.max_files} files at a time.")
    out: list[dict[str, Any]] = []
    for upload in files:
        asset_id = new_id("a_")
        asset_dir = cfg.assets_dir / asset_id
        asset_dir.mkdir(parents=True, exist_ok=True)
        filename = clean_name(upload.filename)
        row: dict[str, Any] = {
            "id": asset_id, "created_at": now(), "filename": filename, "status": "failed", "interpretation": {}, "regions": [],
            "original_name": None, "format": None, "size_bytes": 0, "sha256": None, "inspection": None, "error": None,
        }
        try:
            tmp, digest, size = await _store_upload(request, upload, asset_dir)
            row.update(size_bytes=size, sha256=digest)
            if size == 0:
                raise ProcessingError("EMPTY_FILE", "This file is empty.")
            fmt = await run_in_threadpool(detect_format, tmp)
            final = asset_dir / f"original{_EXT[fmt]}"
            tmp.replace(final)
            final.chmod(stat.S_IREAD)  # originals are immutable
            row.update(format=fmt, original_name=final.name)
            inspection = await run_in_threadpool(inspect_file, final, cfg.max_pixels)
            intake = evaluate_intake(inspection, {})
            row.update(inspection=inspection, status="inspecting")
            if intake["status"] == "unsupported":
                row.update(status="failed", error={"code": intake.get("code"), "message": intake["message"]})
        except ProcessingError as exc:
            row.update(status="failed", error={"code": exc.code, "message": exc.message})
        except Exception as exc:
            row.update(status="failed", error={"code": "UPLOAD_FAILED", "message": "This file could not be added.", "detail": str(exc)})
        finally:
            await upload.close()
        db.insert("assets", row)
        if row["status"] == "inspecting":
            coord.enqueue_prepare(asset_id)
        out.append(serialize_asset(db, coord, cfg, db.one("SELECT * FROM assets WHERE id=?", (asset_id,))))  # type: ignore[arg-type]
    return {"assets": out}


@router.get("")
async def list_assets(request: Request) -> dict[str, Any]:
    db, coord, cfg = db_of(request), coord_of(request), cfg_of(request)
    rows = db.all("SELECT * FROM assets ORDER BY created_at")
    return {"assets": [serialize_asset(db, coord, cfg, a) for a in rows]}


@router.get("/{asset_id}")
async def get_asset_detail(request: Request, asset_id: str) -> dict[str, Any]:
    return serialize_asset(db_of(request), coord_of(request), cfg_of(request), get_asset(request, asset_id))


@router.patch("/{asset_id}/interpretation")
async def patch_interpretation(request: Request, asset_id: str, body: InterpretationIn) -> dict[str, Any]:
    db, coord, cfg = db_of(request), coord_of(request), cfg_of(request)
    a = get_asset(request, asset_id)
    if a["status"] == "failed" or not a["inspection"]:
        raise ApiError(409, "ASSET_FAILED", "This file could not be read, so there is nothing to confirm.")
    interp = dict(a["interpretation"] or {})
    changes = body.model_dump(exclude_none=True)
    geometry_changed = any(k in changes and changes[k] != interp.get(k) for k in ("hdu", "layout"))
    state_changed = "state" in changes and changes["state"] != interp.get("state")
    interp.update(changes)
    intake = evaluate_intake(a["inspection"], interp)
    values: dict[str, Any] = {"interpretation": interp, "status": "inspecting"}
    if geometry_changed:
        values.update(regions=[], background=None, prepared=None)
    elif state_changed:
        values.update(background=None)
    if intake["status"] == "unsupported":
        values.update(status="failed", error={"code": intake.get("code"), "message": intake["message"]})
    db.update("assets", asset_id, values)
    if intake["status"] != "unsupported":
        coord.enqueue_prepare(asset_id)
    return serialize_asset(db, coord, cfg, get_asset(request, asset_id))


@router.put("/{asset_id}/regions")
async def put_regions(request: Request, asset_id: str, body: RegionsIn) -> dict[str, Any]:
    a = get_asset(request, asset_id)
    prepared = a.get("prepared") or {}
    if not prepared.get("width"):
        raise ApiError(409, "NOT_READY", "The image is still being prepared.")
    try:
        regions = validate_regions([r.model_dump() for r in body.regions], prepared["width"], prepared["height"])
    except ProcessingError as exc:
        raise ApiError(422, exc.code, exc.message) from exc
    db_of(request).update("assets", asset_id, {"regions": regions})
    return serialize_asset(db_of(request), coord_of(request), cfg_of(request), get_asset(request, asset_id))


@router.delete("/{asset_id}")
async def delete_asset(request: Request, asset_id: str) -> dict[str, Any]:
    db, cfg = db_of(request), cfg_of(request)
    get_asset(request, asset_id)
    if db.one("SELECT 1 AS x FROM job_items WHERE asset_id=? AND state='running'", (asset_id,)):
        raise ApiError(409, "ASSET_BUSY", "This image is being processed. Cancel the job first.")
    runs = db.all("SELECT id FROM runs WHERE asset_id=?", (asset_id,))
    for r in runs:
        shutil.rmtree(cfg.runs_dir / r["id"], ignore_errors=True)
    db.execute("DELETE FROM runs WHERE asset_id=?", (asset_id,))
    db.execute("DELETE FROM job_items WHERE asset_id=?", (asset_id,))
    asset_dir = cfg.assets_dir / asset_id
    for f in asset_dir.glob("original*"):
        f.chmod(stat.S_IWRITE | stat.S_IREAD)
    shutil.rmtree(asset_dir, ignore_errors=True)
    db.execute("DELETE FROM assets WHERE id=?", (asset_id,))
    return {"deleted": asset_id, "note": "Only app-owned copies were removed; your original files elsewhere are untouched."}


# ------------------------------------------------------------------------------------------ images
@router.get("/{asset_id}/thumb")
async def thumb(request: Request, asset_id: str):
    p = cfg_of(request).assets_dir / asset_id / "thumb.jpg"
    if not p.exists():
        raise ApiError(404, "NOT_FOUND", "No thumbnail yet.")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{asset_id}/files/{name}")
async def asset_file(request: Request, asset_id: str, name: str):
    if not _SAFE_FILE.match(name):
        raise ApiError(404, "NOT_FOUND", "Unknown file.")
    p = cfg_of(request).assets_dir / asset_id / name
    if not p.exists():
        raise ApiError(404, "NOT_FOUND", "Unknown file.")
    return FileResponse(p, media_type="image/png" if name.endswith(".png") else "image/jpeg")


@router.get("/{asset_id}/preview")
async def preview(request: Request, asset_id: str, x: int | None = None, y: int | None = None, w: int | None = None, h: int | None = None, max_edge: int = 2048):
    a = get_asset(request, asset_id)
    if not (a.get("prepared") or {}).get("label"):
        raise ApiError(409, "NOT_READY", "The preview is not ready yet.")
    roi = (x, y, w, h) if None not in (x, y, w, h) else None
    try:
        data, headers, media = await run_in_threadpool(
            previews.render, cfg_of(request).assets_dir / asset_id / "baseline.npy", roi, max(256, min(max_edge, 2048))
        )
    except ProcessingError as exc:
        raise ApiError(404, exc.code, exc.message) from exc
    return Response(data, media_type=media, headers=headers)


# ------------------------------------------------------------------------------------------ analysis
def _analysis_payload(cfg, a: dict[str, Any]) -> dict[str, Any]:
    d = cfg.assets_dir / a["id"]
    return {
        "asset_dir": str(d),
        "asset": {
            "id": a["id"], "filename": a["filename"], "path": str(d / a["original_name"]), "sha256": a["sha256"],
            "inspection": a["inspection"], "interpretation": a["interpretation"] or {}, "regions": a["regions"] or [],
            "background": a["background"], "prepared": a["prepared"],
        },
    }


def _require_ready(a: dict[str, Any]) -> None:
    if a["status"] != "ready":
        raise ApiError(409, "NOT_READY", "Confirm how this image was saved before using this feature.")


@router.get("/{asset_id}/background/suggest")
async def suggest_background(request: Request, asset_id: str) -> dict[str, Any]:
    a = get_asset(request, asset_id)
    _require_ready(a)
    return await run_worker_task(request, "analysis", {**_analysis_payload(cfg_of(request), a), "analysis": "suggest_background"})


@router.post("/{asset_id}/background/preview")
async def preview_background(request: Request, asset_id: str, body: BackgroundIn) -> dict[str, Any]:
    a = get_asset(request, asset_id)
    _require_ready(a)
    res = await run_worker_task(
        request, "analysis",
        {**_analysis_payload(cfg_of(request), a), "analysis": "background_preview", "method": body.method, "samples": [s.model_dump() for s in body.samples], "strength": body.strength},
    )
    if res.get("preview_file"):
        res["preview_url"] = f"/api/v1/assets/{asset_id}/files/{res['preview_file']}"
    return res


@router.put("/{asset_id}/background")
async def confirm_background(request: Request, asset_id: str, body: BackgroundIn) -> dict[str, Any]:
    """Persist the model choice and confirmation per asset. Re-validated server-side before it is accepted."""
    db = db_of(request)
    a = get_asset(request, asset_id)
    _require_ready(a)
    if not body.confirmed:
        db.update("assets", asset_id, {"background": None})
        return serialize_asset(db, coord_of(request), cfg_of(request), get_asset(request, asset_id))
    res = await run_worker_task(
        request, "analysis",
        {**_analysis_payload(cfg_of(request), a), "analysis": "background_preview", "method": body.method, "samples": [s.model_dump() for s in body.samples], "strength": body.strength},
    )
    model = res["model"]
    if not model["ok"]:
        raise ApiError(422, "BACKGROUND_INVALID", "The sky regions do not support this correction.", model["issues"])
    db.update("assets", asset_id, {"background": {
        "method": body.method, "samples": [s.model_dump() for s in body.samples], "confirmed": True, "confirmed_at": now(),
        "samples_hash": res["samples_hash"], "model_hash": model["model_hash"], "warnings": [i for i in model["issues"] if i["level"] == "warning"],
        "residuals": model.get("residuals"),
    }})
    return serialize_asset(db, coord_of(request), cfg_of(request), get_asset(request, asset_id))


@router.get("/{asset_id}/star-mask")
async def star_mask(request: Request, asset_id: str) -> dict[str, Any]:
    a = get_asset(request, asset_id)
    _require_ready(a)
    res = await run_worker_task(request, "analysis", {**_analysis_payload(cfg_of(request), a), "analysis": "star_mask"})
    res["overlay_url"] = f"/api/v1/assets/{asset_id}/files/{res['file']}" if res.get("file") else None
    return res

