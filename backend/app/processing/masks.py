"""Masks: valid pixels, protected regions (labels) and masked (normalized) Gaussian filtering."""
from __future__ import annotations

from typing import Any

import numpy as np

from .imagedata import ProcessingError

MAX_REGIONS = 32
MAX_PROTECTED_FRACTION = 0.6


def validate_regions(regions: list[dict[str, Any]], width: int, height: int) -> list[dict[str, int]]:
    """Validate rectangles in display-orientation full-resolution pixel coordinates."""
    if len(regions) > MAX_REGIONS:
        raise ProcessingError("INVALID_REGION", f"At most {MAX_REGIONS} protected regions are allowed.")
    out: list[dict[str, int]] = []
    for i, r in enumerate(regions, start=1):
        try:
            x, y, w, h = (int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProcessingError("INVALID_REGION", f"Protected region {i} needs integer x, y, w and h.") from exc
        if w < 1 or h < 1:
            raise ProcessingError("INVALID_REGION", f"Protected region {i} must have a positive width and height.")
        if x < 0 or y < 0 or x + w > width or y + h > height:
            raise ProcessingError(
                "INVALID_REGION",
                f"Protected region {i} ({x},{y} {w}×{h}) extends outside the {width}×{height} image.",
            )
        out.append({"x": x, "y": y, "w": w, "h": h})
    if out:
        frac = regions_mask(out, width, height).mean()
        if frac > MAX_PROTECTED_FRACTION:
            raise ProcessingError(
                "INVALID_REGION",
                f"Protected regions cover {frac:.0%} of the image; too little would remain to enhance.",
            )
    return out


def regions_mask(regions: list[dict[str, int]], width: int, height: int) -> np.ndarray:
    m = np.zeros((height, width), dtype=bool)
    for r in regions:
        m[r["y"] : r["y"] + r["h"], r["x"] : r["x"] + r["w"]] = True
    return m


def masked_gaussian(be, x, weight, sigma: float):
    """Normalized convolution: pixels with weight 0 (invalid/protected) contribute nothing to neighbors.

    Where the neighborhood has (almost) no weight the input value is returned unchanged.
    """
    xp = be.xp
    wx = x * (weight[..., None] if x.ndim == 3 else weight)
    num = be.gaussian(wx, sigma)
    den = be.gaussian(weight, sigma)
    den_b = den[..., None] if x.ndim == 3 else den
    ok = den_b > 1e-3
    return xp.where(ok, num / xp.maximum(den_b, 1e-3), x)


def region_summary(regions: list[dict[str, int]], width: int, height: int) -> dict[str, Any]:
    m = regions_mask(regions, width, height) if regions else np.zeros((1, 1), bool)
    return {"count": len(regions), "rectangles": regions, "covered_fraction": float(m.mean()) if regions else 0.0}
