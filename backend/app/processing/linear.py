"""Linear-data display rendering (separate from the processed-linear science-like array).

``u = (x - offset) / scale`` uses ONE shared scale/offset for every channel. The renderer is a
luminance-based asinh stretch::

    L = luminance(u)            # u for mono
    s = max(L - black, 0) / span
    t = asinh(k*s) / asinh(k)
    RGB_display = guarded_luminance_ratio(u, L, t)

Black, span and k are chosen robustly from valid, unprotected, non-star pixels, recorded, and for the
baseline comparison *frozen* from the source so both sides use the same mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .color import gamut_fit, luminance
from .diagnostics import median_mad_sigma, percentile
from .tone import asinh_map, smoothstep

BASELINE_K = 8.0


@dataclass(frozen=True)
class LinearFrame:
    """Frozen display mapping, in shared-normalized units."""

    scale: float
    offset: float
    black: float
    span: float
    k: float
    sky: float
    sigma_sky: float

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "LinearFrame":
        return LinearFrame(**{k: float(d[k]) for k in ("scale", "offset", "black", "span", "k", "sky", "sigma_sky")})


def derive_normalization(pixels: np.ndarray, weight: np.ndarray) -> tuple[float, float]:
    """Shared (offset, scale). Offset is 0 (preserves the physical zero point and negatives);
    scale is a high percentile of the valid values over all channels."""
    vals = pixels[weight] if pixels.ndim == 2 else pixels[weight].reshape(-1)
    if vals.size == 0:
        return 0.0, 1.0
    scale = percentile(vals, 99.5)
    if not np.isfinite(scale) or scale <= 0:
        scale = float(np.std(vals.astype(np.float64))) or 1.0
    return 0.0, float(scale)


def derive_frame(
    u: np.ndarray, weight: np.ndarray, star_hard: np.ndarray | None, offset: float, scale: float, k: float,
    black_sigmas: float = 1.0, white_percentile: float = 99.5,
) -> LinearFrame:
    L = luminance(np, u)
    Lw = L[weight]
    if Lw.size == 0:
        return LinearFrame(scale, offset, 0.0, 1.0, k, 0.0, 0.0)
    sky = float(np.median(Lw))
    below = sky - Lw[Lw < sky]
    sigma = float(np.median(below) * 1.4826) if below.size else median_mad_sigma(Lw)[1]
    black = sky - black_sigmas * sigma
    use = weight & ~star_hard if star_hard is not None else weight
    s_vals = L[use] - black
    span = percentile(s_vals, white_percentile) if s_vals.size else float(Lw.max() - black)
    if not np.isfinite(span) or span <= max(sigma * 3, 1e-12):
        span = max(float(Lw.max() - black), sigma * 3, 1e-12)
    return LinearFrame(scale, offset, float(black), float(span), float(k), sky, float(sigma))


def fixed_map(xp, u, frame: LinearFrame, k: float | None = None):
    """Map normalized linear data to display. Returns (display, t) where ``t`` is the target display
    luminance. Negative physical values map to black in the display only; they are untouched in ``u``."""
    k = frame.k if k is None else k
    L = luminance(xp, u)
    s = xp.maximum(L - frame.black, 0.0) / frame.span
    t = asinh_map(xp, s, k)
    if u.ndim == 2:
        return xp.clip(t, 0.0, 1.0), t
    denom = xp.maximum(L - frame.black, 1e-12)
    ratio = xp.clip((u - frame.black) / denom[..., None], 0.0, 4.0)
    # Pixels within ~3 sigma of the black level carry no reliable color; blend toward neutral.
    conf = smoothstep(xp, (L - frame.black) / max(3.0 * frame.sigma_sky, 1e-3 * frame.span))[..., None]
    ratio = conf * ratio + (1.0 - conf)
    rgb = t[..., None] * ratio
    return gamut_fit(xp, rgb), t


def to_normalized(pixels: np.ndarray, offset: float, scale: float) -> np.ndarray:
    return ((pixels.astype(np.float64) - offset) / scale).astype(np.float32)


def from_normalized(u: np.ndarray, offset: float, scale: float, dtype) -> np.ndarray:
    return (u.astype(np.float64) * scale + offset).astype(dtype)
