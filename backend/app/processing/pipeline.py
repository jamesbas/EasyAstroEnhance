"""The enhancement pipeline: analysis (global statistics, CPU) followed by one contiguous pixel group
(CPU or GPU, full-frame or tiled), clipping guardrail, protected-region restoration and reporting.

Two display paths share the same tail:
* rendered (JPEG, display-referred TIFF/FITS): background -> denoise -> tone -> star protection ->
  local contrast -> color/gamut;
* linear (stacked TIFF/FITS): background -> denoise (the processed-linear array is saved here, before
  any display-only operation) -> asinh display renderer -> the same tone/star/contrast/color tail.

No module here touches HTTP, the database or the UI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from . import background as bgmod
from . import local_contrast as lcmod
from .backends import Backend, BackendUnavailable, NumpyBackend, RecoverableBackendError, get_backend
from .backends.base import kernel_radius
from .color import gamut_fit, luminance, reconstruct_rgb, saturate
from .denoise import HALO as DENOISE_HALO
from .denoise import DenoiseParams, denoise, estimate_noise
from .diagnostics import clip_report, merge_clip_counts
from .imagedata import Cancelled, ImageData, ProcessingError
from .linear import (
    BASELINE_K, LinearFrame, derive_frame, derive_normalization, fixed_map, from_normalized, to_normalized,
)
from .local_contrast import DEFAULT_SCALE_PX, LocalContrastParams
from .masks import masked_gaussian, regions_mask, region_summary, validate_regions
from .recipe import PIPELINE_VERSION, STRENGTH_TABLES, Recipe
from .report import dependency_versions
from .star_protection import StarMask, detect_stars
from .tiling import run_tiled
from .tone import ManualTone, apply_manual, asinh_map, rational_gain, smoothstep, validate_monotonic

CLIP_THRESHOLD_BLACK = 0.001
CLIP_THRESHOLD_WHITE = 0.001
STAT_FLOOR = 1e-6
BYTES_PER_PIXEL_PER_CHANNEL = 80  # conservative live-buffer estimate for the pixel group (temporaries included)


@dataclass
class AssetContext:
    """Per-asset data (never taken from a preset): protected regions, background confirmation, frozen frame."""

    regions: list[dict[str, Any]] = field(default_factory=list)
    background: dict[str, Any] | None = None
    frame: dict[str, Any] | None = None


@dataclass
class ExecutionOptions:
    device: str = "auto"  # auto | gpu | cpu
    gpu_available: bool = False
    gpu_disabled: bool = False  # set after a device failure earlier in the same job
    gpu_memory_fraction: float = 0.7
    ram_budget_bytes: int | None = None
    gpu_threshold_pixels: int = 2_000_000
    force_tile: int | None = None
    cancel_check: Callable[[], None] | None = None
    progress: Callable[[str], None] | None = None
    backend_factory: Callable[[str], Backend] | None = None


@dataclass
class PipelineResult:
    display: np.ndarray
    baseline: np.ndarray
    display_fixed: np.ndarray | None
    processed: np.ndarray | None
    valid_mask: np.ndarray
    protected_mask: np.ndarray
    report: dict[str, Any]
    summary: str
    needs_review: bool
    gpu_disabled: bool
    star_soft: np.ndarray | None = None


@dataclass
class Params:
    mode: str
    channels: int
    bg_offsets: np.ndarray | None
    denoise: DenoiseParams | None
    tone_enabled: bool
    gain: float
    k: float
    frame: LinearFrame | None
    eframe: LinearFrame | None
    manual: ManualTone
    star_amount: float
    lc: LocalContrastParams | None
    saturation: float

    @property
    def tail_needed(self) -> bool:
        return bool(
            self.tone_enabled or not self.manual.neutral or self.lc is not None or self.saturation > 1.0
        )

    @property
    def halo(self) -> int:
        h = DENOISE_HALO if self.denoise else 0
        if self.star_amount > 0:
            h = max(h, kernel_radius(HALO_SIGMA) + 2)
        if self.lc:
            h = max(h, self.lc.halo + kernel_radius(HALO_SIGMA))
        return h


HALO_SIGMA = 6.0
STAR_EXCESS_SCALE = 0.08  # display-luminance excess over the star-free surroundings at which protection is full


def baseline_display(image: ImageData, frame: LinearFrame | None) -> np.ndarray:
    """Original display values: decoded pixels (rendered) or the frozen asinh mapping (linear)."""
    if image.domain == "display":
        return image.pixels
    assert frame is not None
    u = to_normalized(image.pixels, frame.offset, frame.scale)
    return fixed_map(np, u, frame)[0].astype(np.float32)


def prepare_linear_frame(image: ImageData, regions: list[dict[str, Any]] | None = None) -> LinearFrame:
    """Derive the frozen baseline mapping once from the source (used by the asset's baseline preview and every run)."""
    weight = image.valid_mask.copy()
    if regions:
        weight &= ~regions_mask(regions, image.width, image.height)
    offset, scale = derive_normalization(image.pixels, weight)
    u = to_normalized(image.pixels, offset, scale)
    star = detect_stars(u, weight, STAT_FLOOR) if weight.any() else None
    return derive_frame(u, weight, star.hard if star and star.reliable else None, offset, scale, BASELINE_K)


def _strength(table: str, name: str, override: float | None, reduction: float, neutral: float) -> float:
    v = STRENGTH_TABLES[table][name] if override is None else override
    return neutral + (v - neutral) * reduction


def _tone_slope_at_sky(image_mode: str, sky: float, gain: float, frame: LinearFrame | None, k: float) -> float:
    if image_mode == "rendered":
        return gain / (1.0 + (gain - 1.0) * max(sky, 0.0)) ** 2
    assert frame is not None
    s = max(sky - frame.black, 0.0) / frame.span
    return (k / np.arcsinh(k)) / np.sqrt(1.0 + (k * s) ** 2) / frame.span


def estimate_memory_per_pixel(channels: int) -> int:
    return BYTES_PER_PIXEL_PER_CHANNEL * max(1, channels)


# Measured peak working-set per channel-pixel for the whole run on the target PC (tools/benchmark.py: 21 MP RGB,
# 3.6 GB rendered / 7.2 GB linear), rounded up. Used for the up-front memory check, not a promise.
PEAK_RAM_BYTES_PER_CHANNEL_PIXEL = {"rendered": 60, "linear": 120}


def estimate_peak_ram_bytes(height: int, width: int, channels: int, domain: str) -> int:
    return int(height) * int(width) * max(1, channels) * PEAK_RAM_BYTES_PER_CHANNEL_PIXEL["linear" if domain == "linear" else "rendered"]


class _Timings:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def run(self, name: str, backend: str, fn, **extra):
        t0 = time.perf_counter()
        out = fn()
        self.items.append({"stage": name, "backend": backend, "seconds": round(time.perf_counter() - t0, 4), **extra})
        return out


def _group(be: Backend, tile_in: dict[str, np.ndarray], inner: tuple[int, int, int, int], P: Params):
    xp = be.xp
    iy0, iy1, ix0, ix1 = inner
    x = be.asarray(tile_in["x"])
    w = be.asarray(tile_in["w"])
    star = be.asarray(tile_in["star"])
    src = be.asarray(tile_in["src"])
    rgb = x.ndim == 3

    if P.bg_offsets is not None:
        x = x - xp.asarray(P.bg_offsets)
        if "plane" in tile_in:
            pl = be.asarray(tile_in["plane"])
            x = x - (pl[..., None] if rgb else pl)
    if P.denoise is not None:
        x = denoise(be, x, w, star, P.denoise)
    proc = x

    if P.mode == "linear":
        rgb0, L0 = fixed_map(xp, x, P.frame)
        if P.tone_enabled:
            Lx = luminance(xp, x)
            s = xp.maximum(Lx - P.eframe.black, 0.0) / P.eframe.span
            t_base = asinh_map(xp, s, P.k)
        else:
            t_base = L0
    else:
        rgb0 = x
        L0 = luminance(xp, x)
        t_base = rational_gain(xp, L0, P.gain) if P.tone_enabled else L0
    Lt = apply_manual(xp, t_base, P.manual)

    if P.tail_needed:
        delta = Lt - L0
        if P.star_amount > 0:
            # Protect only where a compact star is genuinely brighter than its star-free surroundings, so the
            # sky ring around a star keeps its normal stretch (no dark rings, no abrupt mask edges).
            w_nostar = w * (1.0 - xp.clip(star * 2.0, 0.0, 1.0))
            excess = L0 - masked_gaussian(be, L0, w_nostar, HALO_SIGMA)
            prot = star * smoothstep(xp, excess / STAR_EXCESS_SCALE)
            delta = xp.where(delta > 0, delta * (1.0 - P.star_amount * prot), delta)
        Lp = L0 + delta
        if P.lc is not None:
            halo_mask = xp.clip(be.gaussian(star, HALO_SIGMA) * 2.0, 0.0, 1.0)
            Lp = Lp + lcmod.local_contrast_boost(be, Lp, w, halo_mask, P.lc)
        y = reconstruct_rgb(xp, rgb0, L0, Lp)
        if rgb:
            y = gamut_fit(xp, y)
            y = saturate(xp, y, P.saturation)
    else:
        y = rgb0

    sl = (slice(iy0, iy1), slice(ix0, ix1))
    eligible = w[sl] > 0
    counts = clip_report(src[sl], y[sl], eligible, xp=xp)
    out: dict[str, np.ndarray] = {"y": be.asnumpy(xp.clip(y[sl], 0.0, 1.0)).astype(np.float32, copy=False)}
    if P.mode == "linear":
        out["proc"] = be.asnumpy(proc[sl]).astype(np.float32, copy=False)
        out["fixed"] = be.asnumpy(xp.clip(rgb0[sl], 0.0, 1.0)).astype(np.float32, copy=False)
    be.synchronize()
    return out, counts


def run_pipeline(image: ImageData, recipe: Recipe, ctx: AssetContext, opts: ExecutionOptions | None = None) -> PipelineResult:
    opts = opts or ExecutionOptions()
    check = opts.cancel_check or (lambda: None)

    def progress(msg: str) -> None:
        check()
        if opts.progress:
            opts.progress(msg)

    timings = _Timings()
    t_start = time.perf_counter()
    h, w = image.height, image.width
    channels = image.channels
    mode = "linear" if image.domain == "linear" else "rendered"
    adv = recipe.advanced
    ops: list[dict[str, Any]] = []
    notes: list[str] = list(image.notes)

    # ---------------------------------------------------------------- masks
    progress("Measuring image")
    regions = validate_regions(ctx.regions, w, h) if (recipe.protect_regions and ctx.regions) else []
    protected = regions_mask(regions, w, h) if regions else np.zeros((h, w), dtype=bool)
    weight = image.valid_mask & ~protected
    if not weight.any():
        raise ProcessingError("NO_VALID_PIXELS", "There are no valid, unprotected pixels to process.")

    # ---------------------------------------------------------------- work array and baseline
    frame: LinearFrame | None = None
    if mode == "linear":
        frame = LinearFrame.from_dict(ctx.frame) if ctx.frame else None
        if frame is None:
            offset, scale = derive_normalization(image.pixels, weight)
            u0 = to_normalized(image.pixels, offset, scale)
            frame = derive_frame(u0, weight, None, offset, scale, BASELINE_K)
        work = to_normalized(image.pixels, frame.offset, frame.scale)
    else:
        work = image.pixels.astype(np.float32, copy=False)
    baseline = baseline_display(image, frame)

    manual = ManualTone(recipe.tone.brightness_ev, recipe.tone.shadows, recipe.tone.highlights, recipe.tone.black_point)
    validate_monotonic(manual)
    tone_stage = recipe.tone.enabled or not manual.neutral
    is_noop = not (
        recipe.denoise.enabled or tone_stage or recipe.local_contrast.enabled
        or (recipe.color.enabled and channels == 3) or recipe.background.enabled
    )

    # ---------------------------------------------------------------- analysis (CPU, global, once)
    star: StarMask | None = None
    need_star = (recipe.denoise.enabled or recipe.local_contrast.enabled or (recipe.star_protection.enabled and tone_stage)) and not is_noop
    if need_star:
        progress("Finding stars")
        star = timings.run("star detection", "cpu", lambda: detect_stars(work, weight, STAT_FLOOR), note="global connected components")
    star_hard = star.hard if star and star.reliable else None
    star_soft = star.soft if star and star.reliable else None

    noise: dict[str, float] = {}
    if recipe.denoise.enabled:
        progress("Measuring noise")
        noise = timings.run("noise estimate", "cpu", lambda: estimate_noise(work, weight, star_hard, STAT_FLOOR))

    # background model (supervised)
    bg_model: bgmod.BgModel | None = None
    bg_status = {"name": "background", "requested": recipe.background.enabled}
    if recipe.background.enabled:
        progress("Checking background samples")
        conf = ctx.background
        if not conf or not conf.get("confirmed") or not conf.get("samples"):
            bg_status.update(status="skipped", reason="No confirmed sky regions for this image yet (background balancing is pending).")
        elif conf.get("method") != recipe.background.method:
            bg_status.update(status="skipped", reason=f"Confirmed sky regions are for the '{conf.get('method')}' model, not '{recipe.background.method}'; confirm the new model first.")
        else:
            sigma_pix = noise.get("sigma_white_equivalent") or estimate_noise(work, weight, star_hard, STAT_FLOOR)["sigma_white_equivalent"]
            model = timings.run(
                "background model", "cpu",
                lambda: bgmod.build_model(work, weight, star_hard, conf["samples"], recipe.background.method, sigma_pix, protected),
            )
            if not model.ok:
                msgs = "; ".join(i.message for i in model.issues if i.level == "error")
                bg_status.update(status="skipped", reason=f"The confirmed sky regions did not validate on this run: {msgs}")
            else:
                bg_model = model
    if not recipe.background.enabled:
        bg_status.update(status="off", reason=None)

    bg_plane_full: np.ndarray | None = None
    bg_strength_base = _strength("background", recipe.background.strength, adv.background_strength, 1.0, 0.0)

    # enhanced linear frame: derived from the background-corrected data (before denoise)
    def bg_corrected_for_frame(strength: float) -> np.ndarray:
        if bg_model is None:
            return work
        off = bgmod.channel_offset_vector(bg_model, strength)
        out = work - off
        pm = bgmod.plane_map(bg_model, h, w)
        if pm is not None and bg_model.method == "planar":
            out = out - (pm * strength)[..., None] if out.ndim == 3 else out - pm * strength
        return out

    # ---------------------------------------------------------------- guardrail loop
    backend_name, backend_reason = choose_backend(opts, h, w, channels)
    band_sigma_cache: dict[float, float] = {}
    reduction = 1.0
    attempt = 0
    first_counts = None
    guard_action = "none"
    needs_review = False
    gpu_disabled = opts.gpu_disabled
    exec_info: dict[str, Any] = {}
    outputs: dict[str, np.ndarray] = {}
    counts: dict[str, Any] = {}
    P: Params | None = None
    while True:
        attempt += 1
        P = _resolve_params(
            recipe, mode, channels, work, weight, star_hard, noise, frame, bg_model, bg_corrected_for_frame, bg_strength_base,
            manual, tone_stage, star, band_sigma_cache, reduction, regions_ok=True,
        )
        plane = None
        if bg_model is not None and bg_model.method == "planar":
            pm = bgmod.plane_map(bg_model, h, w)
            plane = (pm * (bg_strength_base * reduction)) if pm is not None else None
        progress("Enhancing")
        exec_in = {
            "x": work,
            "w": weight.astype(np.float32),
            "star": star_soft if star_soft is not None else np.zeros((h, w), dtype=np.float32),
            "src": baseline,
        }
        if plane is not None:
            exec_in["plane"] = plane
        outputs, counts, backend_name, exec_info, gpu_disabled = _execute(
            P, exec_in, h, w, channels, mode, opts, backend_name, gpu_disabled, timings, check
        )
        if first_counts is None:
            first_counts = counts
        exec_info["backend_reason"] = backend_reason
        black_bad = counts["new_black_fraction"] > CLIP_THRESHOLD_BLACK
        white_bad = counts["new_white_fraction"] > CLIP_THRESHOLD_WHITE
        if (black_bad or white_bad) and attempt == 1 and not is_noop:
            reduction = 0.5
            guard_action = "reduced"
            progress("Reducing strength after clipping check")
            continue
        if black_bad or white_bad:
            guard_action = "needs_review"
            needs_review = True
        break

    # ---------------------------------------------------------------- restore protected/invalid, finalize
    progress("Finalizing")
    display = outputs["y"]
    prot, invalid = protected, ~image.valid_mask
    if prot.any():
        display[prot] = baseline[prot]
    if invalid.any():
        display[invalid] = 0.0
    display_fixed = None
    processed = None
    if mode == "linear":
        display_fixed = outputs["fixed"]
        if prot.any():
            display_fixed[prot] = baseline[prot]
        if invalid.any():
            display_fixed[invalid] = 0.0
        linear_ops = bg_model is not None or P.denoise is not None
        if linear_ops:
            export_dtype = image.pixels.dtype
            processed = from_normalized(outputs["proc"], frame.offset, frame.scale, export_dtype)
            if prot.any():
                processed[prot] = image.pixels[prot]
        else:
            processed = image.pixels

    # ---------------------------------------------------------------- report
    ops.extend(_operation_report(recipe, image, P, bg_status, bg_model, star, tone_stage, manual, channels, mode, backend_name, reduction, is_noop, regions))
    summary = _summary_note(ops)
    final_counts = counts
    report = {
        "engine_version": PIPELINE_VERSION,
        "mode": mode,
        "no_operations_run": is_noop,
        "operations": ops,
        "summary": summary,
        "needs_review": needs_review,
        "source": {
            "sha256": image.source_hash,
            "format": image.source_format,
            "dtype": image.source_dtype,
            "bit_depth": image.source_bit_depth,
            "dimensions": {"width": w, "height": h, "channels": channels},
            "orientation_transform": image.orientation_transform,
            "units": image.units,
            "domain": image.domain,
            "normalization": image.normalization.to_dict() if mode == "rendered" else {
                "kind": "linear_shared", "scale": frame.scale, "offset": frame.offset,
                "note": "one shared scale/offset for all channels; reversible; applied only for processing",
            },
            "invalid_pixels": int(invalid.sum()),
            "metadata": image.metadata,
        },
        "protected_regions": region_summary(regions, w, h),
        "baseline_frame": frame.to_dict() if frame else None,
        "enhanced_frame": P.eframe.to_dict() if (P.eframe and P.tone_enabled) else None,
        "clipping": {
            "thresholds": {"new_black_fraction": CLIP_THRESHOLD_BLACK, "new_white_fraction": CLIP_THRESHOLD_WHITE},
            "guard_action": guard_action,
            "first_pass": first_counts,
            "final": final_counts,
            "note": "New clipping is counted from per-pixel transitions; invalid and protected pixels are excluded. "
            "Negative physical FITS values are not clipping and are retained in the processed-linear array.",
            "negative_values_source": int((image.pixels[image.valid_mask] < 0).sum()) if mode == "linear" else 0,
        },
        "execution": exec_info,
        "stage_timings": timings.items,
        "total_seconds": round(time.perf_counter() - t_start, 4),
        "dependencies": dependency_versions(),
        "noise_estimate": {
            **noise,
            "limitations": "Robust MAD of Gaussian high-pass residuals over valid, unprotected, non-star pixels. "
            "Stacking/resampling correlate noise, so this is approximate and not a calibrated signal-to-noise measurement.",
        } if noise else None,
        "scientific_disclosure": (
            "This is display enhancement, not scientific calibration. Background neutralization is not photometric "
            "color calibration, and a sharper appearance is not additional measured resolution. No pixels were generated."
        ),
    }
    return PipelineResult(
        display=display, baseline=baseline, display_fixed=display_fixed, processed=processed,
        valid_mask=image.valid_mask, protected_mask=protected, report=report, summary=summary,
        needs_review=needs_review, gpu_disabled=gpu_disabled, star_soft=star_soft,
    )


# ======================================================================================================
def _resolve_params(
    recipe, mode, channels, work, weight, star_hard, noise, frame, bg_model, bg_corrected_for_frame, bg_strength_base,
    manual, tone_stage, star, band_cache, reduction, regions_ok,
) -> Params:
    adv = recipe.advanced
    bg_offsets = None
    if bg_model is not None:
        strength = bg_strength_base * reduction
        bg_offsets = bgmod.channel_offset_vector(bg_model, strength)
    dn = None
    if recipe.denoise.enabled:
        amount = _strength("denoise", recipe.denoise.strength, adv.denoise_amount, 1.0, 0.0)
        dn = DenoiseParams(amount, noise["sigma_residual"], noise["sigma_chroma_residual"] or noise["sigma_residual"])
    gain = 1.0
    k = BASELINE_K
    eframe = None
    if recipe.tone.enabled:
        if mode == "rendered":
            gain = _strength("gain", recipe.tone.strength, adv.tone_gain, reduction, 1.0)
        else:
            k = max(BASELINE_K, _strength("asinh_k", recipe.tone.strength, adv.asinh_k, reduction, BASELINE_K))
            wk = bg_corrected_for_frame(bg_strength_base * reduction)
            eframe = derive_frame(wk, weight, star_hard, frame.offset, frame.scale, k)
    star_amount = 0.0
    if recipe.star_protection.enabled and tone_stage and star is not None and star.reliable:
        star_amount = _strength("star_protection", recipe.star_protection.strength, adv.star_protection_amount, 1.0, 0.0)
    lc = None
    if recipe.local_contrast.enabled:
        scale_px = adv.local_contrast_scale_px or DEFAULT_SCALE_PX
        key = float(scale_px)
        if key not in band_cache:
            Lw = luminance(np, work)
            raw = lcmod.estimate_band_sigma(Lw, weight, star_hard, scale_px, STAT_FLOOR)
            sky = float(np.median(Lw[weight]))
            slope = _tone_slope_at_sky(mode, sky, gain if recipe.tone.enabled else 1.0, frame if mode == "linear" else None, k if recipe.tone.enabled else BASELINE_K)
            band_cache[key] = max(raw * abs(slope), STAT_FLOOR)
        amount = _strength("local_contrast", recipe.local_contrast.strength, adv.local_contrast_amount, reduction, 0.0)
        lc = LocalContrastParams(amount, scale_px, band_cache[key])
    sat = 1.0
    if recipe.color.enabled and channels == 3:
        sat = _strength("saturation", recipe.color.strength, adv.saturation, reduction, 1.0)
    return Params(
        mode=mode, channels=channels, bg_offsets=bg_offsets, denoise=dn, tone_enabled=recipe.tone.enabled, gain=gain, k=k,
        frame=frame, eframe=eframe, manual=manual, star_amount=star_amount, lc=lc, saturation=sat,
    )


def choose_backend(opts: ExecutionOptions, h: int, w: int, channels: int) -> tuple[str, str]:
    px = h * w
    gpu_ok = opts.gpu_available and not opts.gpu_disabled
    if opts.device == "cpu":
        return "cpu", "CPU selected in settings."
    if opts.device == "gpu":
        return ("gpu", "NVIDIA GPU selected in settings.") if gpu_ok else (
            "cpu", "NVIDIA GPU requested but unavailable; using CPU." if not opts.gpu_disabled else "GPU disabled for the rest of this job after a device failure; using CPU."
        )
    if gpu_ok and px >= opts.gpu_threshold_pixels:
        return "gpu", f"Auto: image has {px / 1e6:.1f} MP (>= {opts.gpu_threshold_pixels / 1e6:.1f} MP crossover)."
    if gpu_ok:
        return "cpu", f"Auto: {px / 1e6:.1f} MP is below the measured GPU crossover; CPU is faster for small images."
    return "cpu", "Auto: no validated GPU available."


def _tile_plan(P: Params, h: int, w: int, budget_bytes: int | None, forced: int | None) -> int:
    """Largest tile edge whose working set (tile + halo) fits the budget; full frame when everything fits."""
    if forced:
        return forced
    full = max(h, w)
    if not budget_bytes:
        return full
    bpp = estimate_memory_per_pixel(P.channels)
    if h * w * bpp <= budget_bytes:
        return full
    halo = P.halo
    edge = int(np.sqrt(budget_bytes / bpp)) - 2 * halo
    return max(256, (edge // 64) * 64)


def _execute(P, exec_in, h, w, channels, mode, opts, backend_name, gpu_disabled, timings, check):
    """Run the contiguous pixel group; classified GPU failures retry once with smaller tiles, then rerun on CPU
    from the clean host inputs (never continuing from partial results)."""
    factory = opts.backend_factory or (lambda name: get_backend(name))
    info: dict[str, Any] = {
        "requested_device": opts.device, "resolved_backend": backend_name, "fallbacks": [], "precision": "float32",
        "stage_group": "background,denoise,tone,star protection,local contrast,color,clip count",
    }
    attempts = [backend_name]
    tile_override: int | None = None
    notes: list[str] = []
    while attempts:
        name = attempts.pop(0)
        be: Backend | None = None
        try:
            budget = opts.ram_budget_bytes
            if name == "gpu":
                be = factory("gpu")
                free = getattr(be, "free_memory", lambda: None)()
                budget = int(free * opts.gpu_memory_fraction) if free else None
                info["gpu_budget_bytes"] = budget
            else:
                be = factory("cpu")
            tile = tile_override or _tile_plan(P, h, w, budget, opts.force_tile)
            info["tile"] = None if tile >= max(h, w) else tile
            outputs = {"y": np.empty(exec_in["x"].shape, dtype=np.float32)}
            if mode == "linear":
                outputs["proc"] = np.empty(exec_in["x"].shape, dtype=np.float32)
                outputs["fixed"] = np.empty(exec_in["x"].shape, dtype=np.float32)
            t0 = time.perf_counter()
            extras = run_tiled(lambda t, inner: _group(be, t, inner, P), exec_in, outputs, tile, P.halo if tile < max(h, w) else 0, check)
            counts = merge_clip_counts(extras)
            be.synchronize()
            elapsed = time.perf_counter() - t0
            timings.items.append({"stage": "pixel group", "backend": name, "seconds": round(elapsed, 4), "tile": info["tile"]})
            info.update(actual_backend=name, device=be.device_label, transfers=be.transfers.as_dict(), notes=notes)
            info["label"] = "Processing: NVIDIA GPU" if name == "gpu" else "Processing: CPU"
            be.release()
            return outputs, counts, name, info, gpu_disabled
        except Cancelled:
            if be:
                be.release()
            raise
        except BackendUnavailable as exc:
            info["fallbacks"].append({"from": name, "cause": "unavailable", "message": str(exc)})
            gpu_disabled = True
            attempts = ["cpu"]
        except Exception as exc:
            classified: RecoverableBackendError | None = be.classify_error(exc) if be else None
            if classified is None:
                raise
            if be:
                be.release()
            info["fallbacks"].append({"from": name, "cause": classified.kind, "message": str(classified)})
            if classified.kind == "oom" and tile_override is None:
                cur = info.get("tile") or max(h, w)
                tile_override = max(64, (cur // 2 // 16) * 16)
                attempts = [name]  # one retry with a validated smaller tile strategy
                notes.append(f"GPU out of memory; retried with {tile_override}px tiles.")
            else:
                gpu_disabled = True
                tile_override = None
                attempts = ["cpu"]
                notes.append(f"GPU stage group rerun on CPU after {classified.kind} failure; GPU disabled for the rest of this job.")
    raise ProcessingError("EXECUTION_FAILED", "Processing could not be completed on any backend.")


def _operation_report(recipe, image, P, bg_status, bg_model, star, tone_stage, manual, channels, mode, backend, reduction, is_noop, regions):
    ops: list[dict[str, Any]] = []
    be_label = "gpu" if backend == "gpu" else "cpu"

    def add(name, requested, status, reason=None, params=None, backend_used=None):
        ops.append({"name": name, "requested": requested, "status": status, "reason": reason, "parameters": params, "backend": backend_used})

    if recipe.background.enabled:
        if bg_model is not None:
            add("background", True, "reduced" if reduction < 1 else "applied", None, {
                **bg_model.to_dict(), "strength": bgmod_strength(recipe, reduction),
                "note": "Constant offsets and (for planar) a shared plane relative to a recorded reference sky level; constant subtracted once.",
            }, be_label)
        else:
            add("background", True, "skipped", bg_status.get("reason"))
    else:
        add("background", False, "off")
    if recipe.denoise.enabled and P.denoise:
        add("denoise", True, "applied", None, P.denoise.to_dict(), be_label)
    else:
        add("denoise", False, "off")
    if tone_stage:
        add("tone", True, "reduced" if reduction < 1 and recipe.tone.enabled else "applied", None, {
            "base": ("rational midtone curve" if mode == "rendered" else "luminance asinh") if recipe.tone.enabled else "baseline (identity / frozen baseline mapping)",
            "gain": P.gain if (recipe.tone.enabled and mode == "rendered") else None,
            "asinh_k": P.k if (recipe.tone.enabled and mode == "linear") else None,
            "enhanced_frame": P.eframe.to_dict() if (P.eframe and recipe.tone.enabled) else None,
            "manual": manual.to_dict(),
        }, be_label)
    else:
        add("tone", False, "off")
    if recipe.star_protection.enabled:
        if not tone_stage:
            add("star_protection", True, "inactive", "The tone stage is disabled, so there is no stretch to protect against.")
        elif star is None or not star.reliable:
            reason = (star.stats.get("reason") if star else None) or "Star detection was unreliable."
            add("star_protection", True, "skipped", f"{reason}. General highlight roll-off still applies.", star.stats if star else None)
        else:
            add("star_protection", True, "applied", None, {"amount": P.star_amount, "accepted_stars": star.stats.get("accepted"), "detection": star.stats}, be_label)
    else:
        add("star_protection", False, "off")
    if recipe.local_contrast.enabled and P.lc:
        add("local_contrast", True, "reduced" if reduction < 1 else "applied", None, {**P.lc.to_dict(), "domain": "display-only"}, be_label)
    else:
        add("local_contrast", False, "off")
    if recipe.color.enabled and channels == 1:
        add("color", True, "skipped", "Monochrome image: color enhancement is not available.")
    elif recipe.color.enabled:
        add("color", True, "reduced" if reduction < 1 else "applied", None, {"saturation": P.saturation, "domain": "display RGB only (never in the processed-linear FITS)"}, be_label)
    else:
        add("color", False, "off")
    if recipe.protect_regions:
        add("protect_regions", True, "applied" if regions else "off", None if regions else "No label regions were confirmed.", {"count": len(regions)} if regions else None)
    if is_noop:
        ops.append({"name": "no_operations", "requested": True, "status": "applied", "reason": "No operations were selected; the decoded display pixels are reproduced unchanged.", "parameters": None, "backend": None})
    return ops


def bgmod_strength(recipe, reduction):
    return _strength("background", recipe.background.strength, recipe.advanced.background_strength, 1.0, 0.0) * reduction


def _summary_note(ops) -> str:
    phrases = {
        ("denoise", "applied"): "Noise reduced",
        ("tone", "applied"): "Midtones brightened",
        ("tone", "reduced"): "Midtones brightened (reduced to limit clipping)",
        ("local_contrast", "applied"): "Local contrast added",
        ("color", "applied"): "Colors enhanced",
        ("background", "applied"): "Background balanced",
        ("star_protection", "applied"): "Stars protected",
    }
    parts = []
    for op in ops:
        if op["name"] == "no_operations":
            parts.append("No operations selected")
        elif op["status"] == "skipped":
            parts.append(f"{op['name'].replace('_', ' ').capitalize()} skipped")
        elif (op["name"], op["status"]) in phrases:
            parts.append(phrases[(op["name"], op["status"])])
    return " · ".join(parts) or "Complete"
