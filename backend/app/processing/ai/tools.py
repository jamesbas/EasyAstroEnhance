"""The three optional AI tools, each fed exactly as its model was trained (see the reference implementations cited).

* ``ai_background`` — GraXpert background extraction (graxpert/background_extraction.py, "AI" mode): the whole frame
  shrunk to 240 px + 8 px edge padding, per-channel (x - median) / MAD * 0.04 clipped to +-1; the predicted background
  is mapped back, blurred (sigma 3 at 240 px) and enlarged. Returned zero-median per channel (it replaces the classical
  gradient model and is subtracted the same way).
* ``ai_denoise`` — GraXpert denoising 3.x (graxpert/denoising.py): global per-channel median/MAD normalization (* 0.04),
  256 px tiles, stride 128, centre-crop stitching; pixels above 10 normalized units (star cores) pass through
  unchanged; ``strength`` blends with the input.
* ``separate_stars`` — Cosmic Clarity Dark Star (setiastrocosmicclarity_darkstar.py): an unlinked per-channel midtone
  stretch to a median of 0.25 (only when the data are dark), a large-scale median background taken out so a bright
  galaxy bulge is not mistaken for a star, 256 px tiles, then the exact inverse stretch. Stars are
  ``input - starless`` (never negative) with any structure wider than a star returned to the starless layer, so
  ``starless + stars`` reproduces the input exactly.

Invalid (masked) pixels are filled with the channel median for inference and restored afterwards.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from scipy import ndimage

from .registry import ModelSpec
from .tiles import resize_linear, tile_apply

NORM = 0.04
BGE_SIZE, BGE_PAD, BGE_BLUR = 256, 8, 3.0
DN_WINDOW, DN_STRIDE, DN_THRESHOLD, DN_BATCH = 256, 128, 10.0, 4
DS_TARGET_MEDIAN, DS_STRETCH_BELOW, DS_MARGIN, DS_OVERLAP, DS_BATCH = 0.25, 0.125, 8, 32, 4
DS_GATE_MIN, DS_GATE_MAX = 15, 41


@dataclass
class AIStepInfo:
    model: ModelSpec
    provider: str = ""
    seconds: float = 0.0
    fallbacks: list[dict[str, str]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        m = self.model
        return {
            "model": {"id": m.id, "title": m.title, "file": m.file, "version": m.version, "sha256": m.sha256, "license": m.license,
                      "attribution": m.attribution, "source": m.source},
            "execution_provider": self.provider, "seconds": round(self.seconds, 3), "fallbacks": self.fallbacks, **self.params,
            "kind": "learned (AI) processing: a trained neural network predicts these pixel values",
        }


def _as3(x: np.ndarray) -> np.ndarray:
    return x if x.ndim == 3 else x[..., None]


def _channel_stats(img: np.ndarray, valid: np.ndarray, step: int = 4) -> tuple[np.ndarray, np.ndarray]:
    sub, vs = img[::step, ::step], valid[::step, ::step]
    vals = sub[vs] if vs.any() else sub.reshape(-1, img.shape[2])
    med = np.median(vals, axis=0)
    mad = np.median(np.abs(vals - med), axis=0)
    fallback = np.std(vals, axis=0) * 0.6745
    mad = np.where(mad > 0, mad, np.where(fallback > 0, fallback, 1e-6))
    return med.astype(np.float32), mad.astype(np.float32)


def _filled(img: np.ndarray, valid: np.ndarray, fill: np.ndarray) -> np.ndarray:
    return img if valid.all() else np.where(valid[..., None], img, fill.reshape(1, 1, -1)).astype(np.float32)


def _rgb3(a: np.ndarray) -> np.ndarray:
    return a if a.shape[2] == 3 else np.repeat(a[..., :1], 3, axis=2)


# ---------------------------------------------------------------------------------------------- background
def ai_background(x: np.ndarray, valid: np.ndarray, run: Callable[[np.ndarray], np.ndarray]) -> tuple[np.ndarray, dict[str, Any]]:
    img = _as3(x).astype(np.float32)
    h, w, c = img.shape
    med_full, _ = _channel_stats(img, valid)
    img = _filled(img, valid, med_full)
    inner = BGE_SIZE - 2 * BGE_PAD
    small = np.pad(resize_linear(img, inner, inner), ((BGE_PAD, BGE_PAD), (BGE_PAD, BGE_PAD), (0, 0)), mode="edge")
    med = np.median(small.reshape(-1, c), axis=0)
    mad = np.median(np.abs(small.reshape(-1, c) - med), axis=0)
    mad = np.where(mad > 0, mad, 1e-6).astype(np.float32)
    norm = np.clip((small - med) / mad * NORM, -1.0, 1.0)
    out = run(_rgb3(norm)[None].astype(np.float32))[0][..., :c]
    bg = out / NORM * mad + med
    bg = bg[BGE_PAD:-BGE_PAD, BGE_PAD:-BGE_PAD]
    bg = np.stack([ndimage.gaussian_filter(bg[..., k], BGE_BLUR, mode="mirror", truncate=5.0 / BGE_BLUR) for k in range(c)], -1)
    full = resize_linear(bg, h, w)
    zero = np.median(full[valid] if valid.any() else full.reshape(-1, c), axis=0)
    full = (full - zero).astype(np.float32)
    lo, hi = np.percentile(full[::4, ::4].reshape(-1, c), [1, 99], axis=0)
    info = {"model_input_px": BGE_SIZE, "amplitude_per_channel": (hi - lo).tolist(), "subtracted": "zero-median per channel"}
    return (full if x.ndim == 3 else full[..., 0]), info


# ---------------------------------------------------------------------------------------------- denoise
def ai_denoise(x: np.ndarray, valid: np.ndarray, strength: float, run: Callable[[np.ndarray], np.ndarray],
               check: Callable[[], None] | None = None, progress: Callable[[float], None] | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    img = _as3(x).astype(np.float32)
    c = img.shape[2]
    med, mad = _channel_stats(img, valid)
    norm = (_filled(img, valid, med) - med) / mad * NORM
    model_in = _rgb3(np.clip(norm, -DN_THRESHOLD, DN_THRESHOLD))
    margin = (DN_WINDOW - DN_STRIDE) // 2
    out = tile_apply(model_in, run, DN_WINDOW, DN_STRIDE, margin, DN_BATCH, check, progress)[..., :c]
    den = np.where(norm < DN_THRESHOLD, out / NORM * mad + med, img)  # bright cores: the original values, exactly
    s = float(np.clip(strength, 0.0, 1.0))
    res = den * s + img * (1.0 - s)
    res = np.where(valid[..., None], res, img).astype(np.float32)
    passed = float((norm >= DN_THRESHOLD).any(axis=2)[valid].mean()) if valid.any() else 0.0
    info = {"strength": s, "tile_px": DN_WINDOW, "stride_px": DN_STRIDE, "bright_pixels_passed_through_fraction": passed,
            "normalization": "per-channel (x - median) / MAD * 0.04 (GraXpert)"}
    return (res if x.ndim == 3 else res[..., 0]), info


# ---------------------------------------------------------------------------------------------- stars
def _midtone_for(med: np.ndarray, target: float) -> np.ndarray:
    """MTF midtone parameter m with mtf(m, med) == target."""
    med = np.clip(med, 1e-6, 1 - 1e-6)
    return med * (1.0 - target) / (med - 2.0 * target * med + target)


def _mtf(m: np.ndarray, x: np.ndarray) -> np.ndarray:
    den = (2.0 * m - 1.0) * x - m
    den = np.where(np.abs(den) < 1e-12, -1e-12, den)
    return (m - 1.0) * x / den


def separate_stars(x: np.ndarray, valid: np.ndarray, run: Callable[[np.ndarray], np.ndarray], tile: int,
                   check: Callable[[], None] | None = None, progress: Callable[[float], None] | None = None) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    img = _as3(x).astype(np.float32)
    h, w, c = img.shape
    v = valid if valid.any() else np.ones(valid.shape, bool)
    lo = np.min(img[v], axis=0)
    hi = np.maximum(np.max(img[v], axis=0), lo + 1e-6)
    r = np.clip((img - lo) / (hi - lo), 0.0, 1.0)
    med = np.median(r[::2, ::2][v[::2, ::2]], axis=0)
    stretched = bool(np.median(med) < DS_STRETCH_BELOW)
    m = _midtone_for(med, DS_TARGET_MEDIAN) if stretched else None
    s = _mtf(m, r) if stretched else r
    s = _filled(s.astype(np.float32), valid, np.median(s[v], axis=0))
    # The network mistakes a large, nearly saturated region (a galaxy bulge) for a giant star. The part of a large-scale
    # median background (no star survives a 64 px median) above the sky level is taken out before inference and put back
    # afterwards, so the model sees stars on a flat sky (never pushed above 1).
    level = np.median(s[::7, ::7].reshape(-1, c), axis=0)
    lift = np.maximum(_large_scale(s) - level, 0.0)
    model_in = np.clip(s - lift, 0.0, 1.0)
    out = tile_apply(_rgb3(model_in), run, tile, tile - 2 * DS_MARGIN - DS_OVERLAP, DS_MARGIN, DS_BATCH, check, progress)[..., :c]
    out = np.clip(out + lift, 0.0, 1.0)
    out = np.minimum(out, s)
    if stretched:
        out = _mtf(1.0 - m, out)  # exact inverse of the stretch
    starless = out * (hi - lo) + lo
    stars = np.clip(img - starless, 0.0, None)
    # Safety net: anything in the star layer wider than any star goes back to the starless layer.
    k = int(np.clip(round(max(h, w) / 150) | 1, DS_GATE_MIN, DS_GATE_MAX))
    extended = np.stack([ndimage.grey_opening(stars[..., i], size=(k, k)) for i in range(c)], -1)
    extended = np.minimum(np.stack([ndimage.gaussian_filter(extended[..., i], k / 6.0) for i in range(c)], -1), stars)
    stars = np.where(valid[..., None], stars - extended, 0.0).astype(np.float32)
    starless = (img - stars).astype(np.float32)
    total = float(np.sum(np.clip(img[v] - np.median(img[v], axis=0), 0, None)))
    info = {"tile_px": tile, "overlap_px": DS_OVERLAP,
            "temporary_stretch": "unlinked midtone stretch to median 0.25, inverted exactly" if stretched else "none (data already bright)",
            "flattening": "64 px median background removed before inference and restored after",
            "extended_structure_gate_px": k,
            "star_flux_fraction": float(stars[v].sum()) / total if total > 0 else 0.0,
            "recombination": "stars are input minus starless (never negative), so starless + stars equals the input"}
    if x.ndim == 2:
        return starless[..., 0], stars[..., 0], info
    return starless, stars, info


def _large_scale(s: np.ndarray) -> np.ndarray:
    h, w, c = s.shape
    small = np.stack([ndimage.median_filter(s[::4, ::4, i], size=17, mode="nearest") for i in range(c)], -1)
    small = np.stack([ndimage.gaussian_filter(small[..., i], 2.0, mode="nearest") for i in range(c)], -1)
    return resize_linear(small, h, w)


# ---------------------------------------------------------------------------------------------- sharpen
# Cosmic Clarity Sharpen (SetiAstroCosmicClarity.py, luminance mode "Both"): 16 px median border; unlinked midtone
# stretch to median 0.25 when the data are dark (median < 0.08); BT.601 luminance; 256 px chunks with 64 px overlap whose
# 16 px borders are ignored and overlaps averaged; stellar model first, blended by its amount; then the non-stellar model
# (radius 1/2/4/8, interpolated between the two nearest) on that result, blended by its amount; chrominance restored.
CC_TILE, CC_OVERLAP, CC_BORDER, CC_BATCH = 256, 64, 16, 4
CC_STRETCH_BELOW = 0.08
CC_RADII = (1, 2, 4, 8)


def cc_radius_models(radius: float) -> tuple[tuple[int, int], float]:
    """The two non-stellar models around ``radius`` (clamped to 1..8) and the interpolation weight of the larger."""
    r = float(np.clip(radius, CC_RADII[0], CC_RADII[-1]))
    for lo, hi in zip(CC_RADII, CC_RADII[1:]):
        if r <= hi:
            return ((lo, hi), (r - lo) / (hi - lo)) if r > lo else ((lo, lo), 0.0)
    return (CC_RADII[-1], CC_RADII[-1]), 0.0


def _cc_stitch(plane: np.ndarray, run: Callable[[np.ndarray], np.ndarray], check=None, progress=None) -> np.ndarray:
    h, w = plane.shape
    step = CC_TILE - CC_OVERLAP
    coords = [(i, j) for i in range(0, h, step) for j in range(0, w, step)]
    acc = np.zeros((h, w), np.float32)
    wsum = np.zeros((h, w), np.float32)
    for k in range(0, len(coords), CC_BATCH):
        if check:
            check()
        group = coords[k: k + CC_BATCH]
        batch = np.zeros((len(group), CC_TILE, CC_TILE, 3), np.float32)
        sizes = []
        for n, (i, j) in enumerate(group):
            chunk = plane[i:i + CC_TILE, j:j + CC_TILE]
            batch[n, :chunk.shape[0], :chunk.shape[1], :] = chunk[..., None]
            sizes.append(chunk.shape)
        out = run(batch)[..., 0]
        for (i, j), (ch, cw), o in zip(group, sizes, out):
            bh, bw = min(CC_BORDER, ch // 2), min(CC_BORDER, cw // 2)
            acc[i + bh:i + ch - bh, j + bw:j + cw - bw] += o[bh:ch - bh, bw:cw - bw]
            wsum[i + bh:i + ch - bh, j + bw:j + cw - bw] += 1
        if progress:
            progress(min(1.0, (k + len(group)) / len(coords)))
    return acc / np.maximum(wsum, 1)


def sharpen(x: np.ndarray, valid: np.ndarray, stellar: Callable | None, nonstellar: dict[int, Callable], radius: float,
            stellar_amount: float, nonstellar_amount: float, check=None, progress=None) -> tuple[np.ndarray, dict[str, Any]]:
    img = _as3(x).astype(np.float32)
    c = img.shape[2]
    v = valid if valid.any() else np.ones(valid.shape, bool)
    lo = float(np.min(img[v]))
    hi = max(float(np.max(img[v])), lo + 1e-6)
    r = np.clip((img - lo) / (hi - lo), 0.0, 1.0)
    r = _filled(r, valid, np.median(r[v], axis=0))
    r = np.pad(r, ((CC_BORDER, CC_BORDER), (CC_BORDER, CC_BORDER), (0, 0)), mode="constant", constant_values=float(np.median(r)))
    stretched = bool(np.median(r - r.min()) < CC_STRETCH_BELOW)
    m = _midtone_for(np.median(r, axis=(0, 1)), 0.25) if stretched else None
    s = _mtf(m, r) if stretched else r
    if c == 3:
        Y = 0.299 * s[..., 0] + 0.587 * s[..., 1] + 0.114 * s[..., 2]
        Cb = -0.168736 * s[..., 0] - 0.331264 * s[..., 1] + 0.5 * s[..., 2]
        Cr = 0.5 * s[..., 0] - 0.418688 * s[..., 1] - 0.081312 * s[..., 2]
    else:
        Y = s[..., 0]
    passes = (1 if stellar is not None and stellar_amount > 0 else 0) + (1 if nonstellar_amount > 0 else 0) * len(set(nonstellar))
    done = [0]

    def sub_progress(f: float) -> None:
        if progress:
            progress(min(1.0, (done[0] + f) / max(passes, 1)))

    if stellar is not None and stellar_amount > 0:
        Y = Y + stellar_amount * (_cc_stitch(Y, stellar, check, sub_progress) - Y)
        done[0] += 1
    (rlo, rhi), wt = cc_radius_models(radius)
    if nonstellar_amount > 0:
        out = _cc_stitch(Y, nonstellar[rlo], check, sub_progress)
        done[0] += 1
        if rhi != rlo:
            out = (1 - wt) * out + wt * _cc_stitch(Y, nonstellar[rhi], check, sub_progress)
            done[0] += 1
        Y = Y + nonstellar_amount * (out - Y)
    Y = np.clip(Y, 0.0, 1.0)
    if c == 3:
        rgb = np.stack([Y + 1.402 * Cr, Y - 0.344136 * Cb - 0.714136 * Cr, Y + 1.772 * Cb], -1)
        out_s = np.clip(rgb, 0.0, 1.0)
    else:
        out_s = Y[..., None]
    if stretched:
        out_s = _mtf(1.0 - m, out_s)  # exact inverse of the stretch
    out_s = out_s[CC_BORDER:-CC_BORDER, CC_BORDER:-CC_BORDER]
    res = (out_s * (hi - lo) + lo).astype(np.float32)
    res = np.where(valid[..., None], res, img).astype(np.float32)
    info = {"tile_px": CC_TILE, "overlap_px": CC_OVERLAP, "ignored_tile_border_px": CC_BORDER,
            "temporary_stretch": "unlinked midtone stretch to median 0.25, inverted exactly" if stretched else "none (data already bright)",
            "channels": "BT.601 luminance only (chrominance kept)" if c == 3 else "monochrome",
            "stellar_amount": stellar_amount if stellar is not None else 0.0, "nonstellar_amount": nonstellar_amount,
            "nonstellar_radius": float(np.clip(radius, 1, 8)), "nonstellar_models": [rlo, rhi] if rhi != rlo else [rlo],
            "interpolation_weight": wt}
    return (res if x.ndim == 3 else res[..., 0]), info


def timed(info: AIStepInfo, fn):
    t0 = time.perf_counter()
    out = fn()
    info.seconds += time.perf_counter() - t0
    return out
