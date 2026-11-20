"""Row/column banding (walking noise) reduction for linear stacks (engine 1.7).

Banding shows up as whole rows or columns offset from their neighbours. Per channel, the mean of each row and each
column is taken over sky pixels only (within 3 sigma of the sky level, valid, outside low-coverage edges); the profile's
slow trend is removed (running median over 65 rows/columns, which keeps real large-scale structure and gradients out).
The noise expectation for such a mean accounts for the correlation that stacking interpolation gives neighbouring
pixels (measured from 4 x 4 block means). The profile is corrected only when its scatter exceeds that expectation by
``BANDING_SIGMAS`` and is at least ``MIN_RELATIVE`` of the pixel noise; the correction subtracts the detrended profile, an
additive offset per row (then per column) and channel that leaves every other structure in place.

Diagonal "walking noise" from a drifting mount is not modelled; Seestar alt-az stacks rotate the field, which smears it.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import ndimage

from .diagnostics import MAD_TO_SIGMA

DETREND = 65
BANDING_SIGMAS = 4.0
MIN_RELATIVE = 0.05
MIN_SKY_FRACTION = 0.2  # a row/column needs this share of sky pixels to be measured
BLOCK = 4


def _correlation_factor(ch: np.ndarray, sky: np.ndarray, s_pix: float) -> float:
    """How much more a mean of many pixels scatters than independent noise would (>= 1), from 4 x 4 block means."""
    h, w = ch.shape
    hb, wb = h // BLOCK * BLOCK, w // BLOCK * BLOCK
    blk = ch[:hb, :wb].reshape(hb // BLOCK, BLOCK, wb // BLOCK, BLOCK)
    full = sky[:hb, :wb].reshape(hb // BLOCK, BLOCK, wb // BLOCK, BLOCK).all(axis=(1, 3))
    means = blk.mean(axis=(1, 3))[full]
    if means.size < 100 or s_pix <= 0:
        return 1.0
    # remove slow structure before measuring the block scatter
    resid = means - np.median(means)
    s_blk = float(np.median(np.abs(resid - np.median(resid))) * MAD_TO_SIGMA)
    return float(max(1.0, s_blk / (s_pix / BLOCK)))


def _profile(c: np.ndarray, sky: np.ndarray, axis: int) -> tuple[np.ndarray, np.ndarray]:
    n = sky.sum(axis=axis)
    s = np.where(sky, c, 0.0).sum(axis=axis, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return s / n, n


def _detrended(mean: np.ndarray, n: np.ndarray, length: int) -> np.ndarray:
    ok = np.isfinite(mean) & (n >= MIN_SKY_FRACTION * length)
    if ok.sum() < DETREND:
        return np.zeros_like(mean)
    filled = np.interp(np.arange(len(mean)), np.nonzero(ok)[0], mean[ok])
    trend = ndimage.median_filter(filled, size=DETREND, mode="nearest")
    return np.where(ok, filled - trend, 0.0)


def reduce_banding(u: np.ndarray, weight: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    u3 = u if u.ndim == 3 else u[..., None]
    c = u3.shape[2]
    info: dict[str, Any] = {"method": "row/column means of sky pixels, detrended (65 px running median); offsets subtracted only "
                                      "when the profile scatter exceeds the (correlation-corrected) noise expectation",
                            "thresholds": {"sigmas_over_noise": BANDING_SIGMAS, "min_relative_to_pixel_noise": MIN_RELATIVE},
                            "axes": {}}
    out = u3.astype(np.float32, copy=True)
    applied = False
    for axis_name, axis in (("rows", 1), ("columns", 0)):
        axis_info = []
        length = u3.shape[1] if axis == 1 else u3.shape[0]
        for k in range(c):
            ch = out[..., k]
            v = ch[weight][:: max(1, int(weight.sum()) // 2_000_000)]
            med = float(np.median(v)) if v.size else 0.0
            s_pix = float(np.median(np.abs(v - med)) * MAD_TO_SIGMA) if v.size else 0.0
            sky = weight & (np.abs(ch - med) < 3.0 * s_pix) if s_pix > 0 else weight
            corr = _correlation_factor(ch, sky, s_pix)
            mean, n = _profile(ch, sky, axis)
            prof = _detrended(mean, n, length)
            measured = prof[n >= MIN_SKY_FRACTION * length]
            amp = float(np.median(np.abs(measured - np.median(measured))) * MAD_TO_SIGMA) if measured.size else 0.0
            n_typ = float(np.median(n[n > 0])) if (n > 0).any() else 1.0
            expected = s_pix * corr / np.sqrt(max(n_typ, 1.0))
            ok = s_pix > 0 and amp > BANDING_SIGMAS * expected and amp > MIN_RELATIVE * s_pix
            axis_info.append({"channel": k, "amplitude": amp, "expected_from_noise": expected, "noise_correlation_factor": corr,
                              "relative_to_pixel_noise": amp / s_pix if s_pix else 0.0, "corrected": bool(ok)})
            if ok:
                offs = prof.astype(np.float32)
                out[..., k] = ch - (offs[:, None] if axis == 1 else offs[None, :])
                applied = True
        info["axes"][axis_name] = axis_info
    info["applied"] = applied
    res = out if u.ndim == 3 else out[..., 0]
    res = np.where(weight[..., None] if u.ndim == 3 else weight, res, u).astype(u.dtype, copy=False)
    return res, info
