from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from astropy.io import fits
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response

from ..models.api import BatchExportIn, ConfirmIn
from ..processing.export import _clean_header
from ..processing.imagedata import ProcessingError
from ..services import previews
from ..services.exports import ALLOWED_KINDS, start_batch
from .common import ApiError, cfg_of, coord_of, db_of, serialize_run

router = APIRouter(tags=["runs"])
MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".tif": "image/tiff", ".fits": "application/fits", ".json": "application/json", ".txt": "text/plain"}


def _run(request: Request, run_id: str) -> dict[str, Any]:
    r = db_of(request).one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not r:
        raise ApiError(404, "RUN_NOT_FOUND", "That result no longer exists.")
    return r


@router.get("/runs")
async def list_runs(request: Request, asset_id: str | None = None) -> dict[str, Any]:
    db = db_of(request)
    rows = db.all("SELECT * FROM runs WHERE asset_id=? ORDER BY created_at DESC", (asset_id,)) if asset_id else db.all("SELECT * FROM runs ORDER BY created_at DESC LIMIT 200")
    out = []
    for r in rows:
        a = db.one("SELECT filename FROM assets WHERE id=?", (r["asset_id"],))
        out.append({**serialize_run(r), "filename": a["filename"] if a else None})
    return {"runs": out}


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> dict[str, Any]:
    r = _run(request, run_id)
    report_path = cfg_of(request).runs_dir / run_id / "processing.json"
    applied = None
    if report_path.exists():
        full = json.loads(report_path.read_text(encoding="utf-8"))
        applied = {k: full["applied"].get(k) for k in ("summary", "clipping", "execution", "protected_regions", "baseline_frame", "enhanced_frame", "linear_preparation", "decisions", "noise_estimate")}
        applied["operations"] = full["applied"]["operations"]
    has_fixed = (cfg_of(request).runs_dir / run_id / "display_fixed.npy").exists()
    return {**serialize_run(r), "applied": applied, "has_fixed_mapping": has_fixed}


@router.get("/runs/{run_id}/preview")
async def run_preview(request: Request, run_id: str, variant: str = "enhanced", x: int | None = None, y: int | None = None, w: int | None = None, h: int | None = None, max_edge: int = 2048):
    _run(request, run_id)
    name = {"enhanced": "display.npy", "fixed": "display_fixed.npy"}.get(variant)
    if not name:
        raise ApiError(400, "BAD_VARIANT", "Unknown preview variant.")
    roi = (x, y, w, h) if None not in (x, y, w, h) else None
    try:
        data, headers, media = await run_in_threadpool(previews.render, cfg_of(request).runs_dir / run_id / name, roi, max(256, min(max_edge, 2048)))
    except ProcessingError as exc:
        raise ApiError(404, exc.code, exc.message) from exc
    return Response(data, media_type=media, headers=headers)


@router.get("/runs/{run_id}/overlay/clipping")
async def clipping_overlay(request: Request, run_id: str):
    r = _run(request, run_id)
    cfg = cfg_of(request)
    try:
        data = await run_in_threadpool(previews.clipping_overlay, cfg.assets_dir / r["asset_id"] / "baseline.npy", cfg.runs_dir / run_id / "display.npy")
    except ProcessingError as exc:
        raise ApiError(404, exc.code, exc.message) from exc
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


def _full_metadata_fits(request: Request, run: dict[str, Any]) -> Path:
    """Explicit full-metadata FITS (original header kept, including location/observer keywords)."""
    cfg = cfg_of(request)
    src = next((e for e in run["exports"] if e["kind"] == "fits"), None)
    if not src:
        raise ApiError(404, "NO_FITS", "This result has no FITS export.")
    asset = db_of(request).one("SELECT * FROM assets WHERE id=?", (run["asset_id"],))
    original = cfg.assets_dir / asset["id"] / asset["original_name"]
    hdu_index = (asset["interpretation"] or {}).get("hdu") or 0
    if not (asset["interpretation"] or {}).get("hdu"):
        cands = [c for c in asset["inspection"]["candidates"] if c["supported"]]
        hdu_index = cands[0]["index"] if cands else 0
    out = cfg.tmp_dir / f"{run['id']}-full-metadata.fits"
    with fits.open(original, memmap=False) as orig, fits.open(cfg.runs_dir / run["id"] / src["filename"]) as proc:
        header, _ = _clean_header(orig[hdu_index].header, strip_sensitive=False)
        for key in ("EAEVER", "EAEKIND", "EAESHA", "EAEPRE", "EAEUNIT"):
            if key in proc[0].header:
                header[key] = (proc[0].header[key], proc[0].header.comments[key])
        header.add_history("Full original metadata retained at the user's explicit request (may include location/observer details).")
        fits.PrimaryHDU(data=proc[0].data, header=header).writeto(out, overwrite=True, checksum=True)
    return out


@router.get("/runs/{run_id}/exports/{kind}")
async def download_export(request: Request, run_id: str, kind: str):
    run = _run(request, run_id)
    if kind == "fits-full":
        path = await run_in_threadpool(_full_metadata_fits, request, run)
        return FileResponse(path, media_type=MEDIA[".fits"], filename=f"{(run['summary'] or {}).get('run_name', run_id)}-full-metadata.fits")
    if kind not in ALLOWED_KINDS:
        raise ApiError(404, "UNKNOWN_EXPORT", "That export type does not exist.")
    entry = next((e for e in run["exports"] or [] if e["kind"] == kind), None)
    if not entry:
        raise ApiError(404, "EXPORT_NOT_AVAILABLE", "That export is not available for this result.")
    path = cfg_of(request).runs_dir / run_id / entry["filename"]
    if not path.exists():
        raise ApiError(404, "EXPORT_MISSING", "The file is no longer on disk.")
    name = f"{(run['summary'] or {}).get('run_name', run_id)}-{entry['filename']}"
    return FileResponse(path, media_type=MEDIA.get(path.suffix.lower(), "application/octet-stream"), filename=name)


# ------------------------------------------------------------------------------------------ batch ZIP
@router.post("/exports/batch", status_code=202)
async def batch_export(request: Request, body: BatchExportIn) -> dict[str, Any]:
    db, cfg = db_of(request), cfg_of(request)
    ids = [r for r in dict.fromkeys(body.run_ids) if db.one("SELECT 1 AS x FROM runs WHERE id=?", (r,))]
    if not ids:
        raise ApiError(404, "RUN_NOT_FOUND", "None of the selected results exist.")
    export_id = start_batch(cfg, db, ids, list(body.include))
    return {"id": export_id, "state": "building"}


@router.get("/exports/{export_id}")
async def export_status(request: Request, export_id: str) -> dict[str, Any]:
    e = db_of(request).one("SELECT * FROM exports WHERE id=?", (export_id,))
    if not e:
        raise ApiError(404, "EXPORT_NOT_FOUND", "That export does not exist.")
    return {"id": e["id"], "state": e["state"], "detail": e["detail"], "download_url": f"/api/v1/exports/{export_id}/download" if e["state"] == "ready" else None}


@router.get("/exports/{export_id}/download")
async def export_download(request: Request, export_id: str):
    e = db_of(request).one("SELECT * FROM exports WHERE id=?", (export_id,))
    if not e or e["state"] != "ready" or not e["path"] or not Path(e["path"]).exists():
        raise ApiError(404, "EXPORT_NOT_READY", "That ZIP is not ready.")
    return FileResponse(e["path"], media_type="application/zip", filename="EasyAstroEnhance-results.zip")


# ------------------------------------------------------------------------------------------ history
@router.get("/history/summary")
async def history_summary(request: Request) -> dict[str, Any]:
    cfg, db = cfg_of(request), db_of(request)

    def size(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0

    return {
        "assets": db.one("SELECT COUNT(*) AS n FROM assets")["n"],  # type: ignore[index]
        "runs": db.one("SELECT COUNT(*) AS n FROM runs")["n"],  # type: ignore[index]
        "bytes": {"uploaded_originals_copies": size(cfg.assets_dir), "results": size(cfg.runs_dir), "zip_exports": size(cfg.exports_dir)},
        "will_remove": "App-owned copies of added images, previews, results, reports and ZIPs, plus job history. Saved presets and settings are kept. Your original files elsewhere are never touched.",
        "location": str(cfg.data_dir),
    }


@router.delete("/history")
async def clear_history(request: Request, body: ConfirmIn) -> dict[str, Any]:
    if not body.confirm:
        raise ApiError(400, "CONFIRM_REQUIRED", "Confirm to clear local history.")
    db, cfg = db_of(request), cfg_of(request)
    if db.one("SELECT 1 AS x FROM job_items WHERE state IN ('queued','running')"):
        raise ApiError(409, "JOBS_ACTIVE", "Cancel active jobs before clearing history.")
    if db.one("SELECT 1 AS x FROM stacks WHERE state IN ('queued','running')"):
        raise ApiError(409, "JOBS_ACTIVE", "Cancel the running stack before clearing history.")
    import stat

    for d in (cfg.assets_dir, cfg.runs_dir, cfg.exports_dir, cfg.tmp_dir):
        if d.exists():
            for f in d.rglob("original*"):
                try:
                    f.chmod(stat.S_IWRITE | stat.S_IREAD)
                except OSError:
                    pass
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    for table in ("job_items", "jobs", "runs", "assets", "exports", "stacks"):
        db.execute(f"DELETE FROM {table}")
    return {"cleared": True}

