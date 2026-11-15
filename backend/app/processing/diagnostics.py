"""Small robust-statistics and clipping helpers (CPU, deterministic)."""
from __future__ import annotations

from typing import Any

import numpy as np

MAD_TO_SIGMA = 1.4826  # 1 / 0.67449


def luminance_np(x: np.ndarray) -> np.ndarray:
    if x.ndim == 2:
        return x
    return x[..., 0] * np.float32(0.2126) + x[..., 1] * np.float32(0.7152) + x[..., 2] * np.float32(0.0722)


def strided(values: np.ndarray, max_n: int = 4_000_000) -> np.ndarray:
    """Deterministic subsample so global statistics stay fast and independent of tiling."""
    flat = values.reshape(-1)
    if flat.size <= max_n:
        return flat
    step = int(np.ceil(flat.size / max_n))
    return flat[::step]


def median_mad_sigma(values: np.ndarray) -> tuple[float, float]:
    v = strided(values).astype(np.float64, copy=False)
    if v.size == 0:
        return 0.0, 0.0
    med = float(np.median(v))
    return med, float(np.median(np.abs(v - med)) * MAD_TO_SIGMA)


def percentile(values: np.ndarray, q: float) -> float:
    v = strided(values)
    if v.size == 0:
        return 0.0
    return float(np.percentile(v, q))


def smoothstep_np(x: np.ndarray) -> np.ndarray:
    t = np.clip(x, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def clip_report(src, out_preclip, eligible, xp=np) -> dict[str, Any]:
    """Separate source clipping from *new* clipping using per-pixel transitions (not total counts).

    Invalid and protected pixels are excluded via ``eligible`` (H x W boolean). A color pixel that is already
    black (or saturated) in any channel of the source display counts as source clipping for all its channels,
    so dark defects and saturated star cores are not reported as new clipping. Works on NumPy or CuPy
    arrays (pass ``xp``); only small integer counts leave the device.
    """
    e = eligible if src.ndim == 2 else eligible[..., None]
    eb = xp.broadcast_to(e, src.shape)
    n = int(eb.sum())
    in_zero = (src <= 0.0) & eb
    in_max = (src >= 1.0) & eb
    out_zero = (out_preclip <= 0.0) & eb
    out_max = (out_preclip >= 1.0) & eb
    if src.ndim == 3:
        src_black = xp.broadcast_to((src <= 0.0).any(axis=-1, keepdims=True), src.shape)
        src_white = xp.broadcast_to((src >= 1.0).any(axis=-1, keepdims=True), src.shape)
    else:
        src_black, src_white = in_zero, in_max
    new_black = out_zero & ~src_black
    new_white = out_max & ~src_white
    c = lambda m: int(m.sum())  # noqa: E731
    return {
        "eligible_channel_values": n,
        "input_zero": c(in_zero),
        "input_max": c(in_max),
        "output_zero": c(out_zero),
        "output_max": c(out_max),
        "new_black": c(new_black),
        "new_white": c(new_white),
        "new_black_fraction": c(new_black) / n if n else 0.0,
        "new_white_fraction": c(new_white) / n if n else 0.0,
    }


def merge_clip_counts(parts: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ["eligible_channel_values", "input_zero", "input_max", "output_zero", "output_max", "new_black", "new_white"]
    total = {k: sum(p[k] for p in parts) for k in keys}
    n = total["eligible_channel_values"]
    total["new_black_fraction"] = total["new_black"] / n if n else 0.0
    total["new_white_fraction"] = total["new_white"] / n if n else 0.0
    return total
