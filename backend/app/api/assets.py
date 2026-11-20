from __future__ import annotations

import asyncio
import errno
import hashlib
import io
import re
import shutil
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from ..db import new_id, now
from ..models.api import BackgroundIn, InterpretationIn, LivePreviewIn, PresetPreviewsIn, RegionsIn
from ..processing.imagedata import ProcessingError
from ..processing.catalog_color import MAX_BYTES, parse_catalog
from ..processing.color import luminance
from ..processing.color_mix import MIX_ROLES
from ..processing.linear_prep import clipped_stats, sky_stats
from ..processing.masks import validate_regions
from ..processing.object_color import hubble_style, selective_color
from ..processing.readers import detect_format, evaluate_intake, inspect_file
from ..processing.recipe import ObjectColorRecipe
from ..processing.star_protection import detect_stars
from ..services import previews
from .common import (
    ApiError, asset_hubble_input, cfg_of, coord_of, db_of, get_asset, run_worker_task, serialize_asset,
)

router = APIRouter(prefix="/assets", tags=["assets"])
_EXT = {"jpeg": ".jpg", "tiff": ".tif", "fits": ".fits"}
_SAFE_FILE = re.compile(r"^(bgprev-[0-9a-f]+-\d+\.jpg|starmask-[0-9a-f]+\.png|hdu-\d+\.jpg|thumb\.jpg|presetprev-[0-9a-f]{20}\.jpg)$")


def clean_name(name: str | None) -> str:
    base = Path((name or "image").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", base).strip(". ") or "image"
    return base[:120]


async def _store_upload(request: Request, upload: UploadFile, asset_dir: Path) -> tuple[Path, str, int]:
    """Stream an upload to disk, hashing as we go; enforce byte limit and free-space floor. The copy runs on a worker
    thread so large files never block the event loop."""
    cfg = cfg_of(request)
    tmp = asset_dir / "upload.part"
    if shutil.disk_usage(asset_dir).free < cfg.min_free_bytes:
        raise ProcessingError("DISK_FULL", "The disk is nearly full; free some space and try again.")

    def copy() -> tuple[str, int]:
        h = hashlib.sha256()
        size = 0
        upload.file.seek(0)
        with open(tmp, "wb") as out:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > cfg.max_file_bytes:
                    raise ProcessingError("FILE_TOO_LARGE", f"This file is larger than the {cfg.max_file_bytes // (1024 * 1024)} MiB limit.")
                h.update(chunk)
                out.write(chunk)
                if size % (64 * 1024 * 1024) < 1024 * 1024 and shutil.disk_usage(asset_dir).free < cfg.min_free_bytes:
                    raise ProcessingError("DISK_FULL", "The disk is nearly full; free some space and try again.")
        return h.hexdigest(), size

    try:
        digest, size = await run_in_threadpool(copy)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            raise ProcessingError("DISK_FULL", "The disk is full; free some space and try again.") from exc
        raise
    except ProcessingError:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, digest, size


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
def list_assets(request: Request) -> dict[str, Any]:
    db, coord, cfg = db_of(request), coord_of(request), cfg_of(request)
    rows = db.all("SELECT * FROM assets ORDER BY created_at")
    return {"assets": [serialize_asset(db, coord, cfg, a) for a in rows]}


@router.post("/color-catalog")
async def import_color_catalog(request: Request, file: UploadFile) -> dict[str, Any]:
    cfg = cfg_of(request)
    try:
        contents = await file.read(MAX_BYTES + 1)
        values = await run_in_threadpool(parse_catalog, contents)
    except ProcessingError as exc:
        raise ApiError(422, exc.code, exc.message) from exc
    finally:
        await file.close()
    digest = hashlib.sha256(contents).hexdigest()
    folder = cfg.color_catalog_dir
    if shutil.disk_usage(folder).free < cfg.min_free_bytes + len(contents):
        raise ApiError(507, "DISK_FULL", "There is not enough space to store the reference catalog.")
    with NamedTemporaryFile(dir=folder, suffix=".part", delete=False) as f:
        tmp = Path(f.name)
    try:
        tmp.write_bytes(contents)
        tmp.replace(folder / f"{digest}.csv")
    finally:
        tmp.unlink(missing_ok=True)
    return {"sha256": digest, "name": clean_name(file.filename), "stars": len(values)}


class ColorMixIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["RGB", "LRGB", "HOO", "SHO", "DUAL-SHO", "HA-RGB"]
    asset_ids: list[str] = Field(min_length=2, max_length=4)
    gains: list[Annotated[float, Field(ge=0.01, le=100)]] = Field(min_length=2, max_length=4)
    strength: float = Field(0.5, ge=0, le=1)
    prealigned: bool = False


@router.post("/color-mix", status_code=201)
async def create_color_mix(request: Request, body: ColorMixIn) -> dict[str, Any]:
    cfg, db, coord = cfg_of(request), db_of(request), coord_of(request)
    n = len(MIX_ROLES[body.mode])
    if len(set(body.asset_ids)) != n or len(body.asset_ids) != n or len(body.gains) != n:
        raise ApiError(422, "MIX_ROLES", "Select a different linear master for each channel role.")
    sources = []
    for asset_id in body.asset_ids:
        source = get_asset(request, asset_id)
        ready = source.get("prepared") or {}
        if source["status"] != "ready" or ready.get("state") != "linear" or source["format"] != "fits":
            raise ApiError(422, "MIX_INPUT", "All masters must be ready FITS files confirmed as linear.")
        sources.append({**source, "path": str(cfg.assets_dir / asset_id / source["original_name"])})
    asset_id = new_id("a_")
    asset_dir = cfg.assets_dir / asset_id
    asset_dir.mkdir()
    out = asset_dir / "original.fits"
    try:
        result = await run_worker_task(request, "color_mix", {
            "sources": sources, "mode": body.mode, "gains": body.gains, "strength": body.strength,
            "prealigned": body.prealigned, "out_path": str(out),
        })
        inspection = await run_in_threadpool(inspect_file, out, cfg.max_pixels)
        out.chmod(stat.S_IREAD)
        db.insert("assets", {
            "id": asset_id, "created_at": now(), "filename": clean_name(f"{Path(sources[0]['filename']).stem} - {body.mode}.fits"),
            "status": "inspecting", "interpretation": {"state": "linear"}, "regions": [],
            "original_name": out.name, "format": "fits", "size_bytes": result["size"], "sha256": result["sha256"],
            "inspection": inspection,
        })
    finally:
        if not db.one("SELECT id FROM assets WHERE id=?", (asset_id,)):
            if out.exists():
                out.chmod(stat.S_IWRITE)
                out.unlink()
            (asset_dir / "original.partial").unlink(missing_ok=True)
            asset_dir.rmdir()
    coord.enqueue_prepare(asset_id)
    return serialize_asset(db, coord, cfg, get_asset(request, asset_id))


def _object_preview(path: Path, regions: list[dict[str, Any]], recipe: ObjectColorRecipe, mask_only: bool,
                    hubble_strength: float = 0.0) -> bytes:
    arr = previews.open_display(path)
    if arr.ndim != 3:
        raise ProcessingError("MONO_COLOR", "Object Color needs a color image.")
    stride = max(1, (max(arr.shape[:2]) + 383) // 384)
    small = arr[::stride, ::stride].astype(np.float32) / 65535
    valid = (small != 0).any(axis=2)
    for rect in regions:
        left, top = (rect["x"] + stride - 1) // stride, (rect["y"] + stride - 1) // stride
        right = (rect["x"] + rect["w"] + stride - 1) // stride
        bottom = (rect["y"] + rect["h"] + stride - 1) // stride
        valid[top:bottom, left:right] = False
    if not valid.any():
        raise ProcessingError("NO_VALID_PIXELS", "No unprotected pixels to preview.")
    stars = detect_stars(small, valid, 1e-6).soft
    if hubble_strength:
        if stars is None:
            raise ProcessingError("NO_PREVIEW_STAR_MASK", "Not enough stars could be detected in the quick preview. Try the full-resolution action.")
        stats = sky_stats(small, valid & (stars < 0.5))
        result, mask = hubble_style(np, small, small, stars, valid, tuple(stats.level), max(stats.sigma), hubble_strength)
    else:
        sky, sigma = clipped_stats(luminance(np, small)[valid])
        result, mask = selective_color(np, small, stars if stars is not None else 0.0, valid, sky, sigma, recipe)
    buf = io.BytesIO()
    Image.fromarray(np.rint(np.clip(mask if mask_only else result, 0, 1) * 255).astype(np.uint8)).save(buf, "PNG")
    return buf.getvalue()


@router.post("/{asset_id}/object-color-preview")
async def preview_object_color(request: Request, asset_id: str, body: ObjectColorRecipe,
                               mask: bool = False, protect_regions: bool = True,
                               hubble_strength: Annotated[float, Query(ge=0, le=1)] = 0.0) -> Response:
    asset = get_asset(request, asset_id)
    if hubble_strength and asset_hubble_input(asset) != "dualband":
        raise ApiError(422, "PALETTE_INPUT", "Hubble-style needs a confirmed linear H-alpha/OIII color FITS.")
    try:
        data = await run_in_threadpool(_object_preview, cfg_of(request).assets_dir / asset_id / "baseline.npy",
                                       (asset.get("regions") or []) if protect_regions else [], body, mask, hubble_strength)
    except ProcessingError as exc:
        raise ApiError(422, exc.code, exc.message) from exc
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/{asset_id}")
def get_asset_detail(request: Request, asset_id: str) -> dict[str, Any]:
    return serialize_asset(db_of(request), coord_of(request), cfg_of(request), get_asset(request, asset_id))


@router.patch("/{asset_id}/interpretation")
def patch_interpretation(request: Request, asset_id: str, body: InterpretationIn) -> dict[str, Any]:
    db, coord, cfg = db_of(request), coord_of(request), cfg_of(request)
    a = get_asset(request, asset_id)
    if a["status"] == "failed" or not a["inspection"]:
        raise ApiError(409, "ASSET_FAILED", "This file could not be read, so there is nothing to confirm.")
    interp = dict(a["interpretation"] or {})
    changes = body.model_dump(exclude_none=True)
    if "dualband_confirmed" in changes:
        detected = asset_hubble_input({**a, "interpretation": {}})
        if len(changes) != 1 or detected != "unknown":
            raise ApiError(422, "PALETTE_INPUT", "Only confirm the filter for a ready linear color FITS with an unrecognized filter.")
        if changes["dualband_confirmed"]:
            interp["dualband_confirmed"] = True
        else:
            interp.pop("dualband_confirmed", None)
        db.update("assets", asset_id, {"interpretation": interp})
        return serialize_asset(db, coord, cfg, get_asset(request, asset_id))
    geometry_changed = any(k in changes and changes[k] != interp.get(k) for k in ("hdu", "layout"))
    state_changed = "state" in changes and changes["state"] != interp.get("state")
    if geometry_changed or state_changed:
        interp.pop("dualband_confirmed", None)
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
def put_regions(request: Request, asset_id: str, body: RegionsIn) -> dict[str, Any]:
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
def delete_asset(request: Request, asset_id: str) -> dict[str, Any]:
    db, cfg = db_of(request), cfg_of(request)
    get_asset(request, asset_id)
    if db.one("SELECT 1 AS x FROM job_items WHERE asset_id=? AND state='running'", (asset_id,)):
        raise ApiError(409, "ASSET_BUSY", "This image is being processed. Cancel the job first.")
    coord_of(request).cancel_live(asset_id)
    coord_of(request).live_previews.pop(asset_id, None)
    runs = db.all("SELECT id FROM runs WHERE asset_id=?", (asset_id,))
    for r in runs:
        shutil.rmtree(cfg.runs_dir / r["id"], ignore_errors=True)
    db.execute("DELETE FROM runs WHERE asset_id=?", (asset_id,))
    db.execute("DELETE FROM job_items WHERE asset_id=?", (asset_id,))
    asset_dir = cfg.assets_dir / asset_id
    for f in asset_dir.glob("original*"):
        f.chmod(stat.S_IWRITE | stat.S_IREAD)
    shutil.rmtree(asset_dir, ignore_errors=True)
    shutil.rmtree(cfg.tmp_dir / "live" / asset_id, ignore_errors=True)
    db.execute("DELETE FROM assets WHERE id=?", (asset_id,))
    return {"deleted": asset_id, "note": "Only app-owned copies were removed; your original files elsewhere are untouched."}


# ------------------------------------------------------------------------------------------ images
@router.get("/{asset_id}/thumb")
def thumb(request: Request, asset_id: str):
    p = cfg_of(request).assets_dir / asset_id / "thumb.jpg"
    if not p.exists():
        raise ApiError(404, "NOT_FOUND", "No thumbnail yet.")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{asset_id}/files/{name}")
def asset_file(request: Request, asset_id: str, name: str):
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


# ------------------------------------------------------------------------------------------ live preview
_LIVE_ID = re.compile(r"^lp_[0-9a-zA-Z_-]+$")


def _live_view(asset_id: str, st: dict[str, Any] | None) -> dict[str, Any]:
    if not st:
        return {"state": "none"}
    res = st.get("result") or {}
    url = f"/api/v1/assets/{asset_id}/live-preview/{st['id']}" if st["state"] == "ready" else None
    return {
        "id": st["id"], "state": st["state"], "stage": st.get("stage"), "error": st.get("error"), "recipe": st["recipe"],
        "summary": res.get("summary"), "operations": res.get("operations", []), "needs_review": res.get("needs_review"),
        "seconds": res.get("seconds"), "reused": res.get("reused"), "auto_preset": res.get("auto_preset"),
        "preview_url": url, "has_fixed_mapping": bool(res.get("has_fixed")),
    }


@router.post("/{asset_id}/live-preview", status_code=202)
def start_live_preview(request: Request, asset_id: str, body: LivePreviewIn) -> dict[str, Any]:
    """Preview the enhancement for the current settings at full resolution without saving a result (latest request wins)."""
    from .common import settings_snapshot

    a = get_asset(request, asset_id)
    _require_ready(a)
    if not a.get("original_name"):
        raise ApiError(409, "NOT_READY", "This image is not ready yet.")
    st = coord_of(request).request_live(a, body.recipe.model_dump(), settings_snapshot(db_of(request), cfg_of(request)))
    return _live_view(asset_id, st)


@router.get("/{asset_id}/live-preview")
def live_preview_status(request: Request, asset_id: str) -> dict[str, Any]:
    get_asset(request, asset_id)
    return _live_view(asset_id, coord_of(request).live_previews.get(asset_id))


@router.delete("/{asset_id}/live-preview")
def cancel_live_preview(request: Request, asset_id: str) -> dict[str, Any]:
    coord_of(request).cancel_live(asset_id)
    return {"cancelled": True}


@router.get("/{asset_id}/live-preview/{live_id}")
async def live_preview_image(request: Request, asset_id: str, live_id: str, variant: str = "enhanced", x: int | None = None,
                             y: int | None = None, w: int | None = None, h: int | None = None, max_edge: int = 2048):
    get_asset(request, asset_id)
    if not _LIVE_ID.match(live_id) or variant not in ("enhanced", "fixed"):
        raise ApiError(404, "NOT_FOUND", "Unknown preview.")
    path = cfg_of(request).tmp_dir / "live" / asset_id / (f"{live_id}.npy" if variant == "enhanced" else f"{live_id}-fixed.npy")
    roi = (x, y, w, h) if None not in (x, y, w, h) else None
    try:
        data, headers, media = await run_in_threadpool(previews.render, path, roi, max(256, min(max_edge, 2048)))
    except ProcessingError as exc:
        raise ApiError(404, exc.code, "This preview is no longer available; it was replaced by a newer one.") from exc
    return Response(data, media_type=media, headers=headers)
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


@router.post("/{asset_id}/preset-previews")
async def preset_previews(request: Request, asset_id: str, body: PresetPreviewsIn) -> dict[str, Any]:
    """Quick-look thumbnails of this image with each given preset recipe (rendered on a ~1 MP block-averaged copy)."""
    a = get_asset(request, asset_id)
    _require_ready(a)
    payload = {**_analysis_payload(cfg_of(request), a), "items": [{"id": i.id, "recipe": i.recipe.model_dump()} for i in body.items]}
    res = await run_worker_task(request, "preset_previews", payload, timeout=600)
    return {
        "items": [{**i, "url": f"/api/v1/assets/{asset_id}/files/{i['file']}"} for i in res["items"]],
        "scale_factor": res["factor"],
        "note": "Quick look at reduced size; the full-resolution result can differ slightly.",
    }


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

