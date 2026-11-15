"""Optional Richardson-Lucy deconvolution of the linear luminance (off by default; Advanced only).

PSF: a circular Gaussian whose sigma is the median second-moment size of isolated, unsaturated stars.
Each iteration ``est *= G * clip(L / (G * est), 0.5, 2)`` (multiplicative update with per-step damping).
The result is blended in only where the signal is well above the sky noise (SNR gate) and away from star
cores (where ringing and dark halos appear first), and applied to RGB as a luminance ratio so colors are
kept. A sharper appearance is not additional measured resolution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import ndimage

from .backends.base import kernel_radius
from .tone import smoothstep

DEFAULT_ITERATIONS = 10
RATIO_CLAMP = (0.5, 2.0)
MIN_STARS = 10
SNR_START = 3.0
SNR_RAMP = 7.0


@dataclass(frozen=True)
class DeconvParams:
    sigma_psf: float
    iterations: int
    sky: float
    noise: float
    stars_used: int

    @property
    def halo(self) -> int:
        return 2 * self.iterations * kernel_radius(self.sigma_psf) + 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "Richardson-Lucy, Gaussian PSF from star second moments, damped ratio, SNR-gated, star cores excluded",
            "psf_sigma_px": self.sigma_psf, "psf_fwhm_px": self.sigma_psf * 2.3548, "iterations": self.iterations,
            "ratio_clamp": list(RATIO_CLAMP), "snr_gate_sigmas": [SNR_START, SNR_START + SNR_RAMP], "stars_used": self.stars_used,
            "tile_halo_px": self.halo,
        }


def estimate_psf_sigma(L: np.ndarray, star_hard: np.ndarray | None, saturated: np.ndarray) -> tuple[float | None, int]:
    if star_hard is None or not star_hard.any():
        return None, 0
    labels, n = ndimage.label(star_hard)
    sizes = []
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        y0, y1 = max(0, sl[0].start - 4), min(L.shape[0], sl[0].stop + 4)
        x0, x1 = max(0, sl[1].start - 4), min(L.shape[1], sl[1].stop + 4)
        comp = ndimage.binary_dilation(labels[y0:y1, x0:x1] == idx, iterations=2)
        if saturated[y0:y1, x0:x1][comp].any() or comp.sum() < 9:
            continue
        sub = L[y0:y1, x0:x1]
        ring = ndimage.binary_dilation(comp, iterations=3) & ~comp
        if ring.sum() < 8:
            continue
        v = np.where(comp, sub - np.median(sub[ring]), 0.0)
        v = np.maximum(v, 0.0)
        tot = v.sum()
        if tot <= 0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        cy, cx = (v * yy).sum() / tot, (v * xx).sum() / tot
        var = ((v * ((yy - cy) ** 2 + (xx - cx) ** 2)).sum() / tot) / 2.0
        if var > 0:
            sizes.append(np.sqrt(var))
        if len(sizes) >= 500:
            break
    if len(sizes) < MIN_STARS:
        return None, len(sizes)
    return float(np.clip(np.median(sizes), 0.5, 4.0)), len(sizes)


def deconvolve(be, x, weight, star_soft, lum, p: DeconvParams):
    """``x``: linear data (positive pedestal); ``lum``: function(xp, x) -> luminance."""
    xp = be.xp
    L = xp.maximum(lum(xp, x), 1e-9)
    est = L
    lo, hi = RATIO_CLAMP
    for _ in range(p.iterations):
        conv = xp.maximum(be.gaussian(est, p.sigma_psf), 1e-9)
        est = est * be.gaussian(xp.clip(L / conv, lo, hi), p.sigma_psf)
    snr = (L - p.sky) / max(p.noise, 1e-12)
    gate = smoothstep(xp, (snr - SNR_START) / SNR_RAMP) * (1.0 - star_soft) * weight
    Lnew = L + gate * (est - L)
    ratio = Lnew / L
    return x * ratio[..., None] if x.ndim == 3 else x * ratio
