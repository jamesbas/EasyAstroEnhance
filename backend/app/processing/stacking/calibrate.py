"""Calibration masters, cosmetic (defective-pixel) correction and bilinear debayering of raw sub-frames.

* Masters are pixel-wise medians. A master flat is calibrated by a dark-flat (or bias) master and normalized per
  Bayer site (each of the four colour positions to its own median), so it corrects vignetting/dust without
  changing colour balance.
* Defective pixels (hot/cold) are fixed sensor positions. They are found once — on the master dark when one is
  given, otherwise on a temporal median of a sample of lights (stars move between frames, defects do not) — as
  isolated spikes far from their same-colour neighbours, and in each frame only those pixels are replaced by the
  median of their same-colour neighbours (standard cosmetic correction; disclosed with a count).
* Debayering is bilinear (normalized convolution), the default of the free tools for smart-telescope data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage

from ..diagnostics import MAD_TO_SIGMA
from .frames import FrameInfo, read_frame

MAX_MASTER_FRAMES = 64
DEFECT_SAMPLE = 24
DEFECT_SIGMAS = 8.0
DEFECT_ISOLATION_SIGMAS = 4.0
MAX_DEFECT_FRACTION = 0.002
FLAT_FLOOR = 0.05
_SAME_COLOUR = [(-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (-2, 2), (2, -2), (2, 2)]
_ADJACENT = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def _subsample(frames: list[FrameInfo], n: int) -> list[FrameInfo]:
    if len(frames) <= n:
        return list(frames)
    idx = np.linspace(0, len(frames) - 1, n).round().astype(int)
    return [frames[i] for i in idx]


def median_master(frames: list[FrameInfo], check=None, subtract: np.ndarray | None = None) -> np.ndarray:
    use = _subsample(frames, MAX_MASTER_FRAMES)
    stack = []
    for f in use:
        if check:
            check()
        d, _ = read_frame(f)
        stack.append(d - subtract if subtract is not None else d)
    arr = np.stack(stack, axis=0)
    out = np.empty(arr.shape[1:], np.float32)
    rows = max(1, int(32_000_000 // max(1, arr[0].size // arr.shape[1] * len(stack))))
    for y0 in range(0, arr.shape[1], rows):  # bounded temporary memory
        out[y0 : y0 + rows] = np.median(arr[:, y0 : y0 + rows], axis=0)
    return out


def _sites(pattern: str | None) -> list[tuple[int, int]]:
    return [(0, 0), (0, 1), (1, 0), (1, 1)] if pattern else [(0, 0)]


def normalize_flat(flat: np.ndarray, pattern: str | None) -> tuple[np.ndarray, dict[str, Any]]:
    out = flat.astype(np.float32).copy()
    meds = []
    if pattern:
        for dy, dx in _sites(pattern):
            site = out[dy::2, dx::2]
            m = float(np.median(site))
            meds.append(m)
            out[dy::2, dx::2] = site / (m if m > 0 else 1.0)
    else:
        m = float(np.median(out))
        meds.append(m)
        out /= m if m > 0 else 1.0
    low = int((out < FLAT_FLOOR).sum())
    out = np.maximum(out, FLAT_FLOOR)
    return out, {"site_medians": meds, "min": float(out.min()), "max": float(out.max()), "floored_pixels": low}


@dataclass
class Calibration:
    dark: np.ndarray | None = None
    bias: np.ndarray | None = None
    flat: np.ndarray | None = None
    defects: tuple[np.ndarray, np.ndarray] | None = None
    pattern: str | None = None
    report: dict[str, Any] = field(default_factory=dict)

    def apply(self, raw: np.ndarray) -> np.ndarray:
        x = raw
        if self.dark is not None:
            x = x - self.dark
        elif self.bias is not None:
            x = x - self.bias
        if self.flat is not None:
            x = x / self.flat
        if self.defects is not None:
            x = repair_defects(x, self.defects)
        return x.astype(np.float32, copy=False)


def build_calibration(lights: list[FrameInfo], darks: list[FrameInfo], flats: list[FrameInfo], bias: list[FrameInfo],
                      darkflats: list[FrameInfo], check=None, progress=None) -> Calibration:
    ref = lights[0]
    pattern = ref.bayer if ref.layout == "cfa" else None
    cal = Calibration(pattern=pattern)
    rep: dict[str, Any] = {"darks": 0, "flats": 0, "bias": 0, "dark_flats": 0, "warnings": []}
    shape = (ref.height, ref.width)

    def compatible(group: list[FrameInfo], what: str) -> list[FrameInfo]:
        ok = [f for f in group if (f.height, f.width) == shape and f.layout == ref.layout]
        if len(ok) < len(group):
            rep["warnings"].append(f"{len(group) - len(ok)} {what} frame(s) ignored: size or colour layout differs from the lights.")
        return ok

    darks, flats, bias, darkflats = (compatible(g, w) for g, w in ((darks, "dark"), (flats, "flat"), (bias, "bias"), (darkflats, "dark-flat")))
    if bias:
        if progress:
            progress("Building master bias")
        cal.bias = median_master(bias, check)
        rep["bias"] = min(len(bias), MAX_MASTER_FRAMES)
    if darks:
        if progress:
            progress("Building master dark")
        cal.dark = median_master(darks, check)
        rep["darks"] = min(len(darks), MAX_MASTER_FRAMES)
        de = {round(f.exposure or 0, 2) for f in darks}
        le = {round(f.exposure or 0, 2) for f in lights}
        if de and le and de != le:
            rep["warnings"].append(f"Dark exposure {sorted(de)} s differs from the lights {sorted(le)} s; dark current may not match.")
    if flats:
        if progress:
            progress("Building master flat")
        sub = None
        if darkflats:
            sub = median_master(darkflats, check)
            rep["dark_flats"] = min(len(darkflats), MAX_MASTER_FRAMES)
        elif cal.bias is not None:
            sub = cal.bias
        else:
            rep["warnings"].append("Flats were used without dark-flats or bias; their offset is not removed (slight over-correction possible).")
        master = median_master(flats, check, subtract=sub)
        cal.flat, rep["flat"] = normalize_flat(master, pattern)
        rep["flats"] = min(len(flats), MAX_MASTER_FRAMES)
    if progress:
        progress("Finding defective pixels")
    if cal.dark is not None:
        source, src_name = cal.dark, "master dark"
    else:
        sample = _subsample(lights, DEFECT_SAMPLE)
        stack = []
        for f in sample:
            if check:
                check()
            d, _ = read_frame(f)
            if cal.bias is not None:
                d = d - cal.bias
            stack.append(d)
        source, src_name = np.median(np.stack(stack, 0), axis=0), f"temporal median of {len(sample)} lights"
    ys, xs, n_found = find_defects(source, pattern)
    cal.defects = (ys, xs) if ys.size else None
    rep["defective_pixels"] = {"count": int(ys.size), "found_candidates": n_found, "source": src_name,
                               "method": "isolated same-colour outliers (> 8 sigma, > 4 sigma above all adjacent pixels); replaced by the median of same-colour neighbours"}
    cal.report = rep
    return cal


def _shifted(img: np.ndarray, offsets) -> np.ndarray:
    p = np.pad(img, 2, mode="reflect")
    h, w = img.shape
    return np.stack([p[2 + dy : 2 + dy + h, 2 + dx : 2 + dx + w] for dy, dx in offsets], 0)


def find_defects(img: np.ndarray, pattern: str | None) -> tuple[np.ndarray, np.ndarray, int]:
    offs = _SAME_COLOUR if pattern else [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    neigh = _shifted(img, offs)
    med = np.median(neigh, axis=0)
    resid = img - med
    sig = float(np.median(np.abs(resid - np.median(resid))) * MAD_TO_SIGMA) or 1e-6
    adj = _shifted(img, _ADJACENT)
    hot = (resid > DEFECT_SIGMAS * sig) & (img - adj.max(axis=0) > DEFECT_ISOLATION_SIGMAS * sig)
    cold = (resid < -DEFECT_SIGMAS * sig) & (adj.min(axis=0) - img > DEFECT_ISOLATION_SIGMAS * sig)
    bad = hot | cold
    n = int(bad.sum())
    limit = int(MAX_DEFECT_FRACTION * img.size)
    if n > limit:  # keep only the most extreme; a huge count means the detection is unreliable on this data
        score = np.abs(resid) * bad
        thr = np.partition(score.ravel(), -limit)[-limit]
        bad = score >= max(thr, 1e-12)
    ys, xs = np.nonzero(bad)
    return ys.astype(np.int32), xs.astype(np.int32), n


def repair_defects(img: np.ndarray, defects: tuple[np.ndarray, np.ndarray], pattern_step: int = 2) -> np.ndarray:
    ys, xs = defects
    h, w = img.shape[:2]
    out = img.copy()
    vals = []
    for dy, dx in _SAME_COLOUR if pattern_step == 2 else _ADJACENT:
        yy = np.clip(ys + dy, 0, h - 1)
        xx = np.clip(xs + dx, 0, w - 1)
        vals.append(img[yy, xx])
    out[ys, xs] = np.median(np.stack(vals, 0), axis=0)
    return out


_K = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32)


def bayer_masks(pattern: str, h: int, w: int) -> dict[str, np.ndarray]:
    masks = {c: np.zeros((h, w), np.float32) for c in "RGB"}
    for i, ch in enumerate(pattern):
        dy, dx = divmod(i, 2)
        masks[ch][dy::2, dx::2] = 1.0
    return masks


def debayer(raw: np.ndarray, pattern: str) -> np.ndarray:
    """Bilinear demosaic: measured values kept, missing ones from same-colour neighbours (normalized convolution)."""
    h, w = raw.shape
    masks = bayer_masks(pattern, h, w)
    out = np.empty((h, w, 3), np.float32)
    for c, ch in enumerate("RGB"):
        m = masks[ch]
        num = ndimage.convolve(raw * m, _K, mode="mirror")
        den = ndimage.convolve(m, _K, mode="mirror")
        out[..., c] = np.where(m > 0, raw, num / np.maximum(den, 1e-6))
    return out
