"""Multiscale (à trous wavelet) noise reduction with structure and star protection.

Each detail plane of the luminance and of the chroma is shrunk by a smooth gate
``1 - amount * exp(-(w / (k * sigma_j))**2) * (1 - star)``: coefficients that are small compared with the
measured noise of that scale are attenuated, coefficients well above it (structure, stars) pass unchanged.
The coarse residual is never modified, so large-scale brightness and flux are preserved. Chroma uses one more
scale than luminance to reach the low-frequency color mottling typical of stacked smart-telescope data.

Noise levels are *measured globally on the CPU* per scale (robust MAD over valid, unprotected, non-star
pixels of a deterministic set of sample tiles) and passed in, so the pixel operation is tile- and
backend-independent. Stacking/resampling correlate noise, so the estimate is approximate, not a calibrated SNR.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from . import wavelets
from .backends.base import GAUSSIAN_TRUNCATE, kernel_radius
from .backends.numpy_backend import NumpyBackend
from .color import luminance
from .diagnostics import median_mad_sigma
from .masks import masked_gaussian

SIGMA_FINE = 0.8  # residual scale used by the global noise estimate (reporting, background tools)
SIGMA_CHROMA = 2.0
GATE_K = 3.0  # coefficients beyond ~3 sigma of their scale are treated as structure
MAX_AMOUNT = 0.9  # the strongest setting still keeps 10% of the gated coefficients (no plastic look)
CHROMA_BOOST = 1.3
DEFAULT_SCALES = 4
FILL_SIGMA = 4.0
SAMPLE_TILE = 512


def halo(n_lum: int, n_chroma: int) -> int:
    return wavelets.total_radius(max(n_lum, n_chroma)) + kernel_radius(FILL_SIGMA) + 4


@dataclass(frozen=True)
class WaveletNoise:
    lum: tuple[float, ...]
    chroma: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"luminance_sigma_per_scale": list(self.lum), "chroma_sigma_per_scale": list(self.chroma)}


@dataclass(frozen=True)
class DenoiseParams:
    amount: float
    n_lum: int
    n_chroma: int
    noise: WaveletNoise
    gate_k: float = GATE_K

    @property
    def halo(self) -> int:
        return halo(self.n_lum, self.n_chroma)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "a trous B3-spline wavelets, gated shrinkage (luminance + chroma); coarse residual untouched",
            "amount": self.amount,
            "luminance_scales": self.n_lum,
            "chroma_scales": self.n_chroma,
            "chroma_amount": min(MAX_AMOUNT, self.amount * CHROMA_BOOST),
            "gate_width_sigma": self.gate_k,
            **self.noise.to_dict(),
            "tile_halo_px": self.halo,
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


def _sample_boxes(h: int, w: int, size: int) -> list[tuple[int, int]]:
    ys = sorted({max(0, h // 6 - size // 2), max(0, h // 2 - size // 2), max(0, 5 * h // 6 - size // 2)})
    xs = sorted({max(0, w // 6 - size // 2), max(0, w // 2 - size // 2), max(0, 5 * w // 6 - size // 2)})
    return [(y, x) for y in ys for x in xs]


def _fill(be, x, weight):
    xp = be.xp
    filled = masked_gaussian(be, x, weight, FILL_SIGMA)
    return xp.where((weight > 0)[..., None] if x.ndim == 3 else weight > 0, x, filled)


def estimate_wavelet_noise(
    x: np.ndarray, weight: np.ndarray, star_hard: np.ndarray | None, n_lum: int, n_chroma: int, floor: float
) -> WaveletNoise:
    """Per-scale noise of luminance and chroma detail planes from deterministic sample tiles (tile-independent)."""
    be = NumpyBackend()
    h, w = weight.shape
    pad = halo(n_lum, n_chroma)
    size = SAMPLE_TILE
    lum_samples: list[list[np.ndarray]] = [[] for _ in range(n_lum)]
    chr_samples: list[list[np.ndarray]] = [[] for _ in range(n_chroma)]
    for y0, x0 in _sample_boxes(h, w, size):
        oy0, oy1 = max(0, y0 - pad), min(h, y0 + size + pad)
        ox0, ox1 = max(0, x0 - pad), min(w, x0 + size + pad)
        wt = weight[oy0:oy1, ox0:ox1].astype(np.float32)
        if wt.mean() < 0.5:
            continue
        xt = _fill(be, x[oy0:oy1, ox0:ox1].astype(np.float32), wt)
        iy0, ix0 = y0 - oy0, x0 - ox0
        sl = (slice(iy0, iy0 + min(size, h - y0)), slice(ix0, ix0 + min(size, w - x0)))
        use = weight[oy0:oy1, ox0:ox1][sl]
        if star_hard is not None:
            use = use & ~star_hard[oy0:oy1, ox0:ox1][sl]
        if not use.any():
            continue
        L = luminance(np, xt)
        planes, _ = wavelets.decompose(np, L, n_lum)
        for j, p in enumerate(planes):
            lum_samples[j].append(p[sl][use])
        if xt.ndim == 3:
            planes_c, _ = wavelets.decompose(np, xt - L[..., None], n_chroma)
            for j, p in enumerate(planes_c):
                chr_samples[j].append(p[sl][use].reshape(-1))
    def sig(samples):
        if not samples:
            return floor
        v = np.concatenate(samples)
        return max(float(np.median(np.abs(v)) * 1.4826), floor)
    return WaveletNoise(tuple(sig(s) for s in lum_samples), tuple(sig(s) for s in chr_samples) if x.ndim == 3 else ())


def _shrink(xp, planes, sigmas, amount, k, star):
    out = []
    for p, s in zip(planes, sigmas):
        gate = xp.exp(-((p / (k * s)) ** 2))
        if star is not None:
            gate = gate * (1.0 - (star[..., None] if p.ndim == 3 else star))
        out.append(p * (1.0 - amount * gate))
    return out


def denoise(be, x, weight, star_soft, p: DenoiseParams):
    """x: H x W or H x W x 3; weight: H x W {0,1}; star_soft: H x W in [0,1] (0 where no star)."""
    xp = be.xp
    xf = _fill(be, x, weight)
    L = luminance(xp, xf)
    planes, resid = wavelets.decompose(xp, L, p.n_lum)
    planes = _shrink(xp, planes, p.noise.lum, p.amount, p.gate_k, star_soft)
    L2 = resid
    for q in planes:
        L2 = L2 + q
    if x.ndim == 2:
        return xp.where(weight > 0, L2, x)
    c = xf - L[..., None]
    planes_c, resid_c = wavelets.decompose(xp, c, p.n_chroma)
    amount_c = min(MAX_AMOUNT, p.amount * CHROMA_BOOST)
    planes_c = _shrink(xp, planes_c, p.noise.chroma, amount_c, p.gate_k, star_soft)
    c2 = resid_c
    for q in planes_c:
        c2 = c2 + q
    out = L2[..., None] + c2
    return xp.where((weight > 0)[..., None], out, x)


def denoise_params(noise_slider: float, scales: int | None, noise: WaveletNoise | None) -> DenoiseParams | None:
    if noise_slider <= 0 or noise is None:
        return None
    n_lum = int(scales or DEFAULT_SCALES)
    return DenoiseParams(amount=MAX_AMOUNT * float(noise_slider), n_lum=n_lum, n_chroma=min(6, n_lum + 1), noise=noise)
