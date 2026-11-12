"""Restrained, noise-aware local contrast on display luminance (display-only for linear sources).

An edge-aware coarse base (guided filter with Gaussian windows) is subtracted from a lightly smoothed
luminance to isolate medium-scale structure; that band is boosted by a bounded, signal-confidence-gated
amount. Scales are expressed in FULL-RESOLUTION pixels; previews never change the effective scale.
Not deconvolution and not a resolution gain.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .backends.base import kernel_radius
from .backends.numpy_backend import NumpyBackend
from .diagnostics import median_mad_sigma
from .masks import masked_gaussian
from .tone import smoothstep

SIGMA_FINE = 1.5
DEFAULT_SCALE_PX = 24.0
GUIDED_EPS = 0.05**2  # edges stronger than ~0.05 display units are preserved by the base
BOOST_CAP = 0.06
NOISE_FLOOR_SIGMAS = 1.0  # |band| below this many sigma is treated as noise
NOISE_RAMP_SIGMAS = 2.0


@dataclass(frozen=True)
class LocalContrastParams:
    amount: float
    scale_px: float
    sigma_band: float

    @property
    def halo(self) -> int:
        return 2 * kernel_radius(self.scale_px) + 2 * kernel_radius(SIGMA_FINE) + 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "coarse_scale_full_res_px": self.scale_px,
            "fine_sigma_px": SIGMA_FINE,
            "guided_eps": GUIDED_EPS,
            "boost_cap_display_units": BOOST_CAP,
            "noise_gate_sigma_floor": NOISE_FLOOR_SIGMAS,
            "noise_gate_sigma_ramp": NOISE_RAMP_SIGMAS,
            "band_noise_sigma": self.sigma_band,
            "tile_halo_px": self.halo,
        }


def guided_base(be, L, weight, scale_px: float):
    xp = be.xp
    fill = masked_gaussian(be, L, weight, scale_px)
    I = xp.where(weight > 0, L, fill)
    mean_i = be.gaussian(I, scale_px)
    mean_ii = be.gaussian(I * I, scale_px)
    var = xp.maximum(mean_ii - mean_i * mean_i, 0.0)
    a = var / (var + GUIDED_EPS)
    b = (1.0 - a) * mean_i
    return be.gaussian(a, scale_px) * I + be.gaussian(b, scale_px), I


def local_contrast_boost(be, L, weight, star_halo, p: LocalContrastParams):
    """Returns the additive luminance boost (zero in invalid/protected areas and near stellar halos)."""
    xp = be.xp
    base, I = guided_base(be, L, weight, p.scale_px)
    band = be.gaussian(I, SIGMA_FINE) - base
    band_s = be.gaussian(band, SIGMA_FINE)
    conf = smoothstep(xp, (xp.abs(band_s) - NOISE_FLOOR_SIGMAS * p.sigma_band) / (NOISE_RAMP_SIGMAS * p.sigma_band))
    boost = xp.clip(p.amount * conf * band_s, -BOOST_CAP, BOOST_CAP)
    return boost * weight * (1.0 - star_halo)


def estimate_band_sigma(L: np.ndarray, weight: np.ndarray, star_hard: np.ndarray | None, scale_px: float, floor: float) -> float:
    """Noise level of the medium-scale band from a deterministic set of sample tiles (tile-independent)."""
    be = NumpyBackend()
    h, w = L.shape
    halo = 2 * kernel_radius(scale_px) + 2 * kernel_radius(SIGMA_FINE) + 4
    size = 384
    ys = sorted({0, max(0, h // 2 - size // 2), max(0, h - size)})
    xs = sorted({0, max(0, w // 2 - size // 2), max(0, w - size)})
    samples = []
    for y0 in ys:
        for x0 in xs:
            oy0, oy1 = max(0, y0 - halo), min(h, y0 + size + halo)
            ox0, ox1 = max(0, x0 - halo), min(w, x0 + size + halo)
            wt = weight[oy0:oy1, ox0:ox1].astype(np.float32)
            if wt.mean() < 0.5:
                continue
            Lt = L[oy0:oy1, ox0:ox1].astype(np.float32)
            base, I = guided_base(be, Lt, wt, scale_px)
            band = be.gaussian(I, SIGMA_FINE) - base
            band_s = be.gaussian(band, SIGMA_FINE)
            iy0, ix0 = y0 - oy0, x0 - ox0
            sl = (slice(iy0, iy0 + min(size, h - y0)), slice(ix0, ix0 + min(size, w - x0)))
            use = weight[oy0:oy1, ox0:ox1][sl]
            if star_hard is not None:
                use = use & ~star_hard[oy0:oy1, ox0:ox1][sl]
            if use.any():
                samples.append(band_s[sl][use])
    if not samples:
        return floor
    _, sigma = median_mad_sigma(np.concatenate(samples))
    return max(sigma, floor)
