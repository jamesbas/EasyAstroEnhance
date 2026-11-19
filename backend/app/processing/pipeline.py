"""The enhancement pipeline (engine 1.1, one-button Enhance).

1. Analysis (CPU, global, once): masks, low-coverage edges, stars, supervised background model, automatic
   gradient model, per-channel sky, bounded field-star white balance, PSF and per-scale noise.
2. Pixel group A (CPU or GPU, tiled): supervised background -> gradient -> neutralization + white balance
   (linear) -> optional deconvolution -> multiscale denoise. For linear sources the result is the
   processed-linear array (saved before any display-only operation).
3. Analysis 2 (CPU): auto-solve the stretch (linear) or the rendered tone curve, and decide the automatic
   finishing stages (HDR cores, green removal) and per-scale detail noise from the actual display values.
4. Pixel group B (CPU or GPU, tiled): stretch / tone -> gentler star stretch -> HDR -> pop curve -> manual
   tone -> multiscale detail -> RGB reconstruction -> green removal -> gamut -> protected saturation, then
   the clipping guardrail, protected-region restoration and reporting.

Optional AI tools (recipe ``ai``, opt-in, engine 1.2): learned background extraction replaces the polynomial gradient
model; learned denoising replaces the wavelet denoise (after group A); learned star separation lets group B finish the
starless image and add the stars back with the brightness the stretch gives them (blended toward the gentler star stretch). Each is skipped with a reason (and the
classical step runs) when its model is missing or cannot run.

No module here touches HTTP, the database or the UI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import background as bgmod
from . import finishing as fin
from . import linear_prep as lp
from .ai import registry as ai_registry
from .ai.runtime import Runner
from .ai.tools import AIStepInfo, ai_background, ai_denoise, separate_stars, timed
from .backends import Backend, BackendUnavailable, RecoverableBackendError, get_backend
from .backends.base import kernel_radius
from .catalog_color import catalog_balance
from .color import gamut_fit, luminance, reconstruct_rgb
from .deconv import DEFAULT_ITERATIONS, DeconvParams, deconvolve, estimate_psf_sigma
from .denoise import DenoiseParams, denoise, denoise_params, estimate_noise, estimate_wavelet_noise
from .diagnostics import clip_report, merge_clip_counts
from .imagedata import Cancelled, ImageData, ProcessingError
from .masks import masked_gaussian, region_summary, regions_mask, validate_regions
from .object_color import hubble_input, hubble_style, selective_color
from .recipe import (
    BACKGROUND_STRENGTH, PIPELINE_VERSION, POP_PER_CONTRAST, RENDERED_BASE_GAIN, SATURATION_PER_COLOR,
    STRETCH_DECADES_PER_UNIT, ObjectColorRecipe, Recipe,
)
from .report import dependency_versions
from .star_protection import StarMask, detect_stars
from .stretch import (
    LinearFrame, StretchParams, apply_stretch, derive_frame, derive_normalization, fixed_map, from_normalized, mtf,
    rendered_sky_balance, solve_focus, solve_stretch, stretch_statistics, to_normalized,
)
from .tiling import run_tiled
from .tone import ManualTone, apply_manual, rational_gain, smoothstep, validate_monotonic

CLIP_THRESHOLD_BLACK = 0.001
CLIP_THRESHOLD_WHITE = 0.001
STAT_FLOOR = 1e-6
BYTES_PER_PIXEL_PER_CHANNEL = 96  # conservative live-buffer estimate for a pixel group (wavelet temporaries included)
HALO_SIGMA = 6.0
STAR_EXCESS_SCALE = 0.08  # rendered path: display-luminance excess over the star-free surroundings at full protection
DEFAULT_STAR_STRETCH = 0.5
DEFAULT_HDR_AMOUNT = 0.5
DEFAULT_SCNR_AMOUNT = 1.0
DEFAULT_GRADIENT_DEGREE = 2
COLD_SIGMAS = 8.0


@dataclass
class AssetContext:
    """Per-asset data (never taken from a preset): protected regions, background confirmation, frozen frame."""

    regions: list[dict[str, Any]] = field(default_factory=list)
    background: dict[str, Any] | None = None
    frame: dict[str, Any] | None = None
    dualband_confirmed: bool = False


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
    ai_models_dir: Path | None = None
    color_catalog_dir: Path | None = None


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


# ====================================================================================================== params
@dataclass
class GroupA:
    mode: str
    channels: int
    bg_offsets: np.ndarray | None = None
    use_plane: bool = False
    use_gradient: bool = False
    sky: np.ndarray | None = None  # per-channel level subtracted by neutralization
    gains: np.ndarray | None = None  # white-balance gains (linear RGB)
    pedestal: float = 0.0
    rendered_offsets: np.ndarray | None = None
    deconv: DeconvParams | None = None
    denoise: DenoiseParams | None = None

    @property
    def needed(self) -> bool:
        return any(v is not None for v in (self.bg_offsets, self.sky, self.rendered_offsets, self.deconv, self.denoise)) or self.use_gradient or self.use_plane

    @property
    def halo(self) -> int:
        h = 0
        if self.denoise:
            h = max(h, self.denoise.halo)
        if self.deconv:
            h = max(h, self.deconv.halo)
        return h


@dataclass
class GroupB:
    mode: str
    channels: int
    frame: LinearFrame | None
    tone_enabled: bool
    sp: StretchParams | None = None
    sp_star: StretchParams | None = None
    star_amount: float = 0.0  # linear: gentler star stretch blend; rendered: brightening protection
    rend_gain: float = 1.0
    rend_m: float | None = None
    manual: ManualTone = field(default_factory=ManualTone)
    hdr_amount: float = 0.0
    pop_a: float = 0.0
    sky_disp: float = 0.0
    sky_sd: float = 0.0
    detail: fin.DetailParams | None = None
    scnr_amount: float = 0.0
    saturation: float = 1.0
    object_color: ObjectColorRecipe | None = None
    object_scale: float = 1.0
    hubble_strength: float = 0.0
    hubble_sky: tuple[float, ...] = (0.0, 0.0, 0.0)
    hubble_sigma: float = 0.0
    separated: bool = False  # AI star separation: x is the starless image, "full" the image with stars
    star_brightness: float = 1.0

    @property
    def tail_needed(self) -> bool:
        return bool(
            self.tone_enabled or not self.manual.neutral or self.detail is not None or self.saturation > 1.0
            or self.hdr_amount > 0 or self.pop_a > 0 or self.scnr_amount > 0 or self.star_amount > 0
            or self.object_color is not None or self.hubble_strength > 0
        )

    @property
    def halo(self) -> int:
        h = kernel_radius(HALO_SIGMA) + 2
        if self.detail:
            h = max(h, self.detail.halo)
        if self.hdr_amount > 0:
            h = max(h, fin.halo(0, True))
        if self.mode == "rendered" and self.star_amount > 0:
            h = max(h, 2 * kernel_radius(HALO_SIGMA) + 2)
        return h


# ====================================================================================================== helpers
def baseline_display(image: ImageData, frame: LinearFrame | None) -> np.ndarray:
    """Original display values: decoded pixels (rendered) or the frozen linked autostretch (linear)."""
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
    return derive_frame(u, weight, offset, scale)


def estimate_memory_per_pixel(channels: int) -> int:
    return BYTES_PER_PIXEL_PER_CHANNEL * max(1, channels)


# Measured peak working-set per channel-pixel for the whole run on the target PC (tools/benchmark.py), rounded up.
# Used for the up-front memory check, not a promise.
PEAK_RAM_BYTES_PER_CHANNEL_PIXEL = {"rendered": 80, "linear": 160}


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


def _lum_stretch(xp, x):
    from .stretch import stretch_luminance

    return stretch_luminance(xp, x)


# ====================================================================================================== pixel groups
def _group_a(be: Backend, tile_in: dict[str, np.ndarray], inner: tuple[int, int, int, int], P: GroupA):
    xp = be.xp
    iy0, iy1, ix0, ix1 = inner
    x = be.asarray(tile_in["x"])
    w = be.asarray(tile_in["w"])
    star = be.asarray(tile_in["star"])
    rgb = x.ndim == 3
    if P.bg_offsets is not None:
        x = x - xp.asarray(P.bg_offsets)
    if P.use_plane:
        pl = be.asarray(tile_in["plane"])
        x = x - (pl[..., None] if rgb else pl)
    if P.use_gradient:
        x = x - be.asarray(tile_in["grad"])
    if P.sky is not None:
        x = x - xp.asarray(P.sky)
        if P.gains is not None:
            x = x * xp.asarray(P.gains)
        x = x + P.pedestal
    if P.rendered_offsets is not None:
        x = x - xp.asarray(P.rendered_offsets)
    if P.deconv is not None:
        x = deconvolve(be, x, w, star, _lum_stretch, P.deconv)
    if P.denoise is not None:
        x = denoise(be, x, w, star, P.denoise)
    sl = (slice(iy0, iy1), slice(ix0, ix1))
    out = {"proc": be.asnumpy(x[sl]).astype(np.float32, copy=False)}
    be.synchronize()
    return out, None


def _group_b(be: Backend, tile_in: dict[str, np.ndarray], inner: tuple[int, int, int, int], P: GroupB):
    xp = be.xp
    iy0, iy1, ix0, ix1 = inner
    x = be.asarray(tile_in["x"])
    w = be.asarray(tile_in["w"])
    star = be.asarray(tile_in["star"])
    src = be.asarray(tile_in["src"])
    rgb = x.ndim == 3
    fixed = None
    stars_disp = None

    if P.mode == "linear":
        full = be.asarray(tile_in["full"]) if P.separated else x
        fixed = fixed_map(xp, full, P.frame)[0]
        if P.tone_enabled:
            y = apply_stretch(xp, x, P.sp)
            if P.separated:  # the display brightness the stars add, blended toward the gentler star stretch
                d = apply_stretch(xp, full, P.sp) - y
                if P.sp_star is not None and P.star_amount > 0:
                    d = (1.0 - P.star_amount) * d + P.star_amount * (apply_stretch(xp, full, P.sp_star) - apply_stretch(xp, x, P.sp_star))
                stars_disp = xp.clip(d, 0.0, 1.0)
            elif P.sp_star is not None and P.star_amount > 0:
                y = fin.star_blend(xp, y, apply_stretch(xp, x, P.sp_star), star, P.star_amount)
        elif P.separated:
            y = fixed_map(xp, x, P.frame)[0]
            stars_disp = xp.clip(fixed - y, 0.0, 1.0)
        else:
            y = fixed
        rgb0 = y
        L0 = luminance(xp, y)
        Lb = L0
    else:
        rgb0 = x
        L0 = luminance(xp, x)
        Lb = L0
        if P.tone_enabled:
            Lb = rational_gain(xp, L0, P.rend_gain)
            if P.rend_m is not None:
                Lb = mtf(xp, P.rend_m, xp.clip(Lb, 0.0, 1.0))
            if P.star_amount > 0:
                # Protect only where a compact star is genuinely brighter than its star-free surroundings, so the
                # sky ring around a star keeps its normal stretch (no dark rings, no abrupt mask edges).
                delta = Lb - L0
                w_nostar = w * (1.0 - xp.clip(star * 2.0, 0.0, 1.0))
                excess = L0 - masked_gaussian(be, L0, w_nostar, HALO_SIGMA)
                prot = star * smoothstep(xp, excess / STAR_EXCESS_SCALE)
                Lb = L0 + xp.where(delta > 0, delta * (1.0 - P.star_amount * prot), delta)

    if P.tail_needed:
        Lp = Lb
        if P.hdr_amount > 0:
            w_nostar = w * (1.0 - xp.clip(star * 2.0, 0.0, 1.0))
            Lp = fin.hdr_compress(be, Lp, w_nostar, P.hdr_amount)
        if P.pop_a > 0:
            Lp = fin.pop_curve(xp, Lp, P.sky_disp, P.pop_a)
        Lp = apply_manual(xp, Lp, P.manual)
        if P.detail is not None:
            Lp = Lp + fin.detail_boost(be, Lp, w, fin.star_halo_mask(be, star), P.detail)
        y = reconstruct_rgb(xp, rgb0, L0, Lp)
        if rgb:
            if P.scnr_amount > 0:
                y = fin.scnr(xp, y, P.scnr_amount)
            y = gamut_fit(xp, y)
            y = fin.protected_saturate(xp, y, P.saturation, P.sky_disp, P.sky_sd)
            if P.object_color is not None:
                y, _ = selective_color(xp, y, star, w, P.sky_disp, P.sky_sd, P.object_color, P.object_scale)
            if P.hubble_strength > 0:
                y, _ = hubble_style(xp, y, x, star, w, P.hubble_sky, P.hubble_sigma, P.hubble_strength * P.object_scale)
    else:
        y = rgb0
    if stars_disp is not None:  # stars added back over the finished starless image
        if P.star_brightness < 1.0:
            stars_disp *= P.star_brightness
        y = xp.clip(y + stars_disp, 0.0, 1.0)

    sl = (slice(iy0, iy1), slice(ix0, ix1))
    eligible = w[sl] > 0
    counts = clip_report(src[sl], y[sl], eligible, xp=xp)
    out: dict[str, np.ndarray] = {"y": be.asnumpy(xp.clip(y[sl], 0.0, 1.0)).astype(np.float32, copy=False)}
    if fixed is not None:
        out["fixed"] = be.asnumpy(xp.clip(fixed[sl], 0.0, 1.0)).astype(np.float32, copy=False)
    be.synchronize()
    return out, counts


# ====================================================================================================== main
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
    rgb = channels == 3
    mode = "linear" if image.domain == "linear" else "rendered"
    look, auto, adv = recipe.look, recipe.auto, recipe.advanced
    notes: list[str] = list(image.notes)
    decisions: dict[str, Any] = {}

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
        frame = LinearFrame.from_dict(ctx.frame)
        if frame is None:
            frame = prepare_linear_frame(image)
        work = to_normalized(image.pixels, frame.offset, frame.scale)
    else:
        work = image.pixels.astype(np.float32, copy=False)
    baseline = baseline_display(image, frame)

    manual = ManualTone(recipe.tone.brightness_ev, recipe.tone.shadows, recipe.tone.highlights, recipe.tone.black_point)
    validate_monotonic(manual)
    tone_stage = recipe.tone.enabled or not manual.neutral
    palette = image.header.get("EAEMIX") if image.header is not None else None
    narrowband = palette in ("HOO", "SHO", "DUAL-SHO", "HA-RGB")
    filter_kind = hubble_input(image.header, ctx.dualband_confirmed) if recipe.hubble_strength or recipe.catalog_sha256 else None
    hubble_ready = bool(filter_kind == "dualband" and mode == "linear" and rgb and image.source_format == "fits")
    catalog_eligible = not narrowband and filter_kind not in ("dualband", "unsupported")
    color_ops = rgb and (look.color > 0 or auto.green_removal or recipe.object_color.active
                         or hubble_ready
                         or ((auto.white_balance or recipe.catalog_sha256) and mode == "linear"))
    is_noop = not (
        tone_stage or look.noise > 0 or look.contrast > 0 or look.detail > 0 or color_ops or recipe.background.enabled
        or auto.neutralize or (auto.gradient and mode == "linear") or adv.deconvolution
        or (look.protect_cores and recipe.tone.enabled) or recipe.ai.background or recipe.ai.denoise or recipe.ai.stars
    )

    # ---------------------------------------------------------------- analysis (CPU, global, once)
    edges = np.zeros((h, w), bool)
    edge_info: dict[str, Any] = {"fraction": 0.0, "method": "not measured"}
    if mode == "linear" and not is_noop:
        edges, edge_info = timings.run("edge mask", "cpu", lambda: lp.edge_mask(work, weight))
    stat_w = weight & ~edges
    if not stat_w.any():
        stat_w = weight

    star: StarMask | None = None
    need_star = not is_noop and (look.noise > 0 or look.detail > 0 or auto.star_stretch or auto.white_balance
                                or adv.deconvolution or auto.gradient or recipe.object_color.active or recipe.catalog_sha256
                                or hubble_ready)
    if need_star:
        progress("Finding stars")
        star = timings.run("star detection", "cpu", lambda: detect_stars(work, stat_w, STAT_FLOOR), note="global connected components")
    star_hard = star.hard if star and star.reliable else None
    star_soft = star.soft if star and star.reliable else None

    noise_report: dict[str, float] = {}
    if not is_noop:
        noise_report = timings.run("noise estimate", "cpu", lambda: estimate_noise(work, stat_w, star_hard, STAT_FLOOR))

    # supervised background model
    bg_model: bgmod.BgModel | None = None
    bg_status: dict[str, Any] = {"name": "background", "requested": recipe.background.enabled}
    if recipe.background.enabled:
        progress("Checking background samples")
        conf = ctx.background
        if not conf or not conf.get("confirmed") or not conf.get("samples"):
            bg_status.update(status="skipped", reason="No confirmed sky regions for this image yet (background balancing is pending).")
        elif conf.get("method") != recipe.background.method:
            bg_status.update(status="skipped", reason=f"Confirmed sky regions are for the '{conf.get('method')}' model, not '{recipe.background.method}'; confirm the new model first.")
        else:
            sigma_pix = noise_report.get("sigma_white_equivalent") or estimate_noise(work, weight, star_hard, STAT_FLOOR)["sigma_white_equivalent"]
            model = timings.run(
                "background model", "cpu",
                lambda: bgmod.build_model(work, weight, star_hard, conf["samples"], recipe.background.method, sigma_pix, protected),
            )
            if not model.ok:
                msgs = "; ".join(i.message for i in model.issues if i.level == "error")
                bg_status.update(status="skipped", reason=f"The confirmed sky regions did not validate on this run: {msgs}")
            else:
                bg_model = model
    bg_strength = (BACKGROUND_STRENGTH[recipe.background.strength] if adv.background_strength is None else adv.background_strength)

    A = GroupA(mode=mode, channels=channels)
    base = work
    if bg_model is not None:
        A.bg_offsets = bgmod.channel_offset_vector(bg_model, bg_strength)
        base = work - A.bg_offsets
        pm = bgmod.plane_map(bg_model, h, w) if bg_model.method == "planar" else None
        if pm is not None:
            A.use_plane = True
            plane = (pm * bg_strength).astype(np.float32)
            base = base - (plane[..., None] if rgb else plane)

    # optional AI background extraction (replaces the polynomial gradient model)
    ai: dict[str, dict[str, Any]] = {}
    grad_map: np.ndarray | None = None
    if recipe.ai.background and not is_noop:
        if mode != "linear":
            ai["ai_background"] = {"status": "inactive", "reason": "AI background extraction runs on linear stacks only; this image is already processed."}
        elif bg_model is not None:
            ai["ai_background"] = {"status": "skipped", "reason": "A confirmed manual background correction is used for this image."}
        else:
            res = _run_ai(opts, "background", rgb, progress, "Removing background (AI)", lambda run: ai_background(base, stat_w, run))
            if res["status"] == "applied":
                grad_map = res.pop("result")
                base = base - grad_map
                A.use_gradient = True
            ai["ai_background"] = res
    ai_bg_applied = (ai.get("ai_background") or {}).get("status") == "applied"

    # automatic gradient (linear)
    grad_model: lp.GradientModel | None = None
    grad_status: dict[str, Any] = {"status": "off", "reason": None}
    if ai_bg_applied:
        grad_status = {"status": "inactive", "reason": "Replaced by AI background extraction."}
    elif mode == "linear" and auto.gradient and not is_noop:
        if bg_model is not None:
            grad_status = {"status": "skipped", "reason": "A confirmed manual background correction is used for this image."}
        else:
            progress("Modelling gradients")
            pre_sky = lp.sky_stats(base, stat_w)
            sig_pix = float(np.mean(pre_sky.sigma))
            grad_model = timings.run(
                "gradient model", "cpu",
                lambda: lp.fit_gradient(base, stat_w, star_hard, adv.gradient_degree or DEFAULT_GRADIENT_DEGREE, sig_pix),
            )
            if grad_model.ok:
                grad_map = lp.gradient_map(grad_model, h, w)
                base = base - grad_map
                A.use_gradient = True
                grad_status = {"status": "applied", "reason": None}
            else:
                grad_status = {"status": "skipped", "reason": grad_model.reason}
    elif auto.gradient and mode == "rendered" and not is_noop:
        grad_status = {"status": "inactive", "reason": "Automatic gradient removal runs on linear stacks only; this image is already processed."}

    # neutralization and white balance
    sky = lp.sky_stats(base, stat_w) if not is_noop else None
    neutral_status: dict[str, Any] = {"status": "off", "reason": None}
    wb = lp.WhiteBalance(False, reason=None)
    wb_status: dict[str, Any] = {"status": "off", "reason": None}
    catalog = {"status": "off", "reason": None}
    if recipe.catalog_sha256:
        catalog = {"status": "skipped", "sha256": recipe.catalog_sha256,
                   "reason": ("Catalog calibration is for broadband; preserving the chosen filter mix." if not catalog_eligible else
                              "Catalog calibration requires a linear broadband RGB FITS and background neutralization.")}
    prepped = base
    if auto.neutralize and sky is not None:
        if mode == "linear":
            A.sky = np.array(sky.level, dtype=np.float32)
            A.pedestal = float(lp.PEDESTAL_SIGMAS * max(sky.sigma))
            neutral_status = {"status": "applied", "reason": None}
            if rgb and not narrowband and (auto.white_balance or recipe.catalog_sha256):
                progress("Balancing color")
                saturated = (work >= lp.SATURATION_LEVEL).any(axis=2)
                sig_l = float(np.mean(sky.sigma)) / np.sqrt(3.0)
                if recipe.catalog_sha256 and catalog_eligible:
                    catalog = timings.run(
                        "catalog color", "cpu",
                        lambda: catalog_balance(image, base - A.sky, star_hard, saturated, stat_w, sig_l,
                                                opts.color_catalog_dir, recipe.catalog_sha256),
                    )
                if catalog["status"] == "applied":
                    A.gains = np.asarray(catalog["gains_rgb"], dtype=np.float32)
                    wb_status = {"status": "inactive", "reason": "Replaced by offline catalog calibration."}
            if rgb and not narrowband and auto.white_balance and catalog["status"] != "applied":
                wb = timings.run(
                    "white balance", "cpu",
                    lambda: lp.star_white_balance(base - A.sky, star_hard, saturated, sig_l, adv.white_balance_limit or lp.WB_DEFAULT_LIMIT),
                )
                if wb.ok:
                    A.gains = np.array(wb.factors, dtype=np.float32)
                    wb_status = {"status": "applied", "reason": None}
                else:
                    wb_status = {"status": "skipped", "reason": wb.reason}
            prepped = (base - A.sky) * (A.gains if A.gains is not None else 1.0) + A.pedestal
        elif rgb:
            mean_sky = float(np.mean(sky.level))
            A.rendered_offsets = np.array([lv - mean_sky for lv in sky.level], dtype=np.float32)
            prepped = base - A.rendered_offsets
            neutral_status = {"status": "applied", "reason": None}
        else:
            neutral_status = {"status": "skipped", "reason": "Monochrome image: there is no color cast to neutralize."}
    if rgb and auto.white_balance and mode == "linear" and wb_status["status"] == "off" and not is_noop:
        wb_status = {"status": "skipped", "reason": "Preserving the selected narrowband palette." if narrowband else
                     "White balance needs background neutralization, which is switched off."}
    elif rgb and auto.white_balance and mode == "rendered" and not is_noop:
        wb_status = {"status": "inactive", "reason": "Star-based white balance runs on linear stacks only; this image is already processed."}

    # deconvolution (opt-in)
    protect_a: np.ndarray | None = None
    deconv_status: dict[str, Any] = {"status": "off", "reason": None}
    if adv.deconvolution:
        if mode != "linear":
            deconv_status = {"status": "skipped", "reason": "Deconvolution runs on linear stacks only."}
        else:
            Lp_ = _lum_stretch(np, prepped)
            saturated = (work >= lp.SATURATION_LEVEL).any(axis=2) if rgb else work >= lp.SATURATION_LEVEL
            sig_psf, n_psf = estimate_psf_sigma(Lp_, star_hard, saturated)
            if sig_psf is None:
                deconv_status = {"status": "skipped", "reason": f"Not enough isolated, unsaturated stars to measure the blur ({n_psf} found)."}
            else:
                sky_l, sig_l = lp.clipped_stats(Lp_[stat_w])
                A.deconv = DeconvParams(sig_psf, adv.deconvolution_iterations or DEFAULT_ITERATIONS, sky_l, max(sig_l, STAT_FLOOR), n_psf)
                deconv_status = {"status": "applied", "reason": None}

    # multiscale denoise
    if look.noise > 0:
        progress("Measuring noise")
        n_lum = adv.denoise_scales or 4
        wn = timings.run("wavelet noise", "cpu", lambda: estimate_wavelet_noise(prepped, stat_w, star_hard, n_lum, min(6, n_lum + 1), STAT_FLOOR))
        A.denoise = denoise_params(look.noise, n_lum, wn)
        # Isolated dark defects (cold pixels, stacking holes) are left alone like stars: shrinking the small
        # coefficients around them would spread them into dark blobs.
        Lw = luminance(np, prepped)
        sky_l, sig_l = lp.clipped_stats(Lw[stat_w])
        cold = (Lw < sky_l - COLD_SIGMAS * max(sig_l, STAT_FLOOR)) & weight
        if cold.any():
            from scipy import ndimage as _nd

            cold_soft = _nd.binary_dilation(cold, iterations=2).astype(np.float32)
            protect_a = cold_soft if star_soft is None else np.maximum(star_soft, cold_soft)
            decisions["denoise_defects_protected_px"] = int(cold.sum())

    classical_dn: DenoiseParams | None = None
    if recipe.ai.denoise and not is_noop:
        if look.noise <= 0:
            ai["ai_denoise"] = {"status": "skipped", "reason": "Noise reduction is set to 0, so there is nothing for the AI to remove."}
        else:
            spec, path, reason = _ai_model(opts, "denoise", rgb)
            if path is None:
                ai["ai_denoise"] = {"status": "skipped", "reason": reason}
            else:
                classical_dn, A.denoise = A.denoise, None  # kept as the fallback if the model cannot run
                ai["ai_denoise"] = {"status": "pending"}

    # ---------------------------------------------------------------- pixel group A
    backend_name, backend_reason = choose_backend(opts, h, w, channels)
    gpu_disabled = opts.gpu_disabled
    exec_info: dict[str, Any] = {}
    zeros = np.zeros((h, w), dtype=np.float32)
    star_in = star_soft if star_soft is not None else zeros
    if A.needed:
        progress("Cleaning linear data" if mode == "linear" else "Reducing noise")
        exec_a = {"x": work, "w": weight.astype(np.float32), "star": protect_a if protect_a is not None else star_in}
        if A.use_plane:
            exec_a["plane"] = (bgmod.plane_map(bg_model, h, w) * bg_strength).astype(np.float32)
        if A.use_gradient:
            exec_a["grad"] = grad_map
        out_a, _, backend_name, exec_info, gpu_disabled = _execute(
            lambda be, t, inner: _group_a(be, t, inner, A), exec_a, ["proc"], A.halo, h, w, channels, opts, backend_name, gpu_disabled,
            timings, check, "pixel group A",
        )
        proc = out_a["proc"]
    else:
        proc = work.astype(np.float32, copy=False)
    del grad_map
    proc_changed = A.needed

    # ---------------------------------------------------------------- optional AI denoise and star separation
    sig_before_ai: float | None = None
    if (ai.get("ai_denoise") or {}).get("status") == "pending":
        if mode == "linear" and recipe.tone.enabled:
            sig_before_ai = stretch_statistics(proc, stat_w, star_hard)[1]
        res = _run_ai(opts, "denoise", rgb, progress, "Reducing noise (AI)", lambda run: ai_denoise(proc, weight, look.noise, run, check, _percent(progress, "Reducing noise (AI)")))
        if res["status"] == "applied":
            proc = res.pop("result")
            proc_changed = True
        elif classical_dn is not None:  # the model could not run: classical wavelet denoise instead
            A2 = GroupA(mode=mode, channels=channels, denoise=classical_dn)
            out_a2, _, backend_name, info_a2, gpu_disabled = _execute(
                lambda be, t, inner: _group_a(be, t, inner, A2), {"x": proc, "w": weight.astype(np.float32), "star": protect_a if protect_a is not None else star_in},
                ["proc"], A2.halo, h, w, channels, opts, backend_name, gpu_disabled, timings, check, "denoise (fallback)",
            )
            exec_info = _merge_exec(exec_info, info_a2)
            proc, A.denoise, proc_changed = out_a2["proc"], classical_dn, True
        ai["ai_denoise"] = res
    disp_src = proc
    if recipe.ai.stars and not is_noop:
        if mode != "linear":
            ai["ai_stars"] = {"status": "inactive", "reason": "AI star separation runs on linear stacks only; this image is already processed."}
        else:
            def _sep(run):
                t = run.input_shape[2]
                starless, _stars, params = separate_stars(proc, weight, run, t if isinstance(t, int) else 256, check, _percent(progress, "Separating stars (AI)"))
                return starless, params

            res = _run_ai(opts, "stars", rgb, progress, "Separating stars (AI)", _sep, nchw=True)
            if res["status"] == "applied":
                disp_src = res.pop("result")
            ai["ai_stars"] = res
    stars_sep = disp_src is not proc

    # ---------------------------------------------------------------- analysis 2: display decisions (CPU)
    progress("Choosing the stretch")
    sp: StretchParams | None = None
    B = GroupB(mode=mode, channels=channels, frame=frame, tone_enabled=recipe.tone.enabled, manual=manual,
               star_brightness=recipe.ai.star_brightness)
    focus = recipe.focus_stretch
    focus_active = focus.enabled and mode == "linear" and recipe.tone.enabled
    y0: np.ndarray
    if mode == "linear":
        if recipe.tone.enabled:
            sky_l, sig_l, hi_l = stretch_statistics(disp_src, stat_w, star_hard)
            if sig_before_ai is not None and (ai.get("ai_denoise") or {}).get("status") == "applied":
                # AI denoising flattens the sky far more than its true noise drops; the stretch solver would read that as
                # "almost no noise" and stretch until residual mottle and color are amplified. The stretch therefore
                # treats AI-denoised data as at most AI_STRETCH_NOISE_RATIO cleaner than before (about what full-strength
                # wavelet denoise measures): the result is cleaner at a comparable stretch.
                sig_floor = AI_STRETCH_NOISE_RATIO * sig_before_ai
                decisions["stretch_noise_floor"] = {"measured_sigma": sig_l, "sigma_before_ai_denoise": sig_before_ai, "ratio": AI_STRETCH_NOISE_RATIO,
                                                    "used": max(sig_l, sig_floor)}
                sig_l = max(sig_l, sig_floor)
            white = _white_level(proc, A, rgb)
            if focus_active:
                sp = solve_focus(sky_l, sig_l, hi_l, white, look.background, focus.strength, focus.focus,
                                 focus.protect_shadows, focus.protect_highlights)
            else:
                sp = solve_stretch(
                    sky_l, sig_l, hi_l, white, look.background, protect_cores=look.protect_cores, amount=look.stretch,
                    log_d=adv.stretch_log_d, b=adv.stretch_b, p=adv.highlight_convergence, decades_per_unit=STRETCH_DECADES_PER_UNIT,
                )
            B.sp = sp
            y0 = timings.run("display preview", "cpu", lambda: apply_stretch(np, disp_src, sp))
            B.sky_disp, B.sky_sd = sp.target, sp.sky_display_sigma
            if auto.star_stretch and star_soft is not None:
                B.sp_star = sp.gentler()
                B.star_amount = adv.star_stretch_amount if adv.star_stretch_amount is not None else DEFAULT_STAR_STRETCH
            if stars_sep:
                B.separated = True
                B.sp_star = sp.gentler() if auto.star_stretch else None
                B.star_amount = (adv.star_stretch_amount if adv.star_stretch_amount is not None else DEFAULT_STAR_STRETCH) if auto.star_stretch else 0.0
        else:
            B.separated = stars_sep
            y0 = fixed_map(np, disp_src, frame)[0]
            Ys = luminance(np, y0)
            B.sky_disp, B.sky_sd = lp.clipped_stats(Ys[stat_w])
    else:
        L0 = luminance(np, proc)
        Lb = L0
        if recipe.tone.enabled:
            B.rend_gain = adv.tone_gain if adv.tone_gain is not None else RENDERED_BASE_GAIN * float(2.0 ** (0.5 * look.stretch))
            Lg = rational_gain(np, L0, B.rend_gain)
            sky_g, _ = lp.clipped_stats(Lg[stat_w])
            B.rend_m, goal = rendered_sky_balance(sky_g, look.background)
            decisions["rendered_tone"] = {"gain": B.rend_gain, "sky_after_gain": sky_g, "sky_goal": goal, "mtf_m": B.rend_m,
                                          "note": "sky goal limited to 0.6x..1.6x of the rendered sky"}
            Lb = mtf(np, B.rend_m, np.clip(Lg, 0.0, 1.0))
            if auto.star_stretch and star_soft is not None:
                B.star_amount = adv.star_stretch_amount if adv.star_stretch_amount is not None else DEFAULT_STAR_STRETCH
        y0 = reconstruct_rgb(np, proc, L0, Lb) if rgb else Lb
        B.sky_disp, B.sky_sd = lp.clipped_stats(luminance(np, y0)[stat_w])
    Y0 = luminance(np, y0)
    use_ns = stat_w & ~star_hard if star_hard is not None else stat_w

    hdr_status: dict[str, Any] = {"status": "off", "reason": None}
    if look.protect_cores and recipe.tone.enabled:
        found, info = fin.detect_bright_core(Y0, use_ns)
        decisions["bright_core"] = info
        if found:
            B.hdr_amount = adv.hdr_amount if adv.hdr_amount is not None else DEFAULT_HDR_AMOUNT
            hdr_status = {"status": "applied", "reason": None}
        else:
            hdr_status = {"status": "skipped", "reason": "No bright extended core was found, so core compression is not needed."}
    scnr_status: dict[str, Any] = {"status": "off", "reason": None}
    if narrowband and auto.green_removal:
        scnr_status = {"status": "skipped", "reason": "Preserving the selected narrowband palette."}
    elif rgb and auto.green_removal and not is_noop:
        excess = fin.green_excess(y0, use_ns, B.sky_disp, B.sky_sd)
        decisions["green_excess"] = excess
        if excess > fin.SCNR_DETECT_EXCESS:
            B.scnr_amount = adv.scnr_amount if adv.scnr_amount is not None else DEFAULT_SCNR_AMOUNT
            scnr_status = {"status": "applied", "reason": None}
        else:
            scnr_status = {"status": "skipped", "reason": f"No green cast remained after color balance (excess {excess:.4f})."}
    if look.detail > 0:
        n_d = fin.scales_for(adv.detail_scale_px)
        dn = timings.run("detail noise", "cpu", lambda: estimate_wavelet_noise(Y0, stat_w, star_hard, n_d, n_d, STAT_FLOOR))
        B.detail = fin.DetailParams(look.detail, n_d, dn.lum)
    B.pop_a = POP_PER_CONTRAST * look.contrast
    B.saturation = 1.0 + SATURATION_PER_COLOR * look.color if rgb else 1.0
    if rgb and recipe.object_color.active and (star_soft is not None or stars_sep):
        B.object_color = recipe.object_color
    if hubble_ready and (star_soft is not None or stars_sep):
        palette_stats = lp.sky_stats(disp_src, use_ns if use_ns.any() else stat_w)
        B.hubble_strength = recipe.hubble_strength
        B.hubble_sky = tuple(palette_stats.level)
        B.hubble_sigma = max(palette_stats.sigma)
    del y0, Y0

    # ---------------------------------------------------------------- pixel group B with clipping guardrail
    reduction = 1.0
    attempt = 0
    first_counts = None
    guard_action = "none"
    needs_review = False
    base_vals = {"pop_a": B.pop_a, "saturation": B.saturation, "hdr": B.hdr_amount, "detail": B.detail, "gain": B.rend_gain}
    while True:
        attempt += 1
        B.pop_a = base_vals["pop_a"] * reduction
        B.saturation = 1.0 + (base_vals["saturation"] - 1.0) * reduction
        B.object_scale = reduction
        B.hdr_amount = base_vals["hdr"] * reduction
        B.rend_gain = 1.0 + (base_vals["gain"] - 1.0) * reduction
        if base_vals["detail"] is not None:
            d0 = base_vals["detail"]
            B.detail = fin.DetailParams(d0.amount * reduction, d0.n_scales, d0.sigmas)
        progress("Enhancing")
        exec_b = {"x": disp_src, "w": weight.astype(np.float32), "star": star_in, "src": baseline}
        if B.separated:
            exec_b["full"] = proc
        keys = ["y", "fixed"] if mode == "linear" else ["y"]
        outputs, counts, backend_name, info_b, gpu_disabled = _execute(
            lambda be, t, inner: _group_b(be, t, inner, B), exec_b, keys, B.halo, h, w, channels, opts, backend_name, gpu_disabled,
            timings, check, "pixel group B",
        )
        exec_info = _merge_exec(exec_info, info_b)
        if first_counts is None:
            first_counts = counts
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
    exec_info["backend_reason"] = backend_reason

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
        if proc_changed:
            processed = from_normalized(proc, frame.offset, frame.scale, image.pixels.dtype)
            if prot.any():
                processed[prot] = image.pixels[prot]
        else:
            processed = image.pixels

    # ---------------------------------------------------------------- report
    ctx_r = _ReportCtx(recipe, image, mode, rgb, A, B, sp, star, bg_status, bg_model, bg_strength, grad_status, grad_model, neutral_status,
                       sky, wb, wb_status, deconv_status, hdr_status, scnr_status, reduction, is_noop, regions, backend_name, tone_stage, ai)
    learned = [k for k, v in ai.items() if v.get("status") == "applied"]
    ops = _operation_report(ctx_r)
    if recipe.catalog_sha256:
        ops.append({"name": "catalog_color", "requested": True, **catalog,
                    "fallback": wb_status["status"] if catalog["status"] != "applied" else None})
    if focus.enabled:
        ops.append({"name": "focus_stretch", "requested": True, "status": "applied" if focus_active else "skipped",
                    "reason": None if focus_active else "Focused stretch requires a linear image with Stretch enabled.",
                    "parameters": focus.model_dump()})
    if recipe.object_color.active:
        ops.append({"name": "object_color", "requested": True,
                    "status": ("reduced" if reduction < 1 else "applied") if B.object_color else "skipped",
                    "reason": None if B.object_color else ("Monochrome image." if not rgb else "No reliable star mask for protecting stars."),
                    "parameters": {**recipe.object_color.model_dump(), "strength_multiplier": reduction, "domain": "display RGB"}})
    if recipe.hubble_strength > 0:
        reason = None
        if not hubble_ready:
            reason = ("Broadband input such as IR-cut cannot use the H-alpha/OIII palette." if filter_kind == "broadband" else
                      "Hubble-style needs a confirmed linear H-alpha/OIII color FITS.")
        elif not B.hubble_strength:
            reason = "No reliable star mask for protecting stars during the Hubble-style blend."
        ops.append({"name": "hubble_style", "requested": True,
                    "status": "skipped" if reason else ("reduced" if reduction < 1 else "applied"),
                    "reason": reason, "parameters": {"strength": recipe.hubble_strength,
                        "effective_strength": B.hubble_strength * reduction, "input_filter": filter_kind,
                        "dualband_confirmed": ctx.dualband_confirmed, "sky_rgb": B.hubble_sky if B.hubble_strength else None,
                        "signal_sigma": B.hubble_sigma if B.hubble_strength else None,
                        "domain": "display RGB only", "palette": "Hubble-style gold/teal from H-alpha and OIII proxies; not SHO"}})
    summary = _summary_note(ops)
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
                "note": "one shared scale/offset for all channels (scale = data maximum, the display white point); reversible",
            },
            "invalid_pixels": int(invalid.sum()),
            "metadata": image.metadata,
        },
        "protected_regions": region_summary(regions, w, h),
        "baseline_frame": frame.to_dict() if frame else None,
        "enhanced_frame": sp.to_dict() if sp else None,
        "linear_preparation": {
            "edges": edge_info,
            "sky": sky.to_dict() if sky else None,
            "pedestal": A.pedestal if A.sky is not None else None,
            "gradient": grad_model.to_dict() if grad_model else None,
            "white_balance": wb.to_dict() if (mode == "linear" and rgb and auto.white_balance and not is_noop) else None,
            "catalog_color": catalog if recipe.catalog_sha256 else None,
        } if mode == "linear" else None,
        "decisions": decisions,
        "clipping": {
            "thresholds": {"new_black_fraction": CLIP_THRESHOLD_BLACK, "new_white_fraction": CLIP_THRESHOLD_WHITE},
            "guard_action": guard_action,
            "first_pass": first_counts,
            "final": counts,
            "note": "New clipping is counted from per-pixel transitions against the original display; invalid and protected pixels are "
            "excluded, so values already black or saturated in the original are not new. Negative physical FITS values are not "
            "clipping and are retained in the processed-linear array.",
            "negative_values_source": int((image.pixels[image.valid_mask] < 0).sum()) if mode == "linear" else 0,
        },
        "execution": exec_info,
        "stage_timings": timings.items,
        "total_seconds": round(time.perf_counter() - t_start, 4),
        "dependencies": dependency_versions(),
        "noise_estimate": {
            **noise_report,
            "limitations": "Robust MAD of Gaussian high-pass residuals over valid, unprotected, non-star pixels. "
            "Stacking/resampling correlate noise, so this is approximate and not a calibrated signal-to-noise measurement.",
        } if noise_report else None,
        "learned_processing": learned,
        "scientific_disclosure": (
            ("Catalog RGB calibration uses relative reference-star colors, not absolute flux calibration. " if catalog["status"] == "applied" else
             "This is display enhancement, not scientific calibration. Field-star white balance is not photometric calibration. ")
            + "A sharper appearance is not additional measured resolution. "
            + (f"Learned (AI) processing was used ({', '.join(AI_LABELS[k] for k in learned)}): those values were predicted by trained "
               "neural networks from this image's own pixels (no prompts, no reference images); see each operation for the model file."
               if learned else "No pixels were generated.")
        ),
    }
    if notes:
        report["notes"] = notes
    return PipelineResult(
        display=display, baseline=baseline, display_fixed=display_fixed, processed=processed,
        valid_mask=image.valid_mask, protected_mask=protected, report=report, summary=summary,
        needs_review=needs_review, gpu_disabled=gpu_disabled, star_soft=star_soft,
    )


def _white_level(proc: np.ndarray, A: GroupA, rgb: bool) -> float:
    """Display white point: the processed value of the data's saturation level (normalized 1.0)."""
    if A.sky is not None:
        gains = A.gains if A.gains is not None else np.ones(len(A.sky), np.float32)
        return float(np.max((1.0 - A.sky) * gains) + A.pedestal)
    return float(max(np.max(proc), 1e-6)) if proc.size else 1.0


def _merge_exec(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    if not a:
        return b
    out = dict(b)
    out["fallbacks"] = a.get("fallbacks", []) + b.get("fallbacks", [])
    out["notes"] = (a.get("notes") or []) + (b.get("notes") or [])
    ta, tb = a.get("transfers") or {}, b.get("transfers") or {}
    out["transfers"] = {k: (ta.get(k, 0) or 0) + (tb.get(k, 0) or 0) for k in set(ta) | set(tb)}
    out["stage_group"] = f"{a.get('stage_group')}; {b.get('stage_group')}"
    if out.get("tile") is None and a.get("tile") is not None:
        out["tile"] = a["tile"]
    return out


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


def _tile_plan(halo: int, channels: int, h: int, w: int, budget_bytes: int | None, forced: int | None) -> int:
    """Largest tile edge whose working set (tile + halo) fits the budget; full frame when everything fits."""
    if forced:
        return forced
    full = max(h, w)
    if not budget_bytes:
        return full
    bpp = estimate_memory_per_pixel(channels)
    if h * w * bpp <= budget_bytes:
        return full
    edge = int(np.sqrt(budget_bytes / bpp)) - 2 * halo
    return max(256, (edge // 64) * 64)


def _execute(fn, exec_in, out_keys, halo, h, w, channels, opts, backend_name, gpu_disabled, timings, check, stage_name):
    """Run one contiguous pixel group; classified GPU failures retry once with smaller tiles, then rerun on CPU
    from the clean host inputs (never continuing from partial results)."""
    factory = opts.backend_factory or (lambda name: get_backend(name))
    info: dict[str, Any] = {
        "requested_device": opts.device, "resolved_backend": backend_name, "fallbacks": [], "precision": "float32",
        "stage_group": stage_name,
    }
    attempts = [backend_name]
    tile_override: int | None = None
    notes: list[str] = []
    shape = exec_in["x"].shape
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
            tile = tile_override or _tile_plan(halo, channels, h, w, budget, opts.force_tile)
            info["tile"] = None if tile >= max(h, w) else tile
            outputs = {k: np.empty(shape, dtype=np.float32) for k in out_keys}
            t0 = time.perf_counter()
            extras = run_tiled(lambda t, inner: fn(be, t, inner), exec_in, outputs, tile, halo if tile < max(h, w) else 0, check)
            counts = merge_clip_counts([e for e in extras if e is not None]) if any(e is not None for e in extras) else None
            be.synchronize()
            elapsed = time.perf_counter() - t0
            timings.items.append({"stage": stage_name, "backend": name, "seconds": round(elapsed, 4), "tile": info["tile"]})
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


# ====================================================================================================== report
@dataclass
class _ReportCtx:
    recipe: Recipe
    image: ImageData
    mode: str
    rgb: bool
    A: GroupA
    B: GroupB
    sp: StretchParams | None
    star: StarMask | None
    bg_status: dict[str, Any]
    bg_model: bgmod.BgModel | None
    bg_strength: float
    grad_status: dict[str, Any]
    grad_model: lp.GradientModel | None
    neutral_status: dict[str, Any]
    sky: lp.SkyStats | None
    wb: lp.WhiteBalance
    wb_status: dict[str, Any]
    deconv_status: dict[str, Any]
    hdr_status: dict[str, Any]
    scnr_status: dict[str, Any]
    reduction: float
    is_noop: bool
    regions: list[dict[str, int]]
    backend: str
    tone_stage: bool
    ai: dict[str, dict[str, Any]] = field(default_factory=dict)


def _operation_report(c: _ReportCtx) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    be_label = "gpu" if c.backend == "gpu" else "cpu"
    r, A, B = c.recipe, c.A, c.B
    reduced = c.reduction < 1

    def add(name, requested, status, reason=None, params=None, backend_used=None):
        ops.append({"name": name, "requested": requested, "status": status, "reason": reason, "parameters": params, "backend": backend_used})

    if r.background.enabled:
        if c.bg_model is not None:
            add("background", True, "applied", None, {
                **c.bg_model.to_dict(), "strength": c.bg_strength,
                "note": "Supervised: constant offsets and (for planar) a shared plane relative to a recorded reference sky level; constant subtracted once.",
            }, be_label)
        else:
            add("background", True, "skipped", c.bg_status.get("reason"))
    else:
        add("background", False, "off")

    def add_ai(name, requested):
        st = c.ai.get(name)
        if st is None:
            if not requested:
                add(name, False, "off")
            return
        add(name, True, st["status"], st.get("reason"), st.get("params"), (st.get("params") or {}).get("execution_provider") if st["status"] == "applied" else None)

    add_ai("ai_background", r.ai.background)
    if c.mode == "linear":
        st = c.grad_status
        add("gradient", r.auto.gradient, st["status"], st["reason"], c.grad_model.to_dict() if (c.grad_model and st["status"] == "applied") else None,
            be_label if st["status"] == "applied" else None)
    elif r.auto.gradient and not c.is_noop:
        add("gradient", True, c.grad_status.get("status", "inactive"), c.grad_status.get("reason"))
    st = c.neutral_status
    add("neutralize", r.auto.neutralize, st["status"] if r.auto.neutralize else "off", st["reason"], {
        "sky_per_channel": list(c.sky.level) if c.sky else None, "pedestal": A.pedestal if A.sky is not None else None,
        "rendered_offsets": A.rendered_offsets.tolist() if A.rendered_offsets is not None else None,
        "note": "Per-channel sky offsets to one shared level (an offset per channel, never a per-channel scale)",
    } if st["status"] == "applied" else None, be_label if st["status"] == "applied" else None)
    if c.rgb:
        st = c.wb_status
        add("white_balance", r.auto.white_balance, st["status"] if r.auto.white_balance else "off", st["reason"],
            c.wb.to_dict() if st["status"] in ("applied", "skipped") and c.mode == "linear" else None, be_label if st["status"] == "applied" else None)
    st = c.deconv_status
    add("deconvolution", r.advanced.deconvolution, st["status"], st["reason"], A.deconv.to_dict() if A.deconv else None, be_label if A.deconv else None)
    add_ai("ai_denoise", r.ai.denoise)
    if A.denoise is not None:
        add("denoise", True, "applied", None, A.denoise.to_dict(), be_label)
    elif (c.ai.get("ai_denoise") or {}).get("status") == "applied":
        add("denoise", True, "inactive", "Replaced by AI noise reduction.")
    else:
        add("denoise", False, "off")
    if c.tone_stage:
        params: dict[str, Any] = {"manual": B.manual.to_dict()}
        if r.tone.enabled and c.mode == "linear" and c.sp:
            params.update(base="hyperbolic luminance stretch with highlight convergence + MTF to the target sky", stretch=c.sp.to_dict())
        elif r.tone.enabled:
            params.update(base="rational midtone gain + MTF toward the target sky", gain=B.rend_gain, mtf_m=B.rend_m)
        else:
            params.update(base="baseline (identity / frozen baseline mapping)")
        add("tone", True, "applied", None, params, be_label)
    else:
        add("tone", False, "off")
    add_ai("ai_stars", r.ai.stars)
    if r.ai.star_brightness < 1.0 and (st := c.ai.get("ai_stars")) is not None:
        add("star_brightness", True, st["status"], st.get("reason"),
            {"factor": B.star_brightness, "domain": "display-only"} if B.separated else None,
            be_label if B.separated else None)
    if r.auto.star_stretch and B.separated and c.tone_stage and r.tone.enabled:
        add("star_stretch", True, "applied", None, {
            "method": "stars separated by the AI tool are added back over the finished starless image with the brightness the stretch gives them, "
                      "blended toward the gentler stretch (D/8, same sky level)",
            "amount": B.star_amount, "gentle_stretch": B.sp_star.to_dict() if B.sp_star else None,
        }, be_label)
    elif r.auto.star_stretch:
        if not (c.tone_stage and r.tone.enabled):
            add("star_stretch", True, "inactive", "The stretch is disabled, so there is nothing to soften on stars.")
        elif c.star is None or not c.star.reliable:
            reason = (c.star.stats.get("reason") if c.star else None) or "Star detection was unreliable."
            add("star_stretch", True, "skipped", f"{reason}. Highlight convergence still keeps star cores from clipping.", c.star.stats if c.star else None)
        else:
            add("star_stretch", True, "applied", None, {
                "amount": B.star_amount, "accepted_stars": c.star.stats.get("accepted"),
                "method": "gentler stretch (D/8, same sky level) blended inside the soft star mask" if c.mode == "linear"
                else "limits extra brightening of confident compact stars",
                "gentle_stretch": B.sp_star.to_dict() if B.sp_star else None, "detection": c.star.stats,
            }, be_label)
    else:
        add("star_stretch", False, "off")
    st = c.hdr_status
    add("hdr", r.look.protect_cores, ("reduced" if reduced and st["status"] == "applied" else st["status"]) if r.look.protect_cores else "off", st["reason"],
        {"amount": B.hdr_amount, "sigma_px": fin.HDR_SIGMA, "threshold": fin.HDR_THRESHOLD} if st["status"] == "applied" else None,
        be_label if st["status"] == "applied" else None)
    if c.rgb:
        st = c.scnr_status
        add("green_removal", r.auto.green_removal, st["status"] if r.auto.green_removal else "off", st["reason"],
            {"method": "SCNR average neutral, lightness preserved", "amount": B.scnr_amount} if st["status"] == "applied" else None,
            be_label if st["status"] == "applied" else None)
    if r.look.contrast > 0:
        add("contrast", True, "reduced" if reduced else "applied", None, {"s_curve_amplitude": B.pop_a, "anchored_at_sky": B.sky_disp}, be_label)
    else:
        add("contrast", False, "off")
    if B.detail is not None:
        add("detail", True, "reduced" if reduced else "applied", None, {**B.detail.to_dict(), "domain": "display-only"}, be_label)
    else:
        add("detail", False, "off")
    if r.look.color > 0 and not c.rgb:
        add("color", True, "skipped", "Monochrome image: color enhancement is not available.")
    elif r.look.color > 0:
        add("color", True, "reduced" if reduced else "applied", None, {
            "saturation": B.saturation, "protected_below": B.sky_disp + B.sky_sd, "domain": "display RGB only (never in the processed-linear FITS)",
        }, be_label)
    else:
        add("color", False, "off")
    if r.protect_regions:
        add("protect_regions", True, "applied" if c.regions else "off", None if c.regions else "No label regions were confirmed.", {"count": len(c.regions)} if c.regions else None)
    if c.is_noop:
        ops.append({"name": "no_operations", "requested": True, "status": "applied", "reason": "No operations were selected; the decoded display pixels are reproduced unchanged.", "parameters": None, "backend": None})
    return ops


def _summary_note(ops) -> str:
    phrases = {
        ("hubble_style", "applied"): "Hubble-style (not SHO)",
        ("hubble_style", "reduced"): "Hubble-style (not SHO) at reduced strength",
        ("gradient", "applied"): "Gradient removed",
        ("neutralize", "applied"): "Background neutralized",
        ("white_balance", "applied"): "Color balanced",
        ("deconvolution", "applied"): "Sharpened (deconvolution)",
        ("denoise", "applied"): "Noise reduced",
        ("tone", "applied"): "Stretched",
        ("star_stretch", "applied"): "Stars kept small",
        ("hdr", "applied"): "Bright cores protected",
        ("hdr", "reduced"): "Bright cores protected (reduced to limit clipping)",
        ("green_removal", "applied"): "Green cast removed",
        ("contrast", "applied"): "Contrast added",
        ("contrast", "reduced"): "Contrast added (reduced to limit clipping)",
        ("detail", "applied"): "Detail enhanced",
        ("detail", "reduced"): "Detail enhanced (reduced to limit clipping)",
        ("color", "applied"): "Colors enhanced",
        ("color", "reduced"): "Colors enhanced (reduced to limit clipping)",
        ("background", "applied"): "Background balanced",
        ("ai_background", "applied"): "AI background removed",
        ("ai_denoise", "applied"): "AI noise reduction",
        ("ai_stars", "applied"): "Stars separated (AI) and added back",
        ("star_brightness", "applied"): "Stars dimmed",
    }
    parts = []
    quiet_skips = {"hdr", "green_removal", "gradient"}  # automatic stages that are expected to skip on many images
    for op in ops:
        if op["name"] == "no_operations":
            parts.append("No operations selected")
        elif op["status"] == "skipped" and op["name"] not in quiet_skips:
            parts.append(f"{AI_LABELS.get(op['name']) or op['name'].replace('_', ' ').capitalize()} skipped")
        elif (op["name"], op["status"]) in phrases:
            parts.append(phrases[(op["name"], op["status"])])
    return " · ".join(parts) or "Complete"


# ====================================================================================================== AI helpers
AI_STRETCH_NOISE_RATIO = 0.5
AI_LABELS = {"ai_background": "AI background extraction", "ai_denoise": "AI noise reduction", "ai_stars": "AI star separation"}


def _ai_model(opts: ExecutionOptions, tool: str, rgb: bool) -> tuple[ai_registry.ModelSpec, Path | None, str | None]:
    ids = ai_registry.TOOL_MODELS[tool]
    spec = ai_registry.MODELS[ids[0] if (tool != "stars" or rgb) else ids[1]]
    path = ai_registry.installed(opts.ai_models_dir, spec)
    if path is None:
        return spec, None, f"The AI model '{spec.title}' is not downloaded yet (Settings > AI models); the classical step was used instead."
    return spec, path, None


def _run_ai(opts: ExecutionOptions, tool: str, rgb: bool, progress, label: str, fn, nchw: bool = False) -> dict[str, Any]:
    """Run one AI tool. ``fn(runner)`` returns (result, params). Failures are reported, never fatal (the classical step runs)."""
    spec, path, reason = _ai_model(opts, tool, rgb)
    if path is None:
        return {"status": "skipped", "reason": reason}
    progress(label)
    info = AIStepInfo(spec)
    try:
        run = Runner(path, opts.device, nchw=nchw)
        result, params = timed(info, lambda: fn(run))
    except Cancelled:
        raise
    except Exception as exc:
        return {"status": "skipped", "reason": f"The AI model could not run ({type(exc).__name__}: {str(exc)[:160]}); the classical step was used instead."}
    info.provider, info.fallbacks = run.label, run.fallbacks
    info.params.update(params)
    return {"status": "applied", "reason": None, "params": info.to_dict(), "result": result}


def _percent(progress, label: str):
    last = [-1]

    def cb(f: float) -> None:
        pct = int(f * 10) * 10
        if pct != last[0]:
            last[0] = pct
            progress(f"{label} {pct}%")

    return cb
