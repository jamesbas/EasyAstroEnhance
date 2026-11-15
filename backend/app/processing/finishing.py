"""Display-domain finishing stages (written against ``xp`` / ``Backend`` so CPU and GPU share them) and the
small CPU detectors that decide, per image, whether an automatic stage runs.

All stages are monotonic or bounded and operate only on existing pixel values:
* star blend - a gentler stretch inside the confident star mask (selective stretching; never removal/shrinking);
* HDR core compression - lowers only the large-scale base where it is bright, keeping fine structure;
* SCNR - average-neutral green removal with lightness preserved;
* pop - an S-curve anchored at the sky level and white (monotonic for amplitude <= 1);
* protected saturation - no boost in background noise or near white, never outside gamut;
* multiscale detail - à trous band boost gated by per-scale noise, suppressed near star halos.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import ndimage

from . import wavelets
from .backends.base import kernel_radius
from .color import _fit_factor, luminance
from .masks import masked_gaussian
from .tone import smoothstep

HDR_SIGMA = 24.0
HDR_THRESHOLD = 0.5
HDR_MAX_REDUCTION = 0.6
HDR_DETECT_LEVEL = 0.65
HDR_DETECT_FRACTION = 0.0005
SCNR_DETECT_EXCESS = 0.008
STAR_HALO_SIGMA = 6.0
DETAIL_GAIN = 1.5
DETAIL_CAP = 0.08
DETAIL_EDGE = 0.03  # local coefficient energy 0.03-0.06 display units: rolled off (real galaxy/nebula structure sits below ~0.03 at p90)
DETAIL_NOISE_START = 2.0  # coefficients below 2 sigma of their scale's noise are never boosted
DEFAULT_DETAIL_SCALE_PX = 16.0
SAT_HIGH_START = 0.85


def halo(detail_scales: int, hdr: bool) -> int:
    h = kernel_radius(STAR_HALO_SIGMA) + 2
    if detail_scales:
        h = max(h, wavelets.total_radius(detail_scales) + kernel_radius(STAR_HALO_SIGMA) + 4)
    if hdr:
        h = max(h, kernel_radius(HDR_SIGMA) + 4)
    return h


def star_halo_mask(be, star_soft):
    return be.xp.clip(be.gaussian(star_soft, STAR_HALO_SIGMA) * 2.0, 0.0, 1.0)


# ------------------------------------------------------------------------------------------------ stars
def star_blend(xp, y_full, y_gentle, star_soft, amount: float):
    s = amount * star_soft
    if y_full.ndim == 3:
        s = s[..., None]
    return y_full - s * (y_full - y_gentle)


# ------------------------------------------------------------------------------------------------ HDR
def hdr_compress(be, L, weight_nostar, amount: float):
    xp = be.xp
    base = masked_gaussian(be, L, weight_nostar, HDR_SIGMA)
    excess = xp.maximum(base - HDR_THRESHOLD, 0.0)
    ramp = smoothstep(xp, excess / (0.5 * (1.0 - HDR_THRESHOLD)))
    return L - amount * HDR_MAX_REDUCTION * ramp * excess


def detect_bright_core(Y: np.ndarray, weight_nostar: np.ndarray) -> tuple[bool, dict[str, Any]]:
    """A bright *extended* region (galaxy core, M42) exists when the smoothed, star-free display luminance exceeds
    ``HDR_DETECT_LEVEL`` over enough of the frame."""
    step = 4
    Ys = Y[::step, ::step].astype(np.float32)
    ws = weight_nostar[::step, ::step].astype(np.float32)
    num = ndimage.gaussian_filter(Ys * ws, HDR_SIGMA / step, mode="reflect")
    den = ndimage.gaussian_filter(ws, HDR_SIGMA / step, mode="reflect")
    base = np.where(den > 1e-3, num / np.maximum(den, 1e-3), 0.0)
    frac = float(((base > HDR_DETECT_LEVEL) & (ws > 0)).mean())
    return frac >= HDR_DETECT_FRACTION, {"bright_extended_fraction": frac, "level": HDR_DETECT_LEVEL, "min_fraction": HDR_DETECT_FRACTION}


# ------------------------------------------------------------------------------------------------ SCNR
def scnr(xp, y, amount: float):
    neutral = 0.5 * (y[..., 0] + y[..., 2])
    g = y[..., 1]
    g2 = g - amount * xp.maximum(g - neutral, 0.0)
    out = xp.stack([y[..., 0], g2, y[..., 2]], axis=-1)
    L0 = luminance(xp, y)
    L1 = luminance(xp, out)
    ratio = xp.clip(L0 / xp.maximum(L1, 1e-6), 1.0, 1.5)
    return out * ratio[..., None]


def green_excess(y: np.ndarray, use: np.ndarray, sky: float, sky_sigma: float) -> float:
    """Median green excess over pixels clearly above the sky (display units)."""
    if y.ndim != 3:
        return 0.0
    Y = luminance(np, y)
    sig = use & (Y > sky + 3.0 * max(sky_sigma, 1e-3))
    if sig.sum() < 100:
        sig = use
    if not sig.any():
        return 0.0
    ys = y[sig]
    return float(np.median(ys[:, 1] - 0.5 * (ys[:, 0] + ys[:, 2])))


# ------------------------------------------------------------------------------------------------ pop curve
def pop_curve(xp, L, sky: float, a: float):
    """S-curve on [sky, 1]: f(x) = x - a*x*(1-x)*(1-2x); identity at and below the sky and above white."""
    if a <= 0:
        return L
    x = (L - sky) / (1.0 - sky)
    inside = (x > 0.0) & (x < 1.0)
    xc = xp.clip(x, 0.0, 1.0)
    f = xc - a * xc * (1.0 - xc) * (1.0 - 2.0 * xc)
    return xp.where(inside, sky + f * (1.0 - sky), L)


# ------------------------------------------------------------------------------------------------ saturation
def protected_saturate(xp, y, amount: float, sky: float, sky_sigma: float):
    """Boost existing color about each pixel's luminance, faded in by signal above the sky noise and out near white;
    limited per pixel so no channel leaves [0, 1]."""
    if y.ndim == 2 or amount <= 1.0:
        return y
    ly = luminance(xp, y)
    lc = xp.clip(ly, 0.0, 1.0)
    d = y - ly[..., None]
    sd = max(sky_sigma, 0.005)
    fade = smoothstep(xp, (lc - (sky + sd)) / (3.0 * sd)) * (1.0 - smoothstep(xp, (lc - SAT_HIGH_START) / (1.0 - SAT_HIGH_START)))
    s_eff = 1.0 + (amount - 1.0) * fade
    fit = _fit_factor(xp, lc, d)
    f = xp.maximum(1.0, xp.minimum(s_eff, 1.0 + 0.95 * (fit - 1.0)))  # stay just inside the gamut: no channel lands on 0 or 1
    return ly[..., None] + f[..., None] * d


# ------------------------------------------------------------------------------------------------ detail
@dataclass(frozen=True)
class DetailParams:
    amount: float
    n_scales: int
    sigmas: tuple[float, ...]

    @property
    def halo(self) -> int:
        return wavelets.total_radius(self.n_scales) + kernel_radius(_energy_sigma(self.n_scales)) + kernel_radius(STAR_HALO_SIGMA) + 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "a trous detail planes boosted where above their noise (gate 1-3 sigma), suppressed near star halos",
            "amount": self.amount, "gain": DETAIL_GAIN * self.amount, "scales": self.n_scales,
            "largest_scale_full_res_px": 2 ** self.n_scales, "plane_noise_sigma": list(self.sigmas), "boost_cap_display_units": DETAIL_CAP,
            "edge_rolloff_display_units": DETAIL_EDGE, "tile_halo_px": self.halo,
        }


def scales_for(scale_px: float | None) -> int:
    s = float(scale_px or DEFAULT_DETAIL_SCALE_PX)
    return int(np.clip(round(np.log2(s)), 1, 6))


def _energy_sigma(j: int) -> float:
    return max(1.0, 2.0 ** (j - 1))


def detail_boost(be, L, weight, star_halo, p: DetailParams):
    xp = be.xp
    planes, _ = wavelets.decompose(xp, L, p.n_scales)
    boost = None
    for j, (w_j, s) in enumerate(zip(planes, p.sigmas), start=1):
        a = xp.abs(w_j)
        # local coefficient energy at this scale: the tails beside a hard edge inherit the edge's energy
        energy = xp.maximum(a, 2.0 * be.gaussian(a, _energy_sigma(j)))
        # boost structure that clears the noise but is not part of a hard edge (no halos beside sharp transitions)
        conf = smoothstep(xp, (a - DETAIL_NOISE_START * s) / (2.0 * s)) * (1.0 - smoothstep(xp, (energy - DETAIL_EDGE) / DETAIL_EDGE))
        term = conf * w_j
        boost = term if boost is None else boost + term
    boost = xp.clip(DETAIL_GAIN * p.amount * boost, -DETAIL_CAP, DETAIL_CAP)
    boost = xp.maximum(boost, -0.5 * xp.maximum(L, 0.0))  # never darkens a pixel by more than half (no new black specks)
    return boost * weight * (1.0 - star_halo)
