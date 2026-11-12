"""Conservative detection of compact stellar sources and the soft mask used to limit *additional*
brightening during the stretch. This is selective stretching, not star subtraction, shrinking,
reconstruction or replacement. Detection is global (connected components are never tiled).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage

from .backends.numpy_backend import NumpyBackend
from .color import luminance
from .diagnostics import median_mad_sigma
from .masks import masked_gaussian

SETTINGS = {
    "background_sigma_px": 16.0,
    "threshold_sigma": 5.0,
    "min_peak_sigma": 8.0,
    "min_area_px": 3,
    "max_area_px": 2000,
    "max_axis_ratio": 2.5,
    "min_solidity": 0.5,
    "max_mean_over_peak": 0.75,
    "annulus_inner_radii": 2.0,
    "annulus_outer_radii": 3.5,
    "max_annulus_fraction": 0.35,
    "dilate_px": 3,
    "feather_sigma_px": 2.5,
    "min_stars": 5,
    "max_components": 20000,
    "max_mask_coverage": 0.2,
}


@dataclass
class StarMask:
    soft: np.ndarray | None  # float32 0..1, None when unreliable
    hard: np.ndarray | None  # bool accepted star pixels
    reliable: bool
    stats: dict[str, Any] = field(default_factory=dict)


def detect_stars(x: np.ndarray, weight: np.ndarray, floor: float) -> StarMask:
    """``x``: H x W or H x W x 3 work array (display or shared-normalized linear); ``weight``: bool H x W."""
    s = SETTINGS
    be = NumpyBackend()
    L = luminance(np, x).astype(np.float32)
    w = weight.astype(np.float32)
    med, sig = median_mad_sigma(L[weight])
    sig = max(sig, floor)
    clipped = np.minimum(L, med + 3.0 * sig)  # exclude stars/structure from the background estimate
    bg = masked_gaussian(be, clipped, w, s["background_sigma_px"])
    resid = L - bg
    _, sigma_n = median_mad_sigma(resid[weight])
    sigma_n = max(sigma_n, floor)
    cand = (resid > s["threshold_sigma"] * sigma_n) & weight
    labels, n = ndimage.label(cand, structure=np.ones((3, 3), dtype=bool))
    stats: dict[str, Any] = {
        "settings": dict(s),
        "components": int(n),
        "noise_sigma": sigma_n,
        "rejected": {"too_small": 0, "too_large": 0, "elongated": 0, "low_solidity": 0, "faint": 0, "broad_core": 0, "embedded_in_structure": 0},
    }
    if n == 0 or n > s["max_components"]:
        stats["accepted"] = 0
        stats["reason"] = "no compact sources found" if n == 0 else "too many candidate components (noise-dominated); detection unreliable"
        return StarMask(None, None, False, stats)

    objects = ndimage.find_objects(labels)
    hard = np.zeros(labels.shape, dtype=bool)
    accepted = 0
    h, wd = labels.shape
    for idx, sl in enumerate(objects, start=1):
        if sl is None:
            continue
        sub = labels[sl] == idx
        area = int(sub.sum())
        if area < s["min_area_px"]:
            stats["rejected"]["too_small"] += 1
            continue
        if area > s["max_area_px"]:
            stats["rejected"]["too_large"] += 1
            continue
        vals = resid[sl][sub]
        peak = float(vals.max())
        if peak < s["min_peak_sigma"] * sigma_n:
            stats["rejected"]["faint"] += 1
            continue
        ys, xs = np.nonzero(sub)
        if area >= 5:
            cov = np.cov(np.vstack([xs, ys]).astype(np.float64))
            ev = np.sort(np.linalg.eigvalsh(cov))
            ratio = float(np.sqrt(ev[1] / max(ev[0], 1e-6)))
            if ratio > s["max_axis_ratio"]:
                stats["rejected"]["elongated"] += 1
                continue
        bbox_area = (sl[0].stop - sl[0].start) * (sl[1].stop - sl[1].start)
        if area / bbox_area < s["min_solidity"]:
            stats["rejected"]["low_solidity"] += 1
            continue
        if area >= 12 and float(vals.mean()) / peak > s["max_mean_over_peak"]:
            stats["rejected"]["broad_core"] += 1
            continue
        r_eq = float(np.sqrt(area / np.pi))
        r_in, r_out = r_eq * s["annulus_inner_radii"], r_eq * s["annulus_outer_radii"]
        pad = int(np.ceil(r_out)) + 1
        cy = 0.5 * (sl[0].start + sl[0].stop)
        cx = 0.5 * (sl[1].start + sl[1].stop)
        y0, y1 = max(0, int(cy) - pad), min(h, int(cy) + pad + 1)
        x0, x1 = max(0, int(cx) - pad), min(wd, int(cx) + pad + 1)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dist = np.hypot(yy - cy, xx - cx)
        ring = (dist >= r_in) & (dist <= r_out) & weight[y0:y1, x0:x1] & (labels[y0:y1, x0:x1] == 0)
        if ring.sum() >= 8 and float(resid[y0:y1, x0:x1][ring].mean()) > s["max_annulus_fraction"] * peak:
            stats["rejected"]["embedded_in_structure"] += 1
            continue
        hard[sl] |= sub
        accepted += 1
    coverage = float(hard.mean())
    stats.update(accepted=accepted, coverage_fraction=coverage)
    if accepted < s["min_stars"]:
        stats["reason"] = f"only {accepted} confident compact sources; star-specific protection skipped"
        return StarMask(None, None, False, stats)
    if coverage > s["max_mask_coverage"]:
        stats["reason"] = "star mask would cover too much of the frame; detection unreliable"
        return StarMask(None, None, False, stats)
    grown = ndimage.binary_dilation(hard, structure=np.ones((3, 3), bool), iterations=int(s["dilate_px"]))
    soft = ndimage.gaussian_filter(grown.astype(np.float32), s["feather_sigma_px"], mode="reflect", truncate=4.0)
    soft = np.minimum(1.0, soft * 1.6).astype(np.float32)
    soft[~weight] = 0.0
    stats["reason"] = None
    return StarMask(soft, hard, True, stats)
