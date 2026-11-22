"""Integration of registered frames.

Sub-frames ("subs"): calibrate -> repair defective pixels -> debayer (bilinear) -> subtract the per-channel
background offset to the reference frame -> warp onto the reference grid (bilinear) -> combine with
kappa-sigma rejection and noise weights (1 / sigma^2). Up to 40 frames that fit the memory budget the rejection is
exact (iterative, median-centred); otherwise two streaming passes are used (weighted mean and standard deviation, then
a clipped weighted mean), so hundreds of frames never need to be held at once.

2x drizzle (subs): after the native pass, every *measured* CFA pixel (no interpolated colour) is dropped onto a
grid twice as fine through its frame's transform with bilinear weights ("Bayer drizzle", point kernel), skipping
pixels the native statistics reject. Output pixels no frame reached are filled from the native stack, upsampled
(counted and reported).

Mosaics (subs whose header pointings differ, or Seestar mosaic sub-frames): the reference is the best frame of the
central panel; a frame that does not match it is matched to an already aligned frame of the nearest pointing and the
transforms are chained; the output canvas is the union of all aligned frames (capped at ``MOSAIC_MAX_AREA`` times one
frame), and pixels no frame covered are left empty (NaN, reported). Panels are levelled by the same per-channel
background offset as any sub-frame; no seam blending or per-panel gradient model is applied.

Colour balance (colour subs, on by default): the integrated stack is multiplied by one gain per channel (green 1) that
makes the sky neutral, like the Seestar's own stacks; skipped with a reason when the sky is too faint, recorded in the
report and the ``CBAL_R/G/B`` header keywords.

Stacked images from different nights ("sessions"): registered (any scale), resampled onto the largest image,
background-matched and combined, weighted by integration time, with kappa-sigma rejection from three images on.

Nothing is generated: every output value is a weighted mean of measured, resampled pixel values (times the recorded
per-channel colour-balance gain).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from astropy.io import fits
from scipy import ndimage

from ..diagnostics import MAD_TO_SIGMA
from ..imagedata import ProcessingError
from .calibrate import Calibration, _K, bayer_masks, debayer
from .frames import FrameInfo, pointing_offsets, read_frame
from .quality import FrameStats, StarList, grade, measure
from .register import IDENTITY, Match, Transform, match

DEFAULT_KAPPA = 3.0
SIGMA_ITERATIONS = 3
MIN_FRAMES = 2
EXACT_MAX_FRAMES = 40
MOSAIC_MAX_AREA = 6.0  # mosaic canvas at most this many frame areas
MOSAIC_CHAIN_TRIES = 4


@dataclass
class StackOptions:
    mode: str = "subs"  # subs | sessions
    scale: int = 1  # 1 = native, 2 = drizzle (subs only)
    grading: str = "standard"
    rejection: str = "sigma"  # sigma | none
    kappa: float = DEFAULT_KAPPA
    memory_budget_bytes: int = 3 * 1024**3
    device: str = "auto"  # auto | gpu | cpu
    threads: int = 4
    mosaic: bool = False  # subs: union canvas over all frames, chained registration
    color_balance: bool = True  # subs (colour): per-channel gains that make the sky neutral, as the Seestar's own stacks are


BALANCE_BIN = 4  # sky colour is measured on 4 x 4 block means, so pixel noise barely biases the dim-half selection
BALANCE_GAIN_RANGE = (0.4, 2.5)
BALANCE_MIN_SKY_SNR = 5.0


def sky_color_balance(data: np.ndarray) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Per-channel gains (green = 1) that make the sky background neutral.

    Raw colour sub-frames carry the sensor's colour response and the sky glow (a Seestar S30 sky through its IR-cut
    filter is ~1.4x brighter in red), so a stack in camera colour looks strongly tinted; the Seestar's own stacks are
    balanced this way. The sky is the median of the dimmer half (by luminance) of 4 x 4 block means of covered pixels.
    Skipped with a reason when the sky is not clearly above the noise or would need extreme gains."""
    def skip(reason: str) -> tuple[None, dict[str, Any]]:
        return None, {"status": "skipped", "reason": reason}

    if data.ndim != 3 or data.shape[2] != 3:
        return skip("Monochrome frames have no colour to balance.")
    b = BALANCE_BIN
    h, w = (data.shape[0] // b) * b, (data.shape[1] // b) * b
    blocks = data[:h, :w].reshape(h // b, b, w // b, b, 3).mean(axis=(1, 3), dtype=np.float64).reshape(-1, 3)
    blocks = blocks[np.isfinite(blocks).all(axis=1)]
    if len(blocks) < 1000:
        return skip("Too little of the image is covered to measure the sky colour.")
    lum = blocks.mean(axis=1)
    dim = blocks[lum <= np.median(lum)]
    sky = np.median(dim, axis=0)
    noise = np.median(np.abs(dim - sky), axis=0) * MAD_TO_SIGMA
    if (sky <= BALANCE_MIN_SKY_SNR * np.maximum(noise, 1e-9)).any():
        return skip("The sky is too dark (close to zero after calibration) in at least one colour to set the colour balance; camera colour kept.")
    gains = sky[1] / sky
    lo, hi = BALANCE_GAIN_RANGE
    if (gains < lo).any() or (gains > hi).any():
        return skip(f"The sky colour would need gains outside {lo}-{hi} (R {gains[0]:.2f}, B {gains[2]:.2f}); camera colour kept.")
    return gains, {"status": "applied", "method": "per-channel gains that make the median sky of the dimmer half neutral (green unchanged)",
                   "sky_before": sky.tolist(), "gains_rgb": gains.tolist()}


def compose(t2: Transform, t1: Transform) -> Transform:
    """The similarity x -> t2(t1(x))."""
    tx, ty = t2.apply(np.float64(t1.tx), np.float64(t1.ty))
    return Transform(t2.a * t1.a - t2.b * t1.b, t2.a * t1.b + t2.b * t1.a, float(tx), float(ty))


@dataclass
class StackResult:
    data: np.ndarray  # H x W x 3 (or H x W) float32, source units (ADU)
    coverage: np.ndarray  # H x W number of frames contributing
    header: fits.Header
    report: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------------------------- array ops (CPU/GPU)
class _Ops:
    """Debayer + warp on NumPy/SciPy or, when available, CuPy/cupyx (same algorithms, float32)."""

    def __init__(self, device: str) -> None:
        self.name = "cpu"
        self.xp, self.nd = np, ndimage
        if device != "cpu":
            try:
                import cupy as cp
                from cupyx.scipy import ndimage as cnd

                cp.zeros(1).sum()  # touches the device
                self.xp, self.nd, self.name = cp, cnd, "gpu"
            except Exception:
                if device == "gpu":
                    self.note = "NVIDIA GPU requested but unavailable; stacking on the CPU."
        self.note = getattr(self, "note", None)

    def to(self, a):
        return self.xp.asarray(a)

    def host(self, a) -> np.ndarray:
        return a if isinstance(a, np.ndarray) else self.xp.asnumpy(a)

    def debayer(self, raw, pattern: str):
        xp, nd = self.xp, self.nd
        h, w = raw.shape
        masks = bayer_masks(pattern, h, w)
        k = xp.asarray(_K)
        out = xp.empty((h, w, 3), dtype=xp.float32)
        for c, ch in enumerate("RGB"):
            m = xp.asarray(masks[ch])
            num = nd.convolve(raw * m, k, mode="mirror")
            den = nd.convolve(m, k, mode="mirror")
            out[..., c] = xp.where(m > 0, raw, num / xp.maximum(den, 1e-6))
        return out

    def warp(self, img, t_inv: Transform, out_hw: tuple[int, int]):
        """Resample ``img`` onto the reference grid; outside the frame -> NaN. ``t_inv`` maps ref -> frame."""
        xp, nd = self.xp, self.nd
        mat = xp.asarray([[t_inv.a, t_inv.b], [-t_inv.b, t_inv.a]], dtype=xp.float64)
        off = xp.asarray([t_inv.ty, t_inv.tx], dtype=xp.float64)
        if img.ndim == 2:
            return nd.affine_transform(img, mat, offset=off, output_shape=out_hw, order=1, mode="constant", cval=np.nan)
        return xp.stack([nd.affine_transform(img[..., c], mat, offset=off, output_shape=out_hw, order=1, mode="constant", cval=np.nan)
                         for c in range(img.shape[2])], axis=-1)


# ----------------------------------------------------------------------------------------------- helpers
def _robust(v: np.ndarray) -> tuple[float, float]:
    v = v[np.isfinite(v)]
    if v.size == 0:
        return 0.0, 0.0
    m = float(np.median(v))
    return m, float(np.median(np.abs(v - m)) * MAD_TO_SIGMA)


def _sigma_clip_combine(stack: np.ndarray, weights: np.ndarray, kappa: float, reject: bool) -> tuple[np.ndarray, np.ndarray, int]:
    """stack: (n, ...) with NaN = no data. Returns (combined, contributing count, rejected samples)."""
    valid = np.isfinite(stack)
    w = np.broadcast_to(weights.reshape((-1,) + (1,) * (stack.ndim - 1)), stack.shape)
    keep = valid.copy()
    rejected = 0
    if reject and stack.shape[0] >= 3:
        for _ in range(SIGMA_ITERATIONS):
            data = np.where(keep, stack, np.nan)
            with np.errstate(all="ignore"):
                med = np.nanmedian(data, axis=0)
                sig = np.nanstd(data, axis=0)
            sig = np.where(np.isfinite(sig) & (sig > 0), sig, np.inf)
            new = keep & (np.abs(stack - med) <= kappa * sig)
            if (new == keep).all():
                break
            keep = new
        rejected = int((valid & ~keep).sum())
    ww = np.where(keep, w, 0.0)
    num = np.where(keep, stack, 0.0) * ww
    den = ww.sum(axis=0)
    with np.errstate(all="ignore"):
        out = num.sum(axis=0) / den
    out = np.where(den > 0, out, np.nan).astype(np.float32)
    return out, keep.sum(axis=0), rejected


def _apply_offsets(img, offsets: np.ndarray, xp=np):
    if img.ndim == 3:
        return img - xp.asarray(offsets.astype(np.float32))
    return img - float(offsets[0])


def _cfa_offsets(raw: np.ndarray, pattern: str | None, offsets: np.ndarray) -> np.ndarray:
    if not pattern:
        return raw - float(offsets[0])
    out = raw.copy()
    idx = {"R": 0, "G": 1, "B": 2}
    for i, ch in enumerate(pattern):
        dy, dx = divmod(i, 2)
        out[dy::2, dx::2] -= offsets[idx[ch]]
    return out


def _header_for(ref_header, lights: list[FrameInfo], used: list[int], kind: str, extra: dict[str, Any]) -> fits.Header:
    h = fits.Header()
    keep = ("OBJECT", "RA", "DEC", "INSTRUME", "TELESCOP", "FILTER", "GAIN", "FOCALLEN", "XPIXSZ", "YPIXSZ", "DATE-OBS",
            "EXPTIME", "EXPOSURE", "SITELAT", "SITELONG", "OBSERVER", "CREATOR")
    for k in keep:
        if ref_header is not None and k in ref_header:
            try:
                h[k] = ref_header[k]
            except Exception:
                pass
    h["IMAGETYP"] = ("Light", "integrated light frame")
    h["STACKCNT"] = (int(sum(lights[i].stack_count for i in used)), "sub-frames integrated")
    live = sum((lights[i].exposure or 0.0) * lights[i].stack_count for i in used)
    if live:
        h["LIVETIME"] = (float(live), "total integration time (s)")
    h["ROWORDER"] = ("TOP-DOWN", "rows stored in display order")
    h["CTYPE3"] = ("RGB", "colour planes")
    h["BUNIT"] = ("ADU", "calibrated, background-normalized")
    h["EAESTACK"] = (kind, "EasyAstroEnhance stacking mode")
    for k, v in extra.items():
        h[k] = v
    return h


# ----------------------------------------------------------------------------------------------- sub-frames
def stack_subs(lights: list[FrameInfo], cal: Calibration, opts: StackOptions, check: Callable[[], None],
               progress: Callable[[str, float], None]) -> StackResult:
    t0 = time.perf_counter()
    rep: dict[str, Any] = {"mode": "subs", "frames_total": len(lights), "calibration": cal.report}
    pattern = cal.pattern
    layout = lights[0].layout
    ops = _Ops(opts.device)
    rep["device"] = ops.name
    if ops.note:
        rep["device_note"] = ops.note

    # ---- 1. measure every frame
    stats: list[FrameStats | None] = [None] * len(lights)
    stars: list[StarList | None] = [None] * len(lights)
    headers: list[Any] = [None] * len(lights)

    def analyse(i: int):
        check()
        raw, hdr = read_frame(lights[i])
        img = cal.apply(raw)
        s, st = measure(img, layout, pattern)
        return i, s, st, hdr

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, opts.threads)) as ex:
        for i, s, st, hdr in ex.map(analyse, range(len(lights))):
            stats[i], stars[i], headers[i] = s, st, hdr if i == 0 else None
            done += 1
            if done % 10 == 0 or done == len(lights):
                progress(f"Measuring frames {done}/{len(lights)}", 0.25 * done / len(lights))

    # ---- 2. grade and pick the reference
    offs = pointing_offsets(lights) if opts.mosaic else None
    reasons = grade(stats, opts.grading, _neighbours(offs) if offs is not None else None)
    kept = [i for i, r in enumerate(reasons) if r is None]
    if len(kept) < MIN_FRAMES:
        raise ProcessingError("TOO_FEW_GOOD_FRAMES", f"Only {len(kept)} usable frames remained after quality checks; at least {MIN_FRAMES} are needed.")
    pool = kept
    if offs is not None:  # the reference comes from the central panel, so most panels overlap it directly
        dist = np.hypot(offs[:, 0], offs[:, 1])
        near = min(dist[i] for i in kept)
        pool = [i for i in kept if dist[i] <= near + 0.02]
    ref = max(pool, key=lambda i: (stats[i].stars / max(stats[i].fwhm or 10.0, 0.5) ** 2, -i))  # type: ignore[union-attr]
    rep["reference"] = {"name": lights[ref].name, **stats[ref].to_dict()}  # type: ignore[union-attr]

    # ---- 3. register
    transforms: dict[int, Transform] = {ref: IDENTITY}
    regs: dict[str, Any] = {}
    for n, i in enumerate(kept):
        check()
        if i == ref:
            continue
        m: Match = match(stars[ref], stars[i], (0.97, 1.03))  # type: ignore[arg-type]
        if m.ok:
            transforms[i] = m.transform  # type: ignore[assignment]
            regs[lights[i].name] = {"rms_px": m.rms, "stars": m.inliers, **m.transform.to_dict()}  # type: ignore[union-attr]
        else:
            reasons[i] = m.reason
        if n % 20 == 0:
            progress(f"Aligning frames {n + 1}/{len(kept)}", 0.25 + 0.1 * (n + 1) / len(kept))
    chained = _chain_unmatched(kept, transforms, stars, offs, reasons, regs, lights, check) if opts.mosaic else 0
    used = [i for i in kept if i in transforms]
    if len(used) < MIN_FRAMES:
        raise ProcessingError("ALIGNMENT_FAILED", "Too few frames could be aligned to each other; check that the folder holds one target.")
    rot = [regs[lights[i].name]["rotation_deg"] for i in used if i != ref]
    rms = [regs[lights[i].name]["rms_px"] for i in used if i != ref]
    rep["registration"] = {"method": "triangle matching + RANSAC similarity (rotation, scale, shift)",
                           "rotation_range_deg": [float(min(rot, default=0)), float(max(rot, default=0))],
                           "median_rms_px": float(np.median(rms)) if rms else 0.0}
    rep["rejected_frames"] = [{"name": lights[i].name, "reason": reasons[i]} for i in range(len(lights)) if reasons[i]]
    rep["frames_used"] = len(used)

    # ---- 4. normalization and weights
    ref_bg = np.asarray(stats[ref].channel_background, np.float64)  # type: ignore[union-attr]
    offsets = {i: np.asarray(stats[i].channel_background, np.float64) - ref_bg for i in used}  # type: ignore[union-attr]
    noise = np.asarray([stats[i].noise for i in used], np.float64)  # type: ignore[union-attr]
    weights = 1.0 / np.maximum(noise, 1e-9) ** 2
    weights = weights / weights.mean()
    wmap = dict(zip(used, weights))
    rep["normalization"] = {"method": "additive per-channel background offset to the reference frame", "reference_background": ref_bg.tolist()}
    rep["weights"] = {"method": "1 / noise^2 (noise = robust MAD of the frame's high-pass residual)", "min": float(weights.min()), "max": float(weights.max())}

    H, W = lights[ref].height, lights[ref].width
    C = 3 if layout == "cfa" else 1
    if opts.mosaic:
        transforms, (H, W), rep["mosaic"] = _union_canvas(transforms, used, lights[ref].width, lights[ref].height)
        rep["mosaic"]["chained_frames"] = chained

    def warped(i: int) -> np.ndarray:
        check()
        raw, _ = read_frame(lights[i])
        img = cal.apply(raw)
        x = ops.to(img)
        if pattern:
            x = ops.debayer(x, pattern)
        x = _apply_offsets(x, offsets[i], ops.xp)
        t_inv = transforms[i].inverse()
        y = ops.warp(x, t_inv, (H, W))
        out = ops.host(y).astype(np.float32, copy=False)
        return out if out.ndim == 3 else out[..., None]

    frame_bytes = H * W * C * 4
    # Exact median-centred clipping is needed for few frames (one outlier can reach at most (n-1)/sqrt(n) sigma of a
    # plain mean/std); with many frames the two streaming passes reject the same outliers several times faster.
    in_memory = frame_bytes * len(used) <= opts.memory_budget_bytes and opts.scale == 1 and len(used) <= EXACT_MAX_FRAMES
    reject = opts.rejection == "sigma"
    rejected_samples = 0
    if in_memory:
        stack = np.empty((len(used), H, W, C), np.float32)
        with ThreadPoolExecutor(max_workers=max(1, opts.threads)) as ex:
            for n, (k, arr) in enumerate(zip(range(len(used)), ex.map(warped, used))):
                stack[k] = arr
                if n % 10 == 0:
                    progress(f"Aligning and calibrating {n + 1}/{len(used)}", 0.35 + 0.5 * (n + 1) / len(used))
        progress("Combining with outlier rejection", 0.88)
        out = np.empty((H, W, C), np.float32)
        cov = np.zeros((H, W), np.int32)
        rows = max(1, int(64_000_000 // max(1, len(used) * W * C)))
        for y0 in range(0, H, rows):
            check()
            o, c, r = _sigma_clip_combine(stack[:, y0 : y0 + rows], weights, opts.kappa, reject)
            out[y0 : y0 + rows] = o
            cov[y0 : y0 + rows] = c.min(axis=-1)
            rejected_samples += r
        del stack
        rep["integration"] = {"method": f"weighted mean, iterative kappa-sigma rejection (kappa {opts.kappa}, median-centred)" if reject else "weighted mean (no rejection)",
                              "algorithm": "exact (all frames in memory)"}
    else:
        out, cov, mean, std, rejected_samples = _streaming(used, warped, wmap, H, W, C, opts, reject, check, progress)
        rep["integration"] = {"method": f"weighted mean, two-pass kappa-sigma rejection (kappa {opts.kappa})" if reject else "weighted mean (no rejection)",
                              "algorithm": "streaming (two passes over the frames)"}
        if opts.scale == 2:
            out, cov, filled = _drizzle(used, lights, cal, transforms, offsets, wmap, mean, std, H, W, C, opts, reject, check, progress)
            rep["drizzle"] = {"scale": 2, "method": "Bayer drizzle, point kernel with bilinear weights, rejection against the native stack",
                              "filled_from_native_fraction": filled}
    total = len(used) * max(1, H * W * C)
    rep["rejected_pixel_fraction"] = float(rejected_samples) / total if total else 0.0
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    data = out if C == 3 else out[..., 0]
    data = np.where((cov > 0)[..., None] if data.ndim == 3 else cov > 0, data, np.nan).astype(np.float32)
    extra: dict[str, Any] = {}
    if C == 3:
        if opts.color_balance:
            gains, rep["color_balance"] = sky_color_balance(data)
            if gains is not None:
                for c in range(3):
                    data[..., c] *= np.float32(gains[c])
                extra = {f"CBAL_{ch}": (float(g), "sky colour-balance gain applied") for ch, g in zip("RGB", gains)}
        else:
            rep["color_balance"] = {"status": "off", "reason": "Camera colour kept (colour balance switched off)."}
    hdr = _header_for(headers[ref] if headers[ref] is not None else read_frame(lights[ref])[1], lights, used, ("subs" if opts.scale == 1 else "subs-drizzle2x") + ("-mosaic" if opts.mosaic else ""), extra)
    if C == 1:
        del hdr["CTYPE3"]
    return StackResult(data, cov, hdr, rep)


MOSAIC_NEIGHBOURS = 9  # Seestar mosaics record about two frames per panel: compare with the surrounding panels too


def _neighbours(offs: np.ndarray) -> list[list[int]]:
    """For each frame, the frames whose header pointings are nearest (itself included)."""
    d = np.hypot(offs[:, None, 0] - offs[None, :, 0], offs[:, None, 1] - offs[None, :, 1])
    return [list(np.argsort(row, kind="stable")[:MOSAIC_NEIGHBOURS]) for row in d]


def _chain_unmatched(kept, transforms, stars, offs, reasons, regs, lights, check) -> int:
    """Mosaics: match each frame that failed against the reference to aligned frames of the nearest pointings."""
    chained = 0
    for i in [i for i in kept if i not in transforms]:
        check()
        cands = [j for j in transforms if j != i]
        if offs is not None:
            cands.sort(key=lambda j: float(np.hypot(*(offs[j] - offs[i]))))
        for j in cands[:MOSAIC_CHAIN_TRIES]:
            m = match(stars[j], stars[i], (0.97, 1.03))
            if m.ok:
                transforms[i] = compose(transforms[j], m.transform)
                regs[lights[i].name] = {"rms_px": m.rms, "stars": m.inliers, "chained_via": lights[j].name, **transforms[i].to_dict()}
                reasons[i] = None
                chained += 1
                break
    return chained


def _union_canvas(transforms: dict[int, Transform], used: list[int], w: int, h: int):
    """Shift every frame -> reference transform onto a canvas holding all aligned frames."""
    xs, ys = [], []
    for i in used:
        cx, cy = transforms[i].apply(np.array([0.0, w - 1.0, 0.0, w - 1.0]), np.array([0.0, 0.0, h - 1.0, h - 1.0]))
        xs += list(cx)
        ys += list(cy)
    x0, y0 = int(np.floor(min(xs))), int(np.floor(min(ys)))
    W, H = int(np.ceil(max(xs))) - x0 + 1, int(np.ceil(max(ys))) - y0 + 1
    if W * H > MOSAIC_MAX_AREA * w * h:
        raise ProcessingError("MOSAIC_TOO_LARGE", f"The aligned frames span {W} x {H} pixels, more than {MOSAIC_MAX_AREA:g} frames' area; "
                              "check that the folder holds one mosaic.")
    shift = Transform(1.0, 0.0, float(-x0), float(-y0))
    out = {i: compose(shift, t) for i, t in transforms.items()}
    return out, (H, W), {"canvas": [W, H], "frame": [w, h], "reference_offset_px": [-x0, -y0],
                         "method": "union of all aligned frames; uncovered pixels empty; panels levelled by per-channel background offsets"}


def _streaming(used, warped, wmap, H, W, C, opts, reject, check, progress):
    sw = np.zeros((H, W, C), np.float64)
    swx = np.zeros((H, W, C), np.float64)
    swx2 = np.zeros((H, W, C), np.float64)
    with ThreadPoolExecutor(max_workers=max(1, opts.threads)) as ex:
        for n, (i, arr) in enumerate(zip(used, ex.map(warped, used))):
            ok = np.isfinite(arr)
            a = np.where(ok, arr, 0.0)
            w = wmap[i] * ok
            sw += w
            swx += w * a
            swx2 += w * a * a
            if n % 10 == 0:
                progress(f"Integrating (pass 1) {n + 1}/{len(used)}", 0.35 + 0.25 * (n + 1) / len(used))
    with np.errstate(all="ignore"):
        mean = swx / sw
        std = np.sqrt(np.maximum(swx2 / sw - mean**2, 0.0))
    if not reject:
        cov = (sw > 0).all(axis=-1).astype(np.int32) * len(used)
        return mean.astype(np.float32), cov, mean, std, 0
    floor = np.nanmedian(std[sw > 0]) * 0.05 if np.any(sw > 0) else 1e-6
    std_c = np.maximum(std, floor)
    sw2 = np.zeros((H, W, C), np.float64)
    swx_2 = np.zeros((H, W, C), np.float64)
    cnt = np.zeros((H, W), np.int32)
    rejected = 0
    with ThreadPoolExecutor(max_workers=max(1, opts.threads)) as ex:
        for n, (i, arr) in enumerate(zip(used, ex.map(warped, used))):
            ok = np.isfinite(arr)
            good = ok & (np.abs(arr - mean) <= opts.kappa * std_c)
            rejected += int((ok & ~good).sum())
            a = np.where(good, arr, 0.0)
            w = wmap[i] * good
            sw2 += w
            swx_2 += w * a
            cnt += good.all(axis=-1)
            if n % 10 == 0:
                progress(f"Integrating (pass 2, rejecting outliers) {n + 1}/{len(used)}", 0.6 + 0.3 * (n + 1) / len(used))
    with np.errstate(all="ignore"):
        out = np.where(sw2 > 0, swx_2 / sw2, mean)
    return out.astype(np.float32), cnt, mean, std_c, rejected


def _drizzle(used, lights, cal, transforms, offsets, wmap, mean, std, H, W, C, opts, reject, check, progress):
    H2, W2 = 2 * H, 2 * W
    sums = np.zeros((C, H2 * W2), np.float64)
    wsum = np.zeros((C, H2 * W2), np.float64)
    pattern = cal.pattern
    h, w = lights[used[0]].height, lights[used[0]].width
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    if pattern:
        chan = np.zeros((h, w), np.int8)
        idx = {"R": 0, "G": 1, "B": 2}
        for i, ch in enumerate(pattern):
            dy, dx = divmod(i, 2)
            chan[dy::2, dx::2] = idx[ch]
    else:
        chan = np.zeros((h, w), np.int8)
    for n, i in enumerate(used):
        check()
        raw, _ = read_frame(lights[i])
        v = _cfa_offsets(cal.apply(raw), pattern, offsets[i]).ravel().astype(np.float64)
        t = transforms[i]
        xr, yr = t.apply(xx.ravel(), yy.ravel())
        c = chan.ravel()
        ir, jr = np.rint(yr).astype(np.int64), np.rint(xr).astype(np.int64)
        inside = (ir >= 0) & (ir < H) & (jr >= 0) & (jr < W)
        if reject:
            m = np.full(v.shape, np.nan)
            s = np.full(v.shape, np.inf)
            m[inside] = mean[ir[inside], jr[inside], c[inside]]
            s[inside] = std[ir[inside], jr[inside], c[inside]]
            inside &= np.abs(v - m) <= opts.kappa * s
        xs, ys = 2.0 * xr + 0.5, 2.0 * yr + 0.5
        x0, y0 = np.floor(xs).astype(np.int64), np.floor(ys).astype(np.int64)
        fx, fy = xs - x0, ys - y0
        cbase = c.astype(np.int64) * (H2 * W2)
        for dy, dx, wt in ((0, 0, (1 - fx) * (1 - fy)), (0, 1, fx * (1 - fy)), (1, 0, (1 - fx) * fy), (1, 1, fx * fy)):
            yi, xi = y0 + dy, x0 + dx
            ok = inside & (yi >= 0) & (yi < H2) & (xi >= 0) & (xi < W2) & (wt > 0)
            flat = (cbase + yi * W2 + xi)[ok]
            ww = (wt * wmap[i])[ok]
            sums += np.bincount(flat, weights=v[ok] * ww, minlength=C * H2 * W2).reshape(C, -1)
            wsum += np.bincount(flat, weights=ww, minlength=C * H2 * W2).reshape(C, -1)
        if n % 10 == 0:
            progress(f"Drizzling {n + 1}/{len(used)}", 0.9 + 0.08 * (n + 1) / len(used))
    with np.errstate(all="ignore"):
        dz = (sums / wsum).reshape(C, H2, W2)
    native = mean.astype(np.float32)
    up = np.stack([ndimage.zoom(native[..., ch], 2, order=1, grid_mode=True, mode="nearest") for ch in range(C)], 0)[:, :H2, :W2]
    holes = ~np.isfinite(dz) | (wsum.reshape(C, H2, W2) < 1e-3)
    dz = np.where(holes, up, dz)
    cov = np.repeat(np.repeat(np.isfinite(native).all(axis=-1).astype(np.int32) * len(used), 2, 0), 2, 1)
    return np.moveaxis(dz, 0, -1).astype(np.float32), cov, float(holes.mean())


# ----------------------------------------------------------------------------------------------- nights
def stack_sessions(frames: list[FrameInfo], opts: StackOptions, check: Callable[[], None], progress: Callable[[str, float], None]) -> StackResult:
    t0 = time.perf_counter()
    if len(frames) < 2:
        raise ProcessingError("TOO_FEW_FRAMES", "Combining nights needs at least two stacked images.")
    rep: dict[str, Any] = {"mode": "sessions", "frames_total": len(frames)}
    ref = max(range(len(frames)), key=lambda i: (frames[i].width * frames[i].height, frames[i].stack_count))
    H, W = frames[ref].height, frames[ref].width
    data, stars, stats, hdrs = [], [], [], []
    for n, f in enumerate(frames):
        check()
        img, hdr = read_frame(f)
        if img.ndim != 3:
            raise ProcessingError("NOT_RGB", f"{f.name} is not an RGB stacked image.")
        s, st = measure(img, "rgb")
        data.append(img)
        stars.append(st)
        stats.append(s)
        hdrs.append(hdr)
        progress(f"Measuring stacked images {n + 1}/{len(frames)}", 0.3 * (n + 1) / len(frames))
    ops = _Ops("cpu")
    warped, used, reasons = [], [], {}
    for n, f in enumerate(frames):
        check()
        expect = W / f.width
        if n == ref:
            t = IDENTITY
        else:
            m = match(stars[ref], stars[n], (expect * 0.9, expect * 1.1))
            if not m.ok:
                reasons[f.name] = m.reason
                continue
            t = m.transform  # type: ignore[assignment]
        w = ops.warp(data[n], t.inverse(), (H, W))
        bg = np.array([_robust(w[..., c][::4, ::4].ravel())[0] for c in range(3)])
        warped.append((n, w, bg))
        used.append(n)
        progress(f"Aligning stacked images {n + 1}/{len(frames)}", 0.3 + 0.5 * (n + 1) / len(frames))
    if len(used) < 2:
        raise ProcessingError("ALIGNMENT_FAILED", "The stacked images could not be aligned to each other; check that they show the same target.")
    ref_bg = next(bg for n, _, bg in warped if n == ref)
    stack = np.stack([w - (bg - ref_bg) for _, w, bg in warped], 0).astype(np.float32)
    integ = np.array([max((frames[n].exposure or 1.0) * frames[n].stack_count, 1e-6) for n in used])
    weights = integ / integ.mean()
    progress("Combining", 0.85)
    out, cov, rejected = _sigma_clip_combine(stack, weights, opts.kappa, opts.rejection == "sigma" and len(used) >= 3)
    rep.update({
        "reference": frames[ref].name, "frames_used": len(used),
        "rejected_frames": [{"name": k, "reason": v} for k, v in reasons.items()],
        "weights": {"method": "integration time (sub-frames x exposure)", "values": dict((frames[n].name, float(w)) for n, w in zip(used, weights))},
        "normalization": {"method": "additive per-channel background offset to the reference image", "reference_background": ref_bg.tolist()},
        "integration": {"method": "weighted mean" + (f", iterative kappa-sigma rejection (kappa {opts.kappa})" if len(used) >= 3 and opts.rejection == "sigma" else "")},
        "resampling": "bilinear onto the largest image's grid",
        "rejected_pixel_fraction": float(rejected) / max(1, stack.size), "seconds": round(time.perf_counter() - t0, 2),
    })
    cov_px = cov.min(axis=-1)
    out = np.where((cov_px > 0)[..., None], out, np.nan).astype(np.float32)
    hdr = _header_for(hdrs[ref], frames, used, "sessions", {})
    return StackResult(out, cov_px.astype(np.int32), hdr, rep)


def write_stack_fits(path, result: StackResult, history: list[str]) -> None:
    arr = result.data
    if arr.ndim == 3:
        arr = np.moveaxis(arr, -1, 0)
    hdu = fits.PrimaryHDU(data=np.ascontiguousarray(arr.astype(np.float32)), header=result.header)
    for line in history:
        hdu.header.add_history(line)
    hdu.writeto(path, overwrite=True, checksum=True)
