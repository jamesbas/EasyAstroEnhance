"""Cosmetic correction for a single linear stack (engine 1.6).

Only two kinds of isolated defects are repaired, and only on faint background:

* a *colored* hot pixel - one channel spikes far above its eight neighbours while the other channels do not (a hot
  photosite of one Bayer color that survived stacking). Stars are broadband, so a real star - even an undersampled one -
  rises in every channel and is never touched;
* a cold pixel - one value far below all its neighbours (a dead photosite or a stacking hole). A star cannot be darker
  than its surroundings.

The defective value is replaced by the median of its eight same-channel neighbours (the method the stacking path uses
for fixed defects). Pixels in bright structure (above the sky by ``BACKGROUND_SIGMAS``), saturated values, invalid or
protected pixels and pixels next to them are left alone. Every repaired pixel is counted in the report; nothing else changes.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .diagnostics import MAD_TO_SIGMA, strided
from .parallel import thread_map

K_SIGMA = 8.0  # excess over the neighbour median, in units of the channel's local-residual noise
ISOLATION = 0.25  # the brightest (or darkest) neighbour carries less than this share of the excess
COLOR_RATIO = 0.25  # the other channels' excess (in their own noise units) is below this share: a colored spike
BACKGROUND_SIGMAS = 10.0  # neighbourhood no brighter than sky + 10 sigma: faint background only
SATURATION_LEVEL = 0.999
BAND_ROWS = 256


def _neigh_stats(padded: np.ndarray, y0: int, y1: int, w: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Median, max and min of the eight neighbours for rows y0..y1 of the (1-pixel reflect-padded) channel."""
    nb = np.stack([padded[y0 + 1 + dy : y1 + 1 + dy, 1 + dx : 1 + dx + w] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx], 0)
    return np.median(nb, axis=0), nb.max(axis=0), nb.min(axis=0)


def find_defects(u: np.ndarray, weight: np.ndarray, threads: int = 1) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Return (mask H x W x C, neighbour-median values, info) for a shared-normalized linear stack ``u``."""
    u3 = u if u.ndim == 3 else u[..., None]
    h, w, c = u3.shape
    # a pixel qualifies only if it and all eight neighbours are valid and unprotected
    ok = weight.copy()
    pad_w = np.pad(weight, 1, mode="constant", constant_values=False)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ok &= pad_w[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
    bands = [(y, min(h, y + BAND_ROWS)) for y in range(0, h, BAND_ROWS)]
    med = np.empty_like(u3, dtype=np.float32)
    nmax = np.empty_like(med)
    nmin = np.empty_like(med)
    for k in range(c):
        padded = np.pad(u3[..., k], 1, mode="reflect")

        def band(b, k=k, padded=padded):
            y0, y1 = b
            med[y0:y1, :, k], nmax[y0:y1, :, k], nmin[y0:y1, :, k] = _neigh_stats(padded, y0, y1, w)

        thread_map(band, bands, threads)
    exc = u3 - med
    sig = np.empty(c, np.float64)
    sky = np.empty(c, np.float64)
    for k in range(c):
        e = strided(exc[..., k][ok]).astype(np.float64)
        sig[k] = max(float(np.median(np.abs(e - np.median(e))) * MAD_TO_SIGMA), 1e-9) if e.size else 1e-9
        sky[k] = float(np.median(strided(u3[..., k][ok]))) if ok.any() else 0.0
    z = exc / sig.astype(np.float32)
    background = med <= (sky + BACKGROUND_SIGMAS * sig).astype(np.float32)
    usable = ok[..., None] & background & (u3 < SATURATION_LEVEL) & (nmax < SATURATION_LEVEL)
    hot = usable & (z > K_SIGMA) & ((nmax - med) < ISOLATION * exc)
    if c == 3:  # colored: the other two channels rise by much less (in their own noise units)
        others = np.stack([np.maximum(z[..., (k + 1) % 3], z[..., (k + 2) % 3]) for k in range(3)], -1)
        hot &= others < COLOR_RATIO * z
    else:
        hot[:] = False  # monochrome: a single bright pixel cannot be told apart from an undersampled star
    cold = usable & (z < -K_SIGMA) & ((med - nmin) < ISOLATION * (-exc))
    mask = hot | cold
    info = {
        "method": "isolated one-pixel defects repaired with the median of the 8 same-channel neighbours; colored hot pixels "
                  "and cold pixels on faint background only (stars rise in every channel and are never touched)",
        "hot_colored": int(hot.any(axis=2).sum()), "cold": int(cold.any(axis=2).sum()), "values_repaired": int(mask.sum()),
        "thresholds": {"k_sigma": K_SIGMA, "isolation": ISOLATION, "color_ratio": COLOR_RATIO, "background_sigmas": BACKGROUND_SIGMAS},
    }
    if u.ndim == 2:
        return mask[..., 0], med[..., 0], info
    return mask, med, info


def correct(u: np.ndarray, weight: np.ndarray, threads: int = 1) -> tuple[np.ndarray, dict[str, Any]]:
    mask, med, info = find_defects(u, weight, threads)
    if not mask.any():
        return u, info
    out = u.copy()
    out[mask] = med[mask]
    return out, info
