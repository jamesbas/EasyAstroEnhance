"""Tiled execution with full filter overlap (halo). Global statistics are computed once by the caller,
never per tile, so tiled and full-frame results agree to floating-point tolerance."""
from __future__ import annotations

from typing import Any, Callable, Iterator

import numpy as np


def tile_grid(height: int, width: int, tile: int, halo: int) -> Iterator[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
    """Yield (outer, inner) boxes as (y0, y1, x0, x1). ``outer`` includes the halo, clipped to the image;
    at image borders the outer box equals the image edge so boundary handling matches full-frame."""
    for y0 in range(0, height, tile):
        y1 = min(y0 + tile, height)
        for x0 in range(0, width, tile):
            x1 = min(x0 + tile, width)
            outer = (max(0, y0 - halo), min(height, y1 + halo), max(0, x0 - halo), min(width, x1 + halo))
            yield outer, (y0, y1, x0, x1)


def run_tiled(
    fn: Callable[[dict[str, np.ndarray], tuple[int, int, int, int]], tuple[dict[str, np.ndarray], Any]],
    inputs: dict[str, np.ndarray],
    outputs: dict[str, np.ndarray],
    tile: int,
    halo: int,
    cancel_check: Callable[[], None] | None = None,
) -> list[Any]:
    """Run ``fn`` per tile. ``fn(tile_inputs, inner_local)`` returns (interior_outputs, extra); ``inner_local``
    is the interior box in tile-local coordinates and the returned arrays are already interior-sized.
    They are written into the preallocated ``outputs``."""
    any_in = next(iter(inputs.values()))
    h, w = any_in.shape[:2]
    extras: list[Any] = []
    for (oy0, oy1, ox0, ox1), (iy0, iy1, ix0, ix1) in tile_grid(h, w, tile, halo):
        if cancel_check:
            cancel_check()
        tile_in = {k: v[oy0:oy1, ox0:ox1] for k, v in inputs.items()}
        inner_local = (iy0 - oy0, iy1 - oy0, ix0 - ox0, ix1 - ox0)
        tile_out, extra = fn(tile_in, inner_local)
        for k, arr in tile_out.items():
            outputs[k][iy0:iy1, ix0:ix1] = arr
        extras.append(extra)
    return extras
