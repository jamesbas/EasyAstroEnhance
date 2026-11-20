from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from astropy.io import fits
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response

from ..models.api import BatchExportIn, ConfirmIn, EditExportIn, FramingIn
from ..processing.edit_export import Framing, render_edited
from ..processing.export import _clean_header
from ..processing.imagedata import ProcessingError
from ..processing.recipe import PIPELINE_VERSION
from ..services import previews
from ..services.exports import ALLOWED_KINDS, DOWNLOADABLE_KINDS, cancel_batch, ensure_export, start_batch
from .common import ApiError, cfg_of, coord_of, db_of, serialize_run

router = APIRouter(tags=["runs"])
MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".tif": "image/tiff", ".fits": "application/fits", ".json": "application/json", ".txt": "text/plain"}


def _run(request: Request, run_id: str) -> dict[str, Any]:
    r = db_of(request).one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not r:
        raise ApiError(404, "RUN_NOT_FOUND", "That result no longer exists.")
    return r


@router.get("/runs")
def list_runs(request: Request, asset_id: str | None = None) -> dict[str, Any]:
    db = db_of(request)
    rows = db.all("SELECT * FROM runs WHERE asset_id=? ORDER BY created_at DESC", (asset_id,)) if asset_id else db.all("SELECT * FROM runs ORDER BY created_at DESC LIMIT 200")
    out = []
    for r in rows:
        a = db.one("SELECT filename FROM assets WHERE id=?", (r["asset_id"],))
        out.append({**serialize_run(r), "filename": a["filename"] if a else None})
    return {"runs": out}


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    r = _run(request, run_id)
    report_path = cfg_of(request).runs_dir / run_id / "processing.json"
    applied = None
    if report_path.exists():
        full = json.loads(report_path.read_text(encoding="utf-8"))
        applied = {k: full["applied"].get(k) for k in ("summary", "clipping", "execution", "protected_regions", "baseline_frame", "enhanced_frame", "linear_preparation", "decisions", "noise_estimate", "auto_preset")}
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
    if kind not in DOWNLOADABLE_KINDS:
        raise ApiError(404, "UNKNOWN_EXPORT", "That export type does not exist.")
    entry = next((e for e in run["exports"] or [] if e["kind"] == kind), None)
    if not entry:
        raise ApiError(404, "EXPORT_NOT_AVAILABLE", "That export is not available for this result.")
    try:
        path = await run_in_threadpool(ensure_export, cfg_of(request), db_of(request), run, entry)
    except OSError as exc:
        raise ApiError(404, "EXPORT_MISSING", "The file is no longer on disk.") from exc
    if not path.exists():
        raise ApiError(404, "EXPORT_MISSING", "The file is no longer on disk.")
    name = f"{(run['summary'] or {}).get('run_name', run_id)}-{entry['filename']}"
    return FileResponse(path, media_type=MEDIA.get(path.suffix.lower(), "application/octet-stream"), filename=name)


def _label_text(text: str) -> str:
    return "".join(c if c.isprintable() else " " for c in text).strip()


def _fits_target(path: Path, report_path: Path, default_hdu: int) -> str | None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    interpretation = report.get("per_file_resolution", {}).get("interpretation", {})
    hdu_index = interpretation.get("hdu")
    if hdu_index is None:
        hdu_index = default_hdu
    with fits.open(path, lazy_load_hdus=True) as hdus:
        for i in dict.fromkeys((hdu_index, 0)):
            value = hdus[i].header.get("OBJECT")
            if isinstance(value, str):
                name = _label_text(value)[:80]
                if name.casefold() not in ("", "unknown", "undefined", "none", "n/a"):
                    return name
    return None


@router.get("/runs/{run_id}/edit-export/target")
async def edit_export_target(request: Request, run_id: str):
    run = _run(request, run_id)
    asset = db_of(request).one("SELECT * FROM assets WHERE id=?", (run["asset_id"],))
    if not asset:
        raise ApiError(404, "ASSET_NOT_FOUND", "This result's original is no longer available.")
    if asset["format"] != "fits":
        return {"target": None}
    cfg = cfg_of(request)
    path = cfg.assets_dir / asset["id"] / asset["original_name"]
    report_path = cfg.runs_dir / run_id / "processing.json"
    default_hdu = next((c["index"] for c in asset["inspection"]["candidates"] if c["supported"]), 0)
    try:
        target = await run_in_threadpool(_fits_target, path, report_path, default_hdu)
    except (OSError, ValueError, IndexError) as exc:
        raise ApiError(422, "TARGET_UNAVAILABLE", "Couldn't read the FITS target. You can enter the name manually.") from exc
    return {"target": target}


def _annotation_context(request: Request, run_id: str) -> tuple[dict[str, Any] | None, tuple, str | None, str | None]:
    """(sky solution, deep-sky objects, objects catalog SHA-256, reason when unavailable) for a run's image."""
    from ..processing.catalogs import objects as dso
    from ..processing.catalogs import registry as refreg
    from ..services.worker import load_sky_solution

    cfg = cfg_of(request)
    run = _run(request, run_id)
    asset = db_of(request).one("SELECT * FROM assets WHERE id=?", (run["asset_id"],))
    if not asset:
        return None, (), None, "This result's original is no longer available."
    sol = load_sky_solution(cfg, asset)
    if not sol or sol.get("status") not in ("verified", "solved"):
        reason = (sol or {}).get("reason") or "Find where this image points on the sky first (All controls → Advanced → Sky position)."
        return None, (), None, reason
    if not refreg.group_ready(cfg.reference_data_dir, "objects"):
        return sol, (), None, "Download the deep-sky object catalog in Settings → Reference data to label objects."
    paths = tuple(str(refreg.installed(cfg.reference_data_dir, k)) for k in refreg.GROUPS["objects"])
    digest = ",".join(refreg.DATA[k].sha256 for k in refreg.GROUPS["objects"])
    return sol, dso.objects_from(paths), digest, None


@router.post("/runs/{run_id}/edit-export/objects")
async def edit_export_objects(request: Request, run_id: str, body: FramingIn) -> dict[str, Any]:
    """Catalogued objects inside the framed area, for the annotation checklist."""
    from ..processing.annotate import frame_geometry, objects_in_frame

    sol, objs, _, reason = _annotation_context(request, run_id)
    if sol is None:
        return {"available": False, "compass_available": False, "reason": reason, "objects": []}
    geo = frame_geometry(sol["height"], sol["width"], Framing(body.rotation, body.zoom, body.pan_x, body.pan_y))
    found = await run_in_threadpool(objects_in_frame, sol, objs, geo, body.max_mag) if objs else []
    return {
        "available": bool(objs), "compass_available": True, "reason": reason,
        "sky_solution": {k: sol.get(k) for k in ("status", "source", "center", "scale_arcsec")},
        "objects": [{k: o[k] for k in ("name", "type", "common", "mag", "major_arcmin")} for o in found],
    }


@router.post("/runs/{run_id}/edit-export")
async def edit_export(request: Request, run_id: str, body: EditExportIn, preview: bool = False):
    from ..processing.annotate import Annotations, draw, frame_geometry

    _run(request, run_id)
    path = cfg_of(request).runs_dir / run_id / "display.npy"
    frame = Framing(body.rotation, body.zoom, body.pan_x, body.pan_y)
    target, label = _label_text(body.target), _label_text(body.label)
    lines = [text for text in (target, label) if text]
    jpeg = body.format == "jpeg"
    ann = Annotations(objects=body.annotations.objects, hidden=tuple(body.annotations.hidden), max_mag=body.annotations.max_mag,
                      compass=body.annotations.compass, scale_bar=body.annotations.scale_bar)
    overlay = None
    objects_sha = None
    if ann.any:
        sol, objs, objects_sha, reason = _annotation_context(request, run_id)
        if sol is None or (ann.objects and not objs):
            raise ApiError(422, "ANNOTATIONS_UNAVAILABLE", reason or "Annotations are not available for this image.")

        def overlay(image, max_edge):
            return draw(image, sol, objs, frame_geometry(sol["height"], sol["width"], frame, max_edge), ann)

    def metadata(drawn):
        if preview:
            return None
        meta = {**body.model_dump(), "target": target, "label": label, "run_id": run_id, "export_engine": PIPELINE_VERSION}
        if drawn is not None:
            meta["annotations_drawn"] = drawn
            meta["object_catalog_sha256"] = objects_sha
            meta["sky_solution"] = "verified header WCS" if sol.get("status") == "verified" else "EasyAstroEnhance hinted solve"
        return json.dumps(meta, ensure_ascii=True).encode("ascii")

    def render() -> bytes:
        return render_edited(previews.open_display(path), frame, lines, jpeg=jpeg, metadata=metadata, preview=preview, overlay=overlay)

    try:
        data = await run_in_threadpool(render)
    except ProcessingError as exc:
        raise ApiError(404 if exc.code == "NOT_FOUND" else 422, exc.code, exc.message) from exc
    ext = "jpg" if jpeg else "png"
    headers = {"Cache-Control": "no-store"}
    if not preview:
        headers["Content-Disposition"] = f'attachment; filename="{run_id}-edited.{ext}"'
    return Response(data, media_type="image/jpeg" if preview or jpeg else "image/png", headers=headers)


# ------------------------------------------------------------------------------------------ batch ZIP
@router.post("/exports/batch", status_code=202)
def batch_export(request: Request, body: BatchExportIn) -> dict[str, Any]:
    db, cfg = db_of(request), cfg_of(request)
    ids = [r for r in dict.fromkeys(body.run_ids) if db.one("SELECT 1 AS x FROM runs WHERE id=?", (r,))]
    if not ids:
        raise ApiError(404, "RUN_NOT_FOUND", "None of the selected results exist.")
    export_id = start_batch(cfg, db, ids, list(body.include))
    return {"id": export_id, "state": "building"}


@router.get("/exports/{export_id}")
def export_status(request: Request, export_id: str) -> dict[str, Any]:
    e = db_of(request).one("SELECT * FROM exports WHERE id=?", (export_id,))
    if not e:
        raise ApiError(404, "EXPORT_NOT_FOUND", "That export does not exist.")
    return {"id": e["id"], "state": e["state"], "detail": e["detail"], "download_url": f"/api/v1/exports/{export_id}/download" if e["state"] == "ready" else None}


@router.post("/exports/{export_id}/cancel")
def export_cancel(request: Request, export_id: str) -> dict[str, Any]:
    if not db_of(request).one("SELECT id FROM exports WHERE id=?", (export_id,)):
        raise ApiError(404, "EXPORT_NOT_FOUND", "That export does not exist.")
    return {"id": export_id, "cancelling": cancel_batch(db_of(request), export_id)}


@router.get("/exports/{export_id}/download")
def export_download(request: Request, export_id: str):
    e = db_of(request).one("SELECT * FROM exports WHERE id=?", (export_id,))
    if not e or e["state"] != "ready" or not e["path"] or not Path(e["path"]).exists():
        raise ApiError(404, "EXPORT_NOT_READY", "That ZIP is not ready.")
    return FileResponse(e["path"], media_type="application/zip", filename="EasyAstroEnhance-results.zip")


# ------------------------------------------------------------------------------------------ history
@router.get("/history/summary")
def history_summary(request: Request) -> dict[str, Any]:
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
def clear_history(request: Request, body: ConfirmIn) -> dict[str, Any]:
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
    coord_of(request).live_previews.clear()
    return {"cleared": True}

