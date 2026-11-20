"""The largest clean rectangle of a frame (no low-coverage stacking edges or invalid pixels), suggested for cropping in
Edit export. It is only a suggestion: nothing is ever cropped automatically (fidelity rule 3)."""
from __future__ import annotations

from typing import Any

import numpy as np

BLOCK = 8  # the search runs on 8 x 8 blocks; a block counts as clean only when all its pixels are clean
MIN_EDGE_FRACTION = 0.002  # below this share of unclean pixels there is nothing worth cropping


def _largest_rectangle(grid: np.ndarray) -> tuple[int, int, int, int]:
    """(row, col, height, width) of the largest all-True rectangle (histogram / stack method, O(rows x cols))."""
    rows, cols = grid.shape
    heights = np.zeros(cols, dtype=np.int64)
    best = (0, 0, 0, 0)
    best_area = 0
    for r in range(rows):
        heights = np.where(grid[r], heights + 1, 0)
        stack: list[int] = []
        for c in range(cols + 1):
            hgt = int(heights[c]) if c < cols else 0
            while stack and int(heights[stack[-1]]) >= hgt:
                top = stack.pop()
                h_top = int(heights[top])
                left = stack[-1] + 1 if stack else 0
                area = h_top * (c - left)
                if area > best_area:
                    best_area, best = area, (r - h_top + 1, left, h_top, c - left)
            if c < cols:
                stack.append(c)
    return best


def clean_frame(valid: np.ndarray, edges: np.ndarray | None) -> dict[str, Any]:
    clean = valid if edges is None else valid & ~edges
    h, w = clean.shape
    unclean = 1.0 - float(clean.mean())
    if unclean < MIN_EDGE_FRACTION:
        return {"x": 0, "y": 0, "w": int(w), "h": int(h), "width": int(w), "height": int(h), "needed": False, "unclean_fraction": unclean}
    hb, wb = h // BLOCK, w // BLOCK
    blocks = clean[: hb * BLOCK, : wb * BLOCK].reshape(hb, BLOCK, wb, BLOCK).all(axis=(1, 3))
    r, c, rh, cw = _largest_rectangle(blocks)
    return {"x": int(c * BLOCK), "y": int(r * BLOCK), "w": int(cw * BLOCK), "h": int(rh * BLOCK), "width": int(w), "height": int(h),
            "needed": True, "unclean_fraction": unclean,
            "method": f"largest rectangle of fully clean {BLOCK}x{BLOCK} blocks (valid, no low-coverage edge)"}
