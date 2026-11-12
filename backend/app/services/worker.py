"""The single worker process: decoding, analysis and enhancement run here, never in request handlers.

Windows-safe: started with the ``spawn`` start method; CUDA/CuPy are initialized only in this process.
The worker never opens the SQLite database; it exchanges bounded messages with the coordinator.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Config
from ..processing import background as bgmod
from ..processing import export as exp
from ..processing.backends import BackendUnavailable, get_backend, probe_cuda
from ..processing.denoise import estimate_noise
from ..processing.imagedata import Cancelled, ImageData, ProcessingError
from ..processing.linear import LinearFrame, fixed_map, to_normalized
from ..processing.masks import regions_mask, validate_regions
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
    # On Windows a memory-mapped file that a preview request still holds cannot be rewritten; retry briefly.
    last: Exception | None = None
    for _ in range(25):
        try:
            mm = np.lib.format.open_memmap(path, mode="w+", dtype=arr.dtype, shape=arr.shape)
            mm[:] = arr
            mm.flush()
            del mm
            return
        except PermissionError as exc:
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
        "preview_only": state not in ("linear", "rendered"),
        "frame": frame.to_dict() if frame else None,
        "histogram": luminance_histogram(base, image.valid_mask),
        "invalid_pixels": int((~image.valid_mask).sum()),
        "orientation_transform": image.orientation_transform,
        "notes": image.notes,
        "units": image.units,
        "has_sensitive_metadata": bool(image.header is not None and sensitive_keywords_in(image.header)),
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
        fr = LinearFrame.from_dict(frame) if frame else prepare_linear_frame(image)
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


def handle_enhance(cfg: Config, task: dict[str, Any], ctl) -> dict[str, Any]:
    asset = task["asset"]
    settings = task["settings"]
    recipe = parse_recipe(task["recipe"])
    run_dir = Path(task["run_dir"])
    partial = run_dir.with_name(run_dir.name + ".partial")
    if partial.exists():
        shutil.rmtree(partial, ignore_errors=True)

    ctl.progress("Reading image")
    insp_dims = asset["inspection"]
    state_guess = (asset["interpretation"] or {}).get("state")
    import psutil

    ram_budget = int(psutil.virtual_memory().available * float(settings.get("ram_fraction", cfg.ram_fraction)))
    need = estimate_peak_ram_bytes(
        insp_dims["height"], insp_dims["width"], 3 if insp_dims.get("channel_layout") == "rgb" else 1, "linear" if state_guess == "linear" else "rendered"
    )
    if need > ram_budget:
        raise ProcessingError(
            "INSUFFICIENT_MEMORY",
            f"Processing this {insp_dims['width'] * insp_dims['height'] / 1e6:.0f} MP image needs about {need / 1e9:.1f} GB of memory, but the "
            f"configured budget is {ram_budget / 1e9:.1f} GB. Close other programs or raise the memory fraction in Settings; nothing was changed.",
            f"estimate={need} budget={ram_budget}",
        )
    image = load_image(cfg, asset)
    if (asset["interpretation"].get("state") or "") not in ("linear", "rendered") and asset["inspection"]["format"] != "jpeg":
        raise ProcessingError("STATE_NOT_CONFIRMED", "Confirm how this image was saved (linear stack or already processed) before enhancing it.")
    _disk_check(cfg, image.width * image.height, image.channels)
    partial.mkdir(parents=True, exist_ok=False)
    try:
        # execution preferences
        device = settings.get("device", "auto")
        gpu_ok = False
        probe_info = None
        if device != "cpu":
            probe_info = ensure_probe()
            gpu_ok = bool(probe_info.get("ok"))
        job_id = task["job_id"]

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

        import psutil

        opts = ExecutionOptions(
            device=device,
            gpu_available=gpu_ok,
            gpu_disabled=job_id in _Gpu.disabled_jobs,
            gpu_memory_fraction=min(float(settings.get("gpu_memory_fraction", cfg.gpu_memory_fraction)), 0.7),
            ram_budget_bytes=int(psutil.virtual_memory().available * float(settings.get("ram_fraction", cfg.ram_fraction))),
            gpu_threshold_pixels=int(settings.get("gpu_threshold_pixels", cfg.gpu_threshold_pixels)),
            cancel_check=ctl.check,
            progress=ctl.progress,
            backend_factory=factory,
        )
        bg = asset.get("background")
        ctx = AssetContext(
            regions=asset.get("regions") or [],
            background=bg if (bg and bg.get("confirmed")) else None,
            frame=(asset.get("prepared") or {}).get("frame"),
        )
        label_backend, _ = choose_backend(opts, image.height, image.width, image.channels)
        ctl.label("Processing: GPU + CPU" if label_backend == "gpu" else "Processing: CPU")
        result = run_pipeline(image, recipe, ctx, opts)
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
        files: dict[str, tuple[str, str]] = {}  # kind -> (filename, label)

        def put(kind: str, name: str, label: str, writer) -> None:
            ctl.check()
            writer(partial / name)
            files[kind] = (name, label)

        put("png", "enhanced.png", f"Enhanced PNG ({bits}-bit sRGB, full resolution)", lambda p: exp.write_png(p, result.display, bits))
        put("tiff", "enhanced-display.tif", "Enhanced display TIFF (16-bit)", lambda p: exp.write_tiff16(p, result.display))
        put("jpeg", "enhanced.jpg", "Enhanced JPEG (quality 95, for sharing)", lambda p: exp.write_jpeg(p, result.display, 95))
        left = "Original view" if image.domain == "display" else "Original shown with a display stretch"
        put("comparison", "comparison.jpg", "Share-sized comparison JPEG", lambda p: exp.comparison_jpeg(p, result.baseline, result.display, left, "Enhanced"))

        if image.source_format == "fits":
            strip = bool(settings.get("strip_location", True))
            if image.domain == "linear":
                put("fits", "processed-linear.fits", "Processed linear FITS (no display-only operations)",
                    lambda p: exp.write_fits(p, image, result.processed, "processed-linear", recipe.preset, strip))
            else:
                put("fits", "display-processed.fits", "Display-processed FITS (not linear data)",
                    lambda p: exp.write_fits(p, image, result.display, "display-processed", recipe.preset, strip))
        elif image.source_format == "tiff" and image.domain == "linear":
            import tifffile

            put("linear-tiff", "processed-linear.tif", "Processed linear TIFF (float, no display-only operations)",
                lambda p: tifffile.imwrite(p, np.asarray(result.processed, dtype=np.float32), photometric="rgb" if result.processed.ndim == 3 else "minisblack", compression="zlib"))

        # viewer arrays (uint16 memmaps; 8-bit sources are represented exactly as value*257)
        d16 = to_u16(result.display)
        save_npy(partial / "display.npy", d16)
        if result.display_fixed is not None:
            save_npy(partial / "display_fixed.npy", to_u16(result.display_fixed))

        # report + summary
        ex_list = []
        for kind, (name, label) in files.items():
            ex_list.append({"kind": kind, "filename": name, "label": label, "bytes": (partial / name).stat().st_size, "sha256": sha256_path(partial / name)})
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


HANDLERS = {"prepare": handle_prepare, "analysis": handle_analysis, "probe": handle_probe, "enhance": handle_enhance}


def worker_main(task_q, result_q, cancel_event, cfg: Config) -> None:
    """Entry point for the spawned worker."""
    os.environ.setdefault("OMP_NUM_THREADS", str(max(1, (os.cpu_count() or 2) - 1)))
    import queue as _queue

    import psutil

    parent = os.getppid()
    while True:
        try:
            task = task_q.get(timeout=2.0)
        except _queue.Empty:
            if not psutil.pid_exists(parent):  # the server was killed: never linger as an orphan
                break
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
            result_q.put(("error", task_id, {"code": "INTERNAL_ERROR", "message": "Something went wrong while processing this image.", "detail": f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}"}))

