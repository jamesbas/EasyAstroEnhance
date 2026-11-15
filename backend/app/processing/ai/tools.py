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


def timed(info: AIStepInfo, fn):
    t0 = time.perf_counter()
    out = fn()
    info.seconds += time.perf_counter() - t0
    return out
