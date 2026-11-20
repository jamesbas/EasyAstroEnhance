"""The single worker process: decoding, analysis and enhancement run here, never in request handlers.

Windows-safe: started with the ``spawn`` start method; CUDA/CuPy are initialized only in this process.
The worker never opens the SQLite database; it exchanges bounded messages with the coordinator.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Config
from ..processing import background as bgmod
from ..processing import export as exp
from ..processing.backends import BackendUnavailable, get_backend, probe_cuda
from ..processing.denoise import estimate_noise
from ..processing.imagedata import Cancelled, ImageData, ProcessingError
from ..processing.stretch import LinearFrame, fixed_map, to_normalized
from ..processing.masks import regions_mask, validate_regions
from ..processing.object_color import hubble_input
from ..processing.pipeline import (
    AssetContext, ExecutionOptions, baseline_display, choose_backend, estimate_peak_ram_bytes, prepare_linear_frame, run_pipeline,
)
from ..processing.readers import evaluate_intake, read_image
from ..processing.readers.fits import header_to_text, read_fits, sensitive_keywords_in
from ..processing.recipe import PIPELINE_VERSION, parse_recipe
from ..processing.report import dependency_versions
from ..processing.star_protection import detect_stars

STAT_FLOOR = 1e-6
THUMB_EDGE = 256
BG_PREVIEW_EDGE = 640


# ----------------------------------------------------------------------------------------------- helpers
def to_u16(display: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(display.astype(np.float64), 0.0, 1.0) * 65535.0).astype(np.uint16)


def save_npy(path: Path, arr: np.ndarray) -> None:
    # On Windows a memory-mapped file that a preview request still holds cannot be rewritten (PermissionError, or
    # EINVAL "user-mapped section open"); retry briefly.
    last: Exception | None = None
    for _ in range(25):
        try:
            mm = np.lib.format.open_memmap(path, mode="w+", dtype=arr.dtype, shape=arr.shape)
            mm[:] = arr
            mm.flush()
            del mm
            return
        except OSError as exc:
            if not isinstance(exc, PermissionError) and exc.errno != errno.EINVAL:
                raise
            last = exc
            time.sleep(0.2)
    raise last  # type: ignore[misc]


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(4 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def luminance_histogram(display: np.ndarray, valid: np.ndarray, bins: int = 256) -> list[int]:
    from ..processing.diagnostics import luminance_np, strided

    L = luminance_np(display)[valid]
    hist, _ = np.histogram(strided(L), bins=bins, range=(0.0, 1.0))
    return [int(v) for v in hist]


def load_image(cfg: Config, asset: dict[str, Any]) -> ImageData:
    return read_image(
        Path(asset["path"]), asset["sha256"], cfg.max_pixels, asset["interpretation"], asset["inspection"],
        preview_only_state="linear",
    )


def baseline_label(intake: dict[str, Any], fmt: str) -> str:
    state = intake["resolved"]["state"]
    if fmt == "jpeg" or state == "rendered":
        return "Original view"
    if state == "linear":
        return "Original shown with a display stretch"
    return "Preview only — display stretch (state not confirmed)"


# ----------------------------------------------------------------------------------------------- prepare
def handle_prepare(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    asset = task["asset"]
    asset_dir = Path(task["asset_dir"])
    intake = evaluate_intake(asset["inspection"], asset["interpretation"])
    out: dict[str, Any] = {"intake": intake}
    if intake["status"] == "unsupported":
        return out
    insp = asset["inspection"]
    if not intake["can_preview"]:
        # HDU / layout questions pending: thumbnails of each candidate so the user can choose.
        thumbs = {}
        for cand in insp.get("candidates", []):
            if not cand["supported"]:
                continue
            ctl.check()
            try:
                img = read_fits(Path(asset["path"]), asset["sha256"], cfg.max_pixels, "linear", cand["index"], cand["kind"])
                frame = prepare_linear_frame(img)
                disp = baseline_display(img, frame)
                small, _ = exp.resize_u8(exp.to_u8(disp), THUMB_EDGE)
                exp_path = asset_dir / f"hdu-{cand['index']}.jpg"
                exp.write_jpeg(exp_path, small.astype(np.float32) / 255.0, 88)
                thumbs[str(cand["index"])] = exp_path.name
            except ProcessingError:
                continue
        out["hdu_thumbs"] = thumbs
        return out

    ctl.check()
    image = load_image(cfg, asset)
    frame = prepare_linear_frame(image) if image.domain == "linear" else None
    ctl.check()
    base = baseline_display(image, frame)
    u16 = to_u16(base)
    u16[~image.valid_mask] = 0
    save_npy(asset_dir / "baseline.npy", u16)
    small, scale = exp.resize_u8(exp.to_u8(base), THUMB_EDGE)
    exp.write_jpeg(asset_dir / "thumb.jpg", small.astype(np.float32) / 255.0, 88)
    if image.header is not None:
        (asset_dir / "header.txt").write_text(header_to_text(image.header), encoding="utf-8")
    state = intake["resolved"]["state"]
    meta = {
        "width": image.width,
        "height": image.height,
        "channel_layout": image.channel_layout,
        "domain": image.domain,
        "state": state,
        "label": baseline_label(intake, insp["format"]),
        "engine": PIPELINE_VERSION,
        "preview_only": state not in ("linear", "rendered"),
        "frame": frame.to_dict() if frame else None,
        "histogram": luminance_histogram(base, image.valid_mask),
        "invalid_pixels": int((~image.valid_mask).sum()),
        "orientation_transform": image.orientation_transform,
        "notes": image.notes,
        "units": image.units,
        "has_sensitive_metadata": bool(image.header is not None and sensitive_keywords_in(image.header)),
        "hubble_input": hubble_input(image.header),
        "source_dtype": image.source_dtype,
        "source_bit_depth": image.source_bit_depth,
    }
    (asset_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    out["meta"] = meta
    return out


# ----------------------------------------------------------------------------------------------- analysis
def _work_and_weight(image: ImageData, frame: dict[str, Any] | None, regions: list[dict[str, Any]]):
    h, w = image.height, image.width
    regs = validate_regions(regions, w, h) if regions else []
    prot = regions_mask(regs, w, h) if regs else np.zeros((h, w), dtype=bool)
    weight = image.valid_mask & ~prot
    if image.domain == "linear":
        fr = LinearFrame.from_dict(frame) or prepare_linear_frame(image)
        work = to_normalized(image.pixels, fr.offset, fr.scale)
    else:
        fr = None
        work = image.pixels.astype(np.float32, copy=False)
    return work, weight, prot, fr


def handle_analysis(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    asset = task["asset"]
    asset_dir = Path(task["asset_dir"])
    kind = task["analysis"]
    image = load_image(cfg, asset)
    ctl.check()
    prepared = asset.get("prepared") or {}
    work, weight, prot, frame = _work_and_weight(image, prepared.get("frame"), asset.get("regions") or [])
    star = detect_stars(work, weight, STAT_FLOOR)
    ctl.check()
    star_hard = star.hard if star.reliable else None
    if kind == "suggest_background":
        patches = bgmod.suggest_patches(work, weight, star_hard)
        return {"patches": patches, "note": "Heuristic suggestions only. Dark corners alone are not evidence of empty sky; confirm or edit each region."}
    if kind == "star_mask":
        key = hashlib.sha256(json.dumps(asset.get("regions") or [], sort_keys=True).encode()).hexdigest()[:10]
        png = asset_dir / f"starmask-{key}.png"
        if star.reliable and star.soft is not None:
            alpha = np.rint(np.clip(star.soft, 0, 1) * 170).astype(np.uint8)
            rgba = np.zeros((*alpha.shape, 4), dtype=np.uint8)
            rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3] = 255, 70, 70, alpha
            rgba, _ = exp.resize_u8(rgba, 2048) if max(alpha.shape) > 2048 else (rgba, 1.0)
            png.write_bytes(exp.encode_png(rgba))
        stats = {k: v for k, v in star.stats.items() if k != "settings"}
        return {"reliable": star.reliable, "file": png.name if star.reliable else None, "stats": stats, "settings": star.stats.get("settings")}
    if kind == "background_preview":
        method = task["method"]
        samples = task["samples"]
        strength = float(task.get("strength", 0.5))
        noise = estimate_noise(work, weight, star_hard, STAT_FLOOR)
        model = bgmod.build_model(work, weight, star_hard, samples, method, noise["sigma_white_equivalent"], prot)
        out: dict[str, Any] = {"model": model.to_dict(), "samples_hash": hashlib.sha256(json.dumps({"m": method, "s": [[s["x"], s["y"], s["w"], s["h"]] for s in samples]}, sort_keys=True).encode()).hexdigest()[:16]}
        if model.ok:
            corrected = work - bgmod.channel_offset_vector(model, strength)
            pm = bgmod.plane_map(model, image.height, image.width) if method == "planar" else None
            if pm is not None:
                corrected = corrected - ((pm * strength)[..., None] if corrected.ndim == 3 else pm * strength)
            if image.domain == "linear":
                disp = fixed_map(np, corrected, frame)[0]
            else:
                disp = np.clip(corrected, 0, 1)
            small, scale = exp.resize_u8(exp.to_u8(disp), BG_PREVIEW_EDGE)
            name = f"bgprev-{out['samples_hash']}-{int(strength * 100)}.jpg"
            exp.write_jpeg(asset_dir / name, small.astype(np.float32) / 255.0, 90)
            out["preview_file"] = name
            if model.plane:
                gy, gx = np.meshgrid(np.linspace(-1, 1, 24), np.linspace(-1, 1, 24), indexing="ij")
                p = model.plane
                grid = (gx - p["ref_x"]) * p["b"] + (gy - p["ref_y"]) * p["c"]
                out["plane_grid"] = [[float(v) for v in row] for row in grid]
        return out
    raise ProcessingError("UNKNOWN_TASK", f"Unknown analysis task {kind}")


# ----------------------------------------------------------------------------------------------- GPU state
class _Gpu:
    probed = False
    info: dict[str, Any] | None = None
    disabled_jobs: set[str] = set()


def ensure_probe(force: bool = False) -> dict[str, Any]:
    if force or not _Gpu.probed:
        _Gpu.info = probe_cuda()
        _Gpu.probed = True
    return _Gpu.info  # type: ignore[return-value]


def handle_probe(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    t0 = time.perf_counter()
    if cfg.cpu_only:
        return {"ok": False, "status": "unavailable", "note": "This app instance is running in CPU-only mode."}
    info = ensure_probe(force=True)
    info = dict(info)
    info["probe_seconds"] = round(time.perf_counter() - t0, 3)
    return info


# ----------------------------------------------------------------------------------------------- enhance
def _disk_check(cfg: Config, pixels: int, channels: int) -> None:
    free = shutil.disk_usage(cfg.data_dir).free
    need = pixels * channels * 4 * 6 + cfg.min_free_bytes
    if free < need:
        raise ProcessingError(
            "DISK_FULL", f"Not enough free disk space to save results (about {need / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free). Free some space and retry."
        )


def _write_summary(path: Path, run: dict[str, Any], report: dict[str, Any]) -> None:
    lines = [
        "EasyAstroEnhance processing summary",
        f"Run: {run['run_name']}   Engine: {PIPELINE_VERSION}",
        f"Source: {run['filename']}   SHA-256: {report['source']['sha256']}",
        f"Dimensions: {report['source']['dimensions']['width']} x {report['source']['dimensions']['height']}",
        f"Path: {report['mode']} ({report['source']['domain']} source)",
        f"Preset: {run['recipe'].get('preset')}",
        "",
        f"Result: {report['summary']}",
        "",
        "Operations (applied / reduced / skipped):",
    ]
    for op in report["operations"]:
        if op["status"] == "off":
            continue
        reason = f" — {op['reason']}" if op.get("reason") else ""
        lines.append(f"  - {op['name']}: {op['status']}{reason}")
    ex = report["execution"]
    lines += [
        "",
        f"Backend: {ex.get('actual_backend')} ({ex.get('device')}); requested: {ex.get('requested_device')}",
    ]
    for fb in ex.get("fallbacks", []):
        lines.append(f"  fallback from {fb['from']}: {fb['cause']} — {fb['message']}")
    lines += ["", report["scientific_disclosure"]]
    path.write_text("\n".join(lines), encoding="utf-8")


def _linear_history(report: dict[str, Any]) -> list[str]:
    """Short FITS HISTORY lines describing the linear operations (exact values live in processing.json)."""
    ops = {o["name"]: o for o in report.get("operations", [])}
    scale = ((report.get("source") or {}).get("normalization") or {}).get("scale") or 1.0
    lines: list[str] = []
    cos = ops.get("cosmetic") or {}
    if cos.get("status") == "applied":
        p = cos.get("parameters") or {}
        lines.append(f"Cosmetic correction: {p.get('hot_colored', 0)} colored hot, {p.get('cold', 0)} cold pixels repaired.")
    if (ops.get("gradient") or {}).get("status") == "applied":
        lines.append("Automatic polynomial gradient model subtracted.")
    n = ops.get("neutralize") or {}
    if n.get("status") == "applied" and n.get("parameters"):
        sky = n["parameters"].get("sky_per_channel") or []
        ped = n["parameters"].get("pedestal") or 0.0
        lines.append("Sky offsets (source units): " + ", ".join(f"{v * scale:.2f}" for v in sky))
        lines.append(f"Shared pedestal added (source units): {ped * scale:.2f}")
    wbop = ops.get("white_balance") or {}
    if wbop.get("status") == "applied" and wbop.get("parameters"):
        f = wbop["parameters"].get("factors_rgb") or []
        lines.append("White-balance gains R,G,B: " + ", ".join(f"{v:.4f}" for v in f))
    cat = ops.get("catalog_color") or {}
    if cat.get("status") == "applied":
        lines.append("Catalog gains R,G,B: " + ", ".join(f"{v:.4f}" for v in cat.get("gains_rgb") or []))
        if cat.get("sha256"):  # a user-imported reference CSV
            lines.append(f"Offline reference CSV SHA-256: {cat['sha256'][:24]}... (full hash in report)")
        else:  # Accurate star colours: the built-in catalog through the image's sky solution
            lines.append(f"Catalog colour: built-in Gaia DR3, {cat.get('used', 0)} stars, {cat.get('sky_solution') or '?'} sky solution")
    if (ops.get("deconvolution") or {}).get("status") == "applied":
        lines.append("Richardson-Lucy deconvolution applied (see processing.json).")
    if (ops.get("denoise") or {}).get("status") == "applied":
        lines.append("Wavelet noise reduction applied (see processing.json).")
    for name, what in (("ai_background", "background model subtracted"), ("ai_denoise", "noise reduction")):
        op = ops.get(name) or {}
        if op.get("status") == "applied":
            m = (op.get("parameters") or {}).get("model") or {}
            lines.append(f"AI (learned) {what}: {m.get('file')} sha256 {str(m.get('sha256'))[:16]}")
    return lines


# ----------------------------------------------------------------------------------------------- enhance helpers
# Worker-process caches: the linear stage of recent recipes (so display-only changes rerun only the display stage) and
# the most recent complete result (so Enhance right after a live preview with the same settings reuses it). Both give
# exactly the values a fresh run gives; the processing report records the reuse.
_CACHE: dict[str, Any] = {"stages": None, "result_key": None, "result": None}


def _stage_cache():
    if _CACHE["stages"] is None:
        import psutil

        from ..processing.pipeline import StageCache

        _CACHE["stages"] = StageCache(max_entries=2, max_bytes=int(psutil.virtual_memory().total * 0.2))
    return _CACHE["stages"]


def clear_caches() -> None:
    if _CACHE["stages"] is not None:
        _CACHE["stages"].clear()
    _CACHE["result_key"] = _CACHE["result"] = None
    import gc

    gc.collect()


def _memory_check(cfg: Config, asset: dict[str, Any], settings: dict[str, Any]) -> None:
    import psutil

    insp = asset["inspection"]
    state_guess = (asset["interpretation"] or {}).get("state")
    need = estimate_peak_ram_bytes(
        insp["height"], insp["width"], 3 if insp.get("channel_layout") == "rgb" else 1, "linear" if state_guess == "linear" else "rendered"
    )

    def budget() -> int:
        return int(psutil.virtual_memory().available * float(settings.get("ram_fraction", cfg.ram_fraction)))

    if need > budget():
        clear_caches()  # cached stages of other images may hold the memory this one needs
    if need > (b := budget()):
        raise ProcessingError(
            "INSUFFICIENT_MEMORY",
            f"Processing this {insp['width'] * insp['height'] / 1e6:.0f} MP image needs about {need / 1e9:.1f} GB of memory, but the "
            f"configured budget is {b / 1e9:.1f} GB. Close other programs or raise the memory fraction in Settings; nothing was changed.",
            f"estimate={need} budget={b}",
        )


def _execution_options(cfg: Config, settings: dict[str, Any], ctl, job_id: str | None) -> tuple[ExecutionOptions, dict[str, Any] | None, str]:
    import psutil

    device = "cpu" if cfg.cpu_only else settings.get("device", "auto")
    gpu_ok = False
    probe_info = None
    if device != "cpu":
        probe_info = ensure_probe()
        gpu_ok = bool(probe_info.get("ok"))

    def factory(name: str):
        if name == "gpu":
            free = None
            try:
                import cupy as cp  # noqa: F401  (only reached when the probe succeeded)

                free = int(cp.cuda.runtime.memGetInfo()[0])
            except Exception:
                pass
            limit = int(free * min(float(settings.get("gpu_memory_fraction", cfg.gpu_memory_fraction)), 0.7)) if free else None
            return get_backend("gpu", limit)
        return get_backend("cpu")

    opts = ExecutionOptions(
        device=device,
        gpu_available=gpu_ok,
        gpu_disabled=job_id is not None and job_id in _Gpu.disabled_jobs,
        gpu_memory_fraction=min(float(settings.get("gpu_memory_fraction", cfg.gpu_memory_fraction)), 0.7),
        ram_budget_bytes=int(psutil.virtual_memory().available * float(settings.get("ram_fraction", cfg.ram_fraction))),
        gpu_threshold_pixels=int(settings.get("gpu_threshold_pixels", cfg.gpu_threshold_pixels)),
        cpu_threads=cfg.cpu_threads or None,
        cancel_check=ctl.check,
        progress=ctl.progress,
        backend_factory=factory,
        ai_models_dir=cfg.ai_models_dir,
        color_catalog_dir=cfg.color_catalog_dir,
        reference_data_dir=cfg.reference_data_dir,
    )
    return opts, probe_info, device


def _asset_context(asset: dict[str, Any], cfg: Config | None = None) -> AssetContext:
    bg = asset.get("background")
    return AssetContext(
        regions=asset.get("regions") or [],
        background=bg if (bg and bg.get("confirmed")) else None,
        frame=(asset.get("prepared") or {}).get("frame"),
        dualband_confirmed=(asset.get("interpretation") or {}).get("dualband_confirmed") is True,
        sky_solution=load_sky_solution(cfg, asset) if cfg is not None else None,
    )


# ----------------------------------------------------------------------------------------------- sky solution
SKY_FILE = "sky-solution.json"


def load_sky_solution(cfg: Config, asset: dict[str, Any]) -> dict[str, Any] | None:
    """The stored solution for this asset's current HDU (an intake change makes an older one stale)."""
    p = cfg.assets_dir / asset["id"] / SKY_FILE
    try:
        sol = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if sol.get("hdu") != (asset.get("interpretation") or {}).get("hdu") or sol.get("source_sha256") != asset.get("sha256"):
        return None
    return sol


def solve_and_store(cfg: Config, image: ImageData, asset: dict[str, Any], user: dict[str, Any] | None, ctl) -> dict[str, Any]:
    from ..processing.catalogs import objects as dso
    from ..processing.catalogs import registry as refreg
    from ..processing.catalogs.stars import open_catalog
    from ..processing.sky_solution import sky_solution

    path = refreg.installed(cfg.reference_data_dir, "stars-gaia-dr3")
    if path is None:
        return {"status": "unavailable", "reason": "The star catalog is not installed (Settings → Reference data)."}
    resolver = None
    if refreg.group_ready(cfg.reference_data_dir, "objects"):
        objs = dso.objects_from(tuple(str(refreg.installed(cfg.reference_data_dir, k)) for k in refreg.GROUPS["objects"]))

        def resolver(name: str):
            o = dso.resolve_name(objs, name)
            return (o.ra, o.dec, o.name) if o else None
    ctl.progress("Finding where the image points on the sky")
    sol = sky_solution(image, open_catalog(str(path)), user, ctl.check, resolver)
    sol.update(hdu=(asset.get("interpretation") or {}).get("hdu"), source_sha256=asset.get("sha256"),
               engine=PIPELINE_VERSION, catalog_sha256=refreg.DATA["stars-gaia-dr3"].sha256, user_hints=user or None,
               width=image.width, height=image.height, flip_rows=bool(image.flip_rows_on_export))
    p = cfg.assets_dir / asset["id"] / SKY_FILE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(sol, default=float), encoding="utf-8")
    tmp.replace(p)
    return sol


def _ensure_solution(cfg: Config, image: ImageData, asset: dict[str, Any], recipe, ctx: AssetContext, ctl) -> AssetContext:
    """Accurate star colours need a sky solution: solve once (header WCS check or hinted solve) and keep it with the asset."""
    from dataclasses import replace

    if recipe.catalog_builtin and ctx.sky_solution is None and image.domain == "linear" and image.channels == 3:
        return replace(ctx, sky_solution=solve_and_store(cfg, image, asset, None, ctl))
    return ctx


def handle_sky_solve(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    asset = task["asset"]
    image = load_image(cfg, asset)
    return solve_and_store(cfg, image, asset, task.get("hints"), ctl)


def _enhance_cached(cfg: Config, image: ImageData, recipe, ctx: AssetContext, opts: ExecutionOptions):
    import copy
    from dataclasses import replace

    from ..processing.pipeline import stage_key

    key = stage_key(image, recipe, ctx, opts) + hashlib.sha256(json.dumps(recipe.model_dump(), sort_keys=True).encode()).hexdigest()
    if _CACHE["result_key"] == key and _CACHE["result"] is not None:
        res = _CACHE["result"]
        report = copy.deepcopy(res.report)
        report["linear_stage_cache"] = {
            "reused": True, "display_reused": True, "key": key[:16],
            "note": "This exact result was computed moments earlier (live preview) with the same image and settings and was reused.",
        }
        return replace(res, report=report)
    res = run_pipeline(image, recipe, ctx, opts, cache=_stage_cache())
    if not res.gpu_disabled and not res.report["execution"].get("fallbacks"):
        _CACHE["result_key"], _CACHE["result"] = key, res
    return res


def handle_enhance(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    asset = task["asset"]
    settings = task["settings"]
    recipe = parse_recipe(task["recipe"])
    run_dir = Path(task["run_dir"])
    partial = run_dir.with_name(run_dir.name + ".partial")
    if partial.exists():
        shutil.rmtree(partial, ignore_errors=True)

    ctl.progress("Reading image")
    import psutil

    _memory_check(cfg, asset, settings)
    image = load_image(cfg, asset)
    if (asset["interpretation"].get("state") or "") not in ("linear", "rendered") and asset["inspection"]["format"] != "jpeg":
        raise ProcessingError("STATE_NOT_CONFIRMED", "Confirm how this image was saved (linear stack or already processed) before enhancing it.")
    _disk_check(cfg, image.width * image.height, image.channels)
    partial.mkdir(parents=True, exist_ok=False)
    try:
        job_id = task["job_id"]
        opts, probe_info, device = _execution_options(cfg, settings, ctl, job_id)
        ctx = _ensure_solution(cfg, image, asset, recipe, _asset_context(asset, cfg), ctl)
        label_backend, _ = choose_backend(opts, image.height, image.width, image.channels)
        ctl.label("Processing: GPU + CPU" if label_backend == "gpu" else "Processing: CPU")
        result = _enhance_cached(cfg, image, recipe, ctx, opts)
        if result.gpu_disabled:
            _Gpu.disabled_jobs.add(job_id)
        ctl.label(
            "Processing: GPU + CPU" if result.report["execution"].get("actual_backend") == "gpu" else "Processing: CPU"
        )

        ctl.progress("Writing results")
        h, w = image.height, image.width
        if result.display.shape[:2] != (h, w) or not np.isfinite(result.display).all():
            raise ProcessingError("VALIDATION_FAILED", "The enhanced image failed validation and was not published.")
        bits = 8 if image.source_bit_depth <= 8 and image.source_format == "jpeg" else 16
        # Fixed order (it is the order of the export list); the files are written concurrently. The 16-bit display TIFF
        # is rendered on first request from display.npy, which holds exactly the values it encodes.
        specs: list[tuple[str, str, str, Any]] = [
            ("png", "enhanced.png", f"Enhanced PNG ({bits}-bit sRGB, full resolution)", lambda p: exp.write_png(p, result.display, bits)),
            ("tiff", exp.DEFERRED_TIFF, "Enhanced display TIFF (16-bit)", None),
            ("jpeg", "enhanced.jpg", "Enhanced JPEG (quality 95, for sharing)", lambda p: exp.write_jpeg(p, result.display, 95)),
        ]
        left = "Original view" if image.domain == "display" else "Original shown with a display stretch"
        specs.append(("comparison", "comparison.jpg", "Share-sized comparison JPEG", lambda p: exp.comparison_jpeg(p, result.baseline, result.display, left, "Enhanced")))

        if image.source_format == "fits":
            strip = bool(settings.get("strip_location", True))
            sol = ctx.sky_solution or {}
            solved = sol.get("header") if sol.get("status") == "solved" else None
            if image.domain == "linear":
                hist = _linear_history(result.report)
                specs.append(("fits", "processed-linear.fits", "Processed linear FITS (no display-only operations)",
                              lambda p: exp.write_fits(p, image, result.processed, "processed-linear", recipe.preset, strip, hist, solved)))
            else:
                specs.append(("fits", "display-processed.fits", "Display-processed FITS (not linear data)",
                              lambda p: exp.write_fits(p, image, result.display, "display-processed", recipe.preset, strip, None, solved)))
        elif image.source_format == "tiff" and image.domain == "linear":
            import tifffile

            specs.append(("linear-tiff", "processed-linear.tif", "Processed linear TIFF (float, no display-only operations)",
                          lambda p: tifffile.imwrite(p, np.asarray(result.processed, dtype=np.float32), photometric="rgb" if result.processed.ndim == 3 else "minisblack", compression="zlib")))

        # viewer arrays (uint16 memmaps; 8-bit sources are represented exactly as value*257)
        def viewer_arrays(_p: Path) -> None:
            save_npy(partial / "display.npy", to_u16(result.display))
            if result.display_fixed is not None:
                save_npy(partial / "display_fixed.npy", to_u16(result.display_fixed))
            if result.layers is not None:  # sources of the on-request Starless / Stars exports
                save_npy(partial / "display_starless.npy", to_u16(result.layers["starless"]))
                save_npy(partial / "display_stars.npy", to_u16(result.layers["stars"]))
                save_npy(partial / "starless_linear.npy", np.asarray(result.layers["starless_linear"], dtype=np.float32))

        layer_note = ("Made with learned (AI) star separation; large or saturated stars may remain partly in the starless "
                      "layer. Rendered on request; not part of Download all.")
        if result.layers is not None:
            specs.append(("starless-png", "starless.png", "Starless (display, 16-bit PNG)", None))
            specs.append(("stars-png", "stars-only.png", "Stars only on black (display, 16-bit PNG)", None))
            if image.source_format == "fits":
                specs.append(("starless-fits", "starless-linear.fits", "Starless linear FITS", None))
                specs.append(("stars-fits", "stars-linear.fits", "Stars linear FITS (processed minus starless)", None))

        ctl.check()
        jobs = [(name, writer) for _, name, _, writer in specs if writer is not None] + [("display.npy", viewer_arrays)]
        with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="eae-export") as pool:
            for f in [pool.submit(writer, partial / name) for name, writer in jobs]:
                f.result()
            ctl.check()
            eager = [name for _, name, _, writer in specs if writer is not None]
            hashes = dict(zip(eager, pool.map(lambda n: sha256_path(partial / n), eager)))

        # report + summary
        ex_list = []
        for kind, name, label, writer in specs:
            if writer is None:
                ex_list.append({"kind": kind, "filename": name, "label": label, "bytes": None, "sha256": None, "deferred": True,
                                "note": layer_note if kind in ("starless-png", "stars-png", "starless-fits", "stars-fits") else
                                "Rendered on first request from display.npy (identical values); size and hash are recorded then."})
            else:
                ex_list.append({"kind": kind, "filename": name, "label": label, "bytes": (partial / name).stat().st_size, "sha256": hashes[name]})
        report = result.report
        full = {
            "schema": 1,
            "run": {"run_id": task["run_id"], "run_name": task["run_name"], "asset_id": asset["id"], "filename": asset["filename"], "created_at": task["created_at"]},
            "requested_recipe": task["recipe"],
            "preset_snapshot": task.get("preset_snapshot"),
            "applied": report,
            "per_file_resolution": {
                "interpretation": asset["interpretation"],
                "protected_regions": asset.get("regions") or [],
                "background_confirmation": ctx.background,
                "baseline_frame": ctx.frame,
                "sky_solution": ctx.sky_solution,
            },
            "settings": {"device": device, "strip_location": settings.get("strip_location", True)},
            "resources": {
                "peak_ram_bytes": int(getattr(psutil.Process().memory_info(), "peak_wset", psutil.Process().memory_info().rss)),
                "note": "Worker-process working-set peak so far (monotonic across runs).",
            },
            "gpu_probe": probe_info,
            "exports": ex_list,
            "export_note": "processing.json itself is not listed in exports because it contains the export hashes.",
        }
        (partial / "processing.json").write_text(json.dumps(full, indent=2, default=str), encoding="utf-8")
        _write_summary(partial / "processing-summary.txt", {"run_name": task["run_name"], "filename": asset["filename"], "recipe": task["recipe"]}, report)
        for kind, name, label in (("report", "processing.json", "Processing report (JSON)"), ("summary", "processing-summary.txt", "Processing summary (text)")):
            ex_list.append({"kind": kind, "filename": name, "label": label, "bytes": (partial / name).stat().st_size, "sha256": sha256_path(partial / name)})

        # validate PNG round trip dimensions, then publish atomically
        import imagecodecs

        decoded = imagecodecs.png_decode((partial / "enhanced.png").read_bytes())
        if decoded.shape[:2] != (h, w):
            raise ProcessingError("VALIDATION_FAILED", "Exported image dimensions do not match the source; results were not published.")
        os.replace(partial, run_dir)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise

    notes_flag = (
        result.needs_review
        or any(op["status"] in ("skipped", "reduced") for op in report["operations"])
        or bool(report["execution"].get("fallbacks"))
        or bool(image.notes)
    )
    return {
        "run_id": task["run_id"],
        "summary": report["summary"],
        "state": "succeeded_with_notes" if notes_flag else "succeeded",
        "needs_review": result.needs_review,
        "backend_label": "Processing: GPU + CPU" if report["execution"].get("actual_backend") == "gpu" else "Processing: CPU",
        "exports": ex_list,
        "operations": [{"name": o["name"], "status": o["status"], "reason": o["reason"]} for o in report["operations"]],
        "fallbacks": report["execution"].get("fallbacks", []),
        "gpu_disabled": result.gpu_disabled,
        "report_path": str(run_dir / "processing.json"),
        "seconds": report["total_seconds"],
    }


# ----------------------------------------------------------------------------------------------- main loop
class _Ctl:
    def __init__(self, result_q, cancel_event, task_id: str) -> None:
        self.q, self.cancel_event, self.task_id = result_q, cancel_event, task_id

    def check(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()

    def progress(self, stage: str) -> None:
        self.check()
        self.q.put(("progress", self.task_id, {"stage": stage}))

    def label(self, label: str) -> None:
        self.q.put(("progress", self.task_id, {"label": label}))


def handle_live(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    """A live preview: the full-resolution enhanced display for the current settings, without exports or a run record.
    Uses the same pipeline and caches as Enhance, so the preview is exactly what Enhance would publish."""
    asset = task["asset"]
    settings = task["settings"]
    recipe = parse_recipe(task["recipe"])
    if (asset["interpretation"].get("state") or "") not in ("linear", "rendered") and asset["inspection"]["format"] != "jpeg":
        raise ProcessingError("STATE_NOT_CONFIRMED", "Confirm how this image was saved before previewing an enhancement.")
    ctl.progress("Reading image")
    _memory_check(cfg, asset, settings)
    image = load_image(cfg, asset)
    opts, _, _ = _execution_options(cfg, settings, ctl, None)
    result = _enhance_cached(cfg, image, recipe, _ensure_solution(cfg, image, asset, recipe, _asset_context(asset, cfg), ctl), opts)
    ctl.progress("Showing the preview")
    out_dir = Path(task["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    name = task["live_id"]
    save_npy(out_dir / f"{name}.npy", to_u16(result.display))
    if result.display_fixed is not None:
        save_npy(out_dir / f"{name}-fixed.npy", to_u16(result.display_fixed))
    for old in out_dir.glob("*.npy"):
        if not old.name.startswith(name):
            try:
                old.unlink()
            except OSError:  # still memory-mapped by a preview request; removed next time
                pass
    report = result.report
    return {
        "live_id": name, "summary": report["summary"], "needs_review": result.needs_review, "seconds": report["total_seconds"],
        "operations": [{"name": o["name"], "status": o["status"], "reason": o["reason"]} for o in report["operations"]],
        "reused": bool((report.get("linear_stage_cache") or {}).get("reused")), "has_fixed": result.display_fixed is not None,
        "auto_preset": report.get("auto_preset"),
    }


def _proxy_image(image: ImageData, target_pixels: int = 1_000_000) -> tuple[ImageData, int]:
    """A block-averaged copy of about ``target_pixels`` (linear values stay linear) for quick looks only."""
    import math
    from dataclasses import replace

    from ..processing.auto_preset import _bin

    f = max(1, math.ceil(math.sqrt(image.height * image.width / target_pixels)))
    if f == 1:
        return image, 1
    px, valid = _bin(image.pixels, image.valid_mask, f)
    if image.domain == "display":
        px = np.clip(px, 0.0, 1.0)
    return replace(image, pixels=px.astype(np.float32), valid_mask=valid, protected_mask=np.zeros(valid.shape, bool),
                   source_hash=f"{image.source_hash}:proxy{f}", notes=[]), f


def _scaled_rects(rects: list[dict[str, Any]], f: int, w: int, h: int) -> list[dict[str, int]]:
    out = []
    for r in rects or []:
        x0, y0 = int(r["x"]) // f, int(r["y"]) // f
        x1, y1 = min(w, -(-(int(r["x"]) + int(r["w"])) // f)), min(h, -(-(int(r["y"]) + int(r["h"])) // f))
        if x1 > x0 and y1 > y0:
            out.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    return out


def handle_preset_previews(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    """Small thumbnails of the image enhanced with each preset, rendered on a ~1 MP block-averaged copy (a quick look;
    the full-resolution result can differ slightly). Presets with the same linear settings share the linear stage."""
    from PIL import Image

    from ..processing.pipeline import StageCache

    asset = task["asset"]
    out_dir = Path(task["asset_dir"])
    image = load_image(cfg, asset)
    proxy, f = _proxy_image(image)
    actx = _asset_context(asset)
    bg = actx.background
    if bg and bg.get("samples"):
        bg = {**bg, "samples": _scaled_rects(bg["samples"], f, proxy.width, proxy.height)}
    ctx = AssetContext(regions=_scaled_rects(actx.regions, f, proxy.width, proxy.height), background=bg, frame=None,
                       dualband_confirmed=actx.dualband_confirmed)
    opts = ExecutionOptions(device="cpu", cancel_check=ctl.check, cpu_threads=cfg.cpu_threads or None,
                            ai_models_dir=cfg.ai_models_dir, color_catalog_dir=cfg.color_catalog_dir)
    cache = StageCache(max_entries=4)
    items = task["items"]
    results = []
    for i, item in enumerate(items):
        ctl.progress(f"Preview {i + 1} of {len(items)}")
        recipe = parse_recipe(item["recipe"])
        key = hashlib.sha256(json.dumps({"r": recipe.model_dump(), "e": PIPELINE_VERSION, "f": f, "s": asset["sha256"],
                                         "ctx": [ctx.regions, ctx.background, ctx.dualband_confirmed]}, sort_keys=True, default=str).encode()).hexdigest()[:20]
        name = f"presetprev-{key}.jpg"
        meta = out_dir / f"presetprev-{key}.json"
        if not (out_dir / name).exists() or not meta.exists():
            res = run_pipeline(proxy, recipe, ctx, opts, cache)
            im = Image.fromarray(exp.to_u8(res.display), "RGB" if res.display.ndim == 3 else "L")
            im.thumbnail((480, 480), Image.Resampling.LANCZOS)
            im.save(out_dir / name, "JPEG", quality=88)
            meta.write_text(json.dumps({"summary": res.summary, "auto": (res.report.get("auto_preset") or {}).get("label")}), encoding="utf-8")
        info = json.loads(meta.read_text(encoding="utf-8"))
        results.append({"id": item["id"], "file": name, **info})
    return {"items": results, "factor": f}


def handle_stack(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    """Stack frames from user folders (read-only) into a new linear FITS in the app's temporary folder."""
    import psutil

    from ..processing.stacking.stack import StackRequest, run_stack

    req = StackRequest(**task["request"])
    out = Path(task["out_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.stem + ".partial.fits")
    settings = task.get("settings") or {}
    if shutil.disk_usage(out.parent).free < cfg.min_free_bytes:
        raise ProcessingError("DISK_FULL", "The disk is nearly full; free some space and try again.")
    last = {"t": 0.0, "msg": ""}

    def progress(msg: str, frac: float) -> None:
        ctl.check()
        t = time.monotonic()
        if msg != last["msg"] and t - last["t"] > 0.25 or t - last["t"] > 1.0:
            last.update(t=t, msg=msg)
            ctl.q.put(("progress", ctl.task_id, {"stage": msg, "fraction": round(float(frac), 3)}))

    budget = int(psutil.virtual_memory().available * float(settings.get("ram_fraction", cfg.ram_fraction)) * 0.5)
    try:
        report = run_stack(req, partial, ctl.check, progress, device="cpu" if cfg.cpu_only else settings.get("device", "auto"),
                           threads=max(1, min(4, (os.cpu_count() or 2) - 1)), memory_budget_bytes=budget)
        partial.replace(out)
    finally:
        partial.unlink(missing_ok=True)
    return {"report": report, "path": str(out), "sha256": sha256_path(out), "size": out.stat().st_size}


def handle_color_mix(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    import psutil
    from astropy.io import fits
    from ..processing.color_mix import combine_channels

    sources = task["sources"]
    pixels = sum(s["prepared"]["width"] * s["prepared"]["height"] for s in sources)
    ref = sources[0]["prepared"]
    w, h = ref["width"], ref["height"]
    available = int(psutil.virtual_memory().available * cfg.ram_fraction)
    if 64 * pixels + 192 * w * h > available:
        raise ProcessingError("MIX_MEMORY", "The channel masters need more memory than is available for this mix.")
    _disk_check(cfg, w * h, 3)
    images = []
    for source in sources:
        ctl.check()
        images.append(load_image(cfg, source))
    rgb, header = combine_channels(images, task["mode"], task["gains"], task["strength"], task["prealigned"], ctl.check)
    out = Path(task["out_path"])
    partial = out.with_suffix(".partial")
    try:
        fits.PrimaryHDU(np.ascontiguousarray(np.moveaxis(rgb, -1, 0)), header=header).writeto(partial, checksum=True)
        ctl.check()
        partial.replace(out)
        return {"sha256": sha256_path(out), "size": out.stat().st_size}
    finally:
        partial.unlink(missing_ok=True)


HANDLERS = {"prepare": handle_prepare, "analysis": handle_analysis, "probe": handle_probe, "enhance": handle_enhance,
            "live": handle_live, "preset_previews": handle_preset_previews, "stack": handle_stack, "color_mix": handle_color_mix,
            "sky_solve": handle_sky_solve}


AI_IDLE_RELEASE_S = 60.0  # free the AI model sessions (and their GPU memory) after this long without work


def _release_idle_gpu() -> None:
    from ..processing.ai import runtime as ai_runtime

    if ai_runtime.drop_sessions() and "cupy" in sys.modules:  # never initialise CUDA just to free memory
        try:
            cp = sys.modules["cupy"]
            cp.get_default_memory_pool().free_all_blocks()
            cp.get_default_pinned_memory_pool().free_all_blocks()
        except Exception:
            pass


def worker_main(task_q, result_q, cancel_event, cfg: Config) -> None:
    """Entry point for the spawned worker."""
    os.environ.setdefault("OMP_NUM_THREADS", str(max(1, (os.cpu_count() or 2) - 1)))
    import queue as _queue

    import psutil

    from ..processing.ai import runtime as ai_runtime

    parent = os.getppid()
    idle_since = time.monotonic()
    while True:
        try:
            task = task_q.get(timeout=2.0)
        except _queue.Empty:
            if not psutil.pid_exists(parent):  # the server was killed: never linger as an orphan
                break
            if time.monotonic() - idle_since >= AI_IDLE_RELEASE_S and ai_runtime.has_sessions():
                _release_idle_gpu()
            continue
        if task is None:
            break
        task_id = task["task_id"]
        ctl = _Ctl(result_q, cancel_event, task_id)
        try:
            payload = HANDLERS[task["kind"]](cfg, task, ctl)
            result_q.put(("done", task_id, payload))
        except Cancelled:
            result_q.put(("cancelled", task_id, None))
        except ProcessingError as exc:
            result_q.put(("error", task_id, exc.as_dict()))
        except MemoryError:
            result_q.put(("error", task_id, {"code": "OUT_OF_MEMORY", "message": "Not enough memory to process this image. Close other applications and try again.", "detail": None}))
        except Exception as exc:
            result_q.put(("error", task_id, {"code": "INTERNAL_ERROR", "message": "Something went wrong while processing this image.", "detail": f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=-10)}"}))  # innermost frames: where it failed
        idle_since = time.monotonic()

