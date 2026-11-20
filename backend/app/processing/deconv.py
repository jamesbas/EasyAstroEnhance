"""Optional Richardson-Lucy deconvolution of the linear luminance (off by default; Advanced only). Engine 1.7.

PSF: a circular **Moffat** profile ``(1 + (r/alpha)^2)^-beta`` fitted to the radial profiles of isolated, unsaturated
stars (Gaussian cores with extended wings, as real seeing and optics produce). The frame is also split into 3 x 3 zones
and the FWHM measured in each; the zones are reported, and one PSF is used for the whole frame (a spatially varying
deconvolution is not done).

Each iteration is the total-variation regularized Richardson-Lucy update (Dey et al. 2006):
``est *= (K^T * clip(L / (K * est), 0.5, 2)) / (1 - lambda * div(grad est / |grad est|))``, which damps the
amplification of noise. The result is blended in only where the signal is well above the sky noise (SNR gate) and away
from star cores; near stars it is limited to the local minimum and maximum of the input (deringing: no dark rings or
overshoot), and it is applied to RGB as a luminance ratio so colours are kept. A sharper appearance is not additional
measured resolution.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage
from scipy.optimize import curve_fit

from .tone import smoothstep

DEFAULT_ITERATIONS = 10
RATIO_CLAMP = (0.5, 2.0)
TV_FACTOR_CLAMP = (0.5, 2.0)
TV_LAMBDA = 0.002
MIN_STARS = 10
MIN_ZONE_STARS = 5
SNR_START = 3.0
SNR_RAMP = 7.0
KERNEL_FLOOR = 1e-3  # the kernel extends to where the Moffat profile falls below this fraction of its peak
MAX_KERNEL_RADIUS = 15
BETA_BOUNDS = (1.2, 10.0)


def moffat(r, alpha, beta):
    return (1.0 + (r / alpha) ** 2) ** (-beta)


def moffat_fwhm(alpha: float, beta: float) -> float:
    return 2.0 * alpha * math.sqrt(2.0 ** (1.0 / beta) - 1.0)


def moffat_kernel(alpha: float, beta: float) -> np.ndarray:
    r = math.ceil(alpha * math.sqrt(KERNEL_FLOOR ** (-1.0 / beta) - 1.0))
    r = int(min(max(r, 2), MAX_KERNEL_RADIUS))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float64)
    k = moffat(np.hypot(yy, xx), alpha, beta)
    return (k / k.sum()).astype(np.float32)


@dataclass(frozen=True)
class DeconvParams:
    alpha: float
    beta: float
    iterations: int
    sky: float
    noise: float
    stars_used: int
    zones: list[dict[str, Any]] = field(default_factory=list, compare=False)
    tv_lambda: float = TV_LAMBDA

    @property
    def kernel(self) -> np.ndarray:
        return moffat_kernel(self.alpha, self.beta)

    @property
    def fwhm(self) -> float:
        return moffat_fwhm(self.alpha, self.beta)

    @property
    def dering_radius(self) -> int:
        return max(1, int(math.ceil(self.fwhm / 2)))

    @property
    def halo(self) -> int:
        r = self.kernel.shape[0] // 2
        return self.iterations * (2 * r + 2) + 2 * self.dering_radius + int(4 * self.fwhm) + 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "Richardson-Lucy with total-variation regularization; Moffat PSF fitted to star profiles; damped ratio; "
                      "SNR-gated; star cores excluded; deringing (local min/max) near stars",
            "psf": {"model": "Moffat", "alpha_px": self.alpha, "beta": self.beta, "fwhm_px": self.fwhm,
                    "kernel_px": int(self.kernel.shape[0])},
            "psf_zones": self.zones, "spatially_varying": False,
            "iterations": self.iterations, "tv_lambda": self.tv_lambda, "ratio_clamp": list(RATIO_CLAMP),
            "snr_gate_sigmas": [SNR_START, SNR_START + SNR_RAMP], "stars_used": self.stars_used, "tile_halo_px": self.halo,
        }


def _star_profiles(L: np.ndarray, star_hard: np.ndarray, saturated: np.ndarray, limit: int = 400):
    """Radial samples (radius, value / peak) and centres of isolated, unsaturated stars."""
    labels, _ = ndimage.label(star_hard)
    rs, vs, centres = [], [], []
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        y0, y1 = max(0, sl[0].start - 6), min(L.shape[0], sl[0].stop + 6)
        x0, x1 = max(0, sl[1].start - 6), min(L.shape[1], sl[1].stop + 6)
        lab = labels[y0:y1, x0:x1]
        comp = lab == idx
        if (lab[lab > 0] != idx).any() or saturated[y0:y1, x0:x1][ndimage.binary_dilation(comp, iterations=2)].any() or comp.sum() < 5:
            continue  # blended with a neighbour, saturated or too small
        sub = L[y0:y1, x0:x1].astype(np.float64)
        ring = ndimage.binary_dilation(comp, iterations=5) & ~ndimage.binary_dilation(comp, iterations=3)
        if ring.sum() < 8:
            continue
        v = sub - np.median(sub[ring])
        core = np.where(comp, np.maximum(v, 0), 0)
        tot = core.sum()
        if tot <= 0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        cy, cx = (core * yy).sum() / tot, (core * xx).sum() / tot
        peak = v[comp].max()
        if peak <= 0:
            continue
        r = np.hypot(yy - cy, xx - cx).ravel()
        keep = r <= 8
        rs.append(r[keep])
        vs.append((v.ravel() / peak)[keep])
        centres.append((cy, cx))
        if len(centres) >= limit:
            break
    return rs, vs, centres


def _fit(rs: list[np.ndarray], vs: list[np.ndarray]) -> tuple[float, float] | None:
    if not rs:
        return None
    r, v = np.concatenate(rs), np.concatenate(vs)
    try:
        (alpha, beta), _ = curve_fit(moffat, r, v, p0=(2.0, 2.5), bounds=((0.3, BETA_BOUNDS[0]), (12.0, BETA_BOUNDS[1])), maxfev=4000)
    except (RuntimeError, ValueError):
        return None
    return float(alpha), float(beta)


def estimate_psf(L: np.ndarray, star_hard: np.ndarray | None, saturated: np.ndarray) -> tuple[tuple[float, float] | None, int, list[dict[str, Any]]]:
    """((alpha, beta) or None, stars used, per-zone FWHM diagnostics)."""
    if star_hard is None or not star_hard.any():
        return None, 0, []
    rs, vs, centres = _star_profiles(L, star_hard, saturated)
    if len(centres) < MIN_STARS:
        return None, len(centres), []
    fit = _fit(rs, vs)
    if fit is None:
        return None, len(centres), []
    h, w = L.shape
    zones = []
    for zy in range(3):
        for zx in range(3):
            idx = [i for i, (cy, cx) in enumerate(centres) if min(2, int(3 * cy / h)) == zy and min(2, int(3 * cx / w)) == zx]
            z: dict[str, Any] = {"zone": [zy, zx], "stars": len(idx)}
            if len(idx) >= MIN_ZONE_STARS:
                zf = _fit([rs[i] for i in idx], [vs[i] for i in idx])
                if zf:
                    z["fwhm_px"] = moffat_fwhm(*zf)
            zones.append(z)
    return fit, len(centres), zones


def _tv_factor(xp, est):
    """1 / (1 - lambda * div(grad est / |grad est|)), clamped (Dey et al. 2006)."""
    gx = xp.zeros_like(est)
    gy = xp.zeros_like(est)
    gx[:, :-1] = est[:, 1:] - est[:, :-1]
    gy[:-1, :] = est[1:, :] - est[:-1, :]
    norm = xp.sqrt(gx * gx + gy * gy) + 1e-6
    nx, ny = gx / norm, gy / norm
    div = xp.zeros_like(est)
    div[:, 1:] += nx[:, 1:] - nx[:, :-1]
    div[:, 0] += nx[:, 0]
    div[1:, :] += ny[1:, :] - ny[:-1, :]
    div[0, :] += ny[0, :]
    return xp.clip(1.0 / (1.0 - TV_LAMBDA * div), *TV_FACTOR_CLAMP)


def deconvolve(be, x, weight, star_soft, lum, p: DeconvParams):
    """``x``: linear data (positive pedestal); ``lum``: function(xp, x) -> luminance."""
    xp = be.xp
    L = xp.maximum(lum(xp, x), 1e-9)
    k = p.kernel
    kt = np.ascontiguousarray(k[::-1, ::-1])
    est = L
    lo, hi = RATIO_CLAMP
    for _ in range(p.iterations):
        conv = xp.maximum(be.convolve2d(est, k), 1e-9)
        est = est * be.convolve2d(xp.clip(L / conv, lo, hi), kt)
        if p.tv_lambda > 0:
            est = est * _tv_factor(xp, est)
    snr = (L - p.sky) / max(p.noise, 1e-12)
    gate = smoothstep(xp, (snr - SNR_START) / SNR_RAMP) * (1.0 - star_soft) * weight
    Lnew = L + gate * (est - L)
    # deringing near stars: never below the local minimum or above the local maximum of the input
    r = p.dering_radius
    near = xp.clip(be.gaussian(star_soft, p.fwhm) * 3.0, 0.0, 1.0)
    lo_l = be.erode_disk(L, r)
    hi_l = -be.erode_disk(-L, r)
    Lnew = Lnew + near * (xp.clip(Lnew, lo_l, hi_l) - Lnew)
    ratio = Lnew / L
    return x * ratio[..., None] if x.ndim == 3 else x * ratio
