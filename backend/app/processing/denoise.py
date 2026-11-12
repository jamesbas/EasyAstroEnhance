"""Gentle luminance/chroma residual shrinkage with structure and star-edge protection.

Noise levels are *estimated globally on the CPU* (robust MAD of high-pass residuals over valid,
unprotected, non-star pixels) and passed in, so the pixel operation is tile- and backend-independent.
The estimate is approximate: resampling/stacking correlate noise, so it is not a calibrated SNR.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .backends.base import GAUSSIAN_TRUNCATE, kernel_radius
from .backends.numpy_backend import NumpyBackend
from .color import luminance
from .diagnostics import median_mad_sigma
from .masks import masked_gaussian

SIGMA_FINE = 0.8
SIGMA_CHROMA = 2.0
GATE_WIDTH = 2.5  # residuals beyond ~2.5 sigma are treated as structure and left alone
HALO = kernel_radius(SIGMA_CHROMA) + kernel_radius(SIGMA_FINE) + 2


@dataclass(frozen=True)
class DenoiseParams:
    amount: float
    sigma_residual: float
    sigma_chroma_residual: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "sigma_fine_px": SIGMA_FINE,
            "sigma_chroma_px": SIGMA_CHROMA,
            "gate_width_sigma": GATE_WIDTH,
            "noise_residual_sigma": self.sigma_residual,
            "chroma_residual_sigma": self.sigma_chroma_residual,
        }


def highpass_variance_factor(sigma: float) -> float:
    """Variance of (n - G*n) relative to white noise n for the discrete, truncated Gaussian G."""
    r = kernel_radius(sigma, GAUSSIAN_TRUNCATE)
    x = np.arange(-r, r + 1, dtype=np.float64)
    w = np.exp(-0.5 * (x / sigma) ** 2)
    w /= w.sum()
    return float(1.0 - 2.0 * w[r] ** 2 + (w**2).sum() ** 2)


def estimate_noise(
    x: np.ndarray, weight: np.ndarray, star_hard: np.ndarray | None, floor: float
) -> dict[str, float]:
    """Robust residual statistics on the CPU. ``floor`` is a data-scale-aware minimum (not a fixed 1/1024)."""
    be = NumpyBackend()
    L = luminance(np, x)
    w = weight.astype(np.float32)
    r = L - masked_gaussian(be, L, w, SIGMA_FINE)
    use = weight.copy()
    if star_hard is not None:
        use &= ~star_hard
    _, sigma_r = median_mad_sigma(r[use])
    out = {
        "sigma_residual": max(sigma_r, floor),
        "sigma_white_equivalent": max(sigma_r, floor) / np.sqrt(highpass_variance_factor(SIGMA_FINE)),
        "sigma_chroma_residual": 0.0,
    }
    if x.ndim == 3:
        c = x - L[..., None]
        rc = c - masked_gaussian(be, c, w, SIGMA_CHROMA)
        sig = [median_mad_sigma(rc[..., k][use])[1] for k in range(3)]
        out["sigma_chroma_residual"] = max(float(np.mean(sig)), floor)
    return out


def denoise(be, x, weight, star_soft, p: DenoiseParams):
    """x: H x W or H x W x 3; weight: H x W {0,1}; star_soft: H x W in [0,1] (0 where no star)."""
    xp = be.xp
    mono = x.ndim == 2
    L = luminance(xp, x)
    Ls = masked_gaussian(be, L, weight, SIGMA_FINE)
    r = L - Ls
    gate = xp.exp(-((r / (GATE_WIDTH * p.sigma_residual)) ** 2)) * (1.0 - star_soft) * weight
    L2 = L - p.amount * gate * r
    if mono:
        return xp.where(weight > 0, L2, x)
    c = x - L[..., None]
    # Chroma neighborhoods exclude star pixels so color is never smeared across star boundaries.
    w_c = weight * (1.0 - xp.clip(star_soft * 2.0, 0.0, 1.0))
    cs = masked_gaussian(be, c, w_c, SIGMA_CHROMA)
    rc = c - cs
    gate_c = xp.exp(-((rc / (GATE_WIDTH * p.sigma_chroma_residual)) ** 2)) * ((1.0 - star_soft) * weight)[..., None]
    amount_c = min(1.0, p.amount * 1.5)
    c2 = c - amount_c * gate_c * rc
    out = L2[..., None] + c2
    return xp.where((weight > 0)[..., None], out, x)
