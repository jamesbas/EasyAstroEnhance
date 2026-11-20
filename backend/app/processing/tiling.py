"""Tiled execution with full filter overlap (halo). Global statistics are computed once by the caller,
never per tile, so tiled and full-frame results agree exactly as long as the halo covers the chained filter footprint.

Tiles may run on several CPU threads (NumPy/SciPy release the GIL); every tile writes a disjoint interior, and the
per-tile extras are returned in tile order, so threaded and sequential runs give identical results."""
from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterator

import numpy as np

Tile = int | tuple[int, int]


def _edges(tile: Tile) -> tuple[int, int]:
    return (tile, tile) if isinstance(tile, int) else (int(tile[0]), int(tile[1]))


def tile_grid(height: int, width: int, tile: Tile, halo: int) -> Iterator[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
    """Yield (outer, inner) boxes as (y0, y1, x0, x1). ``tile`` is an edge or (tile_h, tile_w). ``outer`` includes the halo,
    clipped to the image; at image borders the outer box equals the image edge so boundary handling matches full-frame."""
    th, tw = _edges(tile)
    for y0 in range(0, height, th):
        y1 = min(y0 + th, height)
        for x0 in range(0, width, tw):
            x1 = min(x0 + tw, width)
            outer = (max(0, y0 - halo), min(height, y1 + halo), max(0, x0 - halo), min(width, x1 + halo))
            yield outer, (y0, y1, x0, x1)


def parallel_tiles(height: int, width: int, halo: int, workers: int, bytes_per_pixel: int, budget_bytes: int | None) -> tuple[tuple[int, int], int]:
    """A (tile_h, tile_w) split into about ``workers`` near-square tiles of equal size, and the number of tiles that may
    run at once without exceeding ``budget_bytes`` (each live tile needs (tile + 2*halo)^2 * bytes_per_pixel)."""
    workers = max(1, int(workers))
    ny = max(1, round(math.sqrt(workers * height / max(width, 1))))
    nx = max(1, math.ceil(workers / ny))
    th, tw = math.ceil(height / ny), math.ceil(width / nx)
    if budget_bytes:
        per_tile = (th + 2 * halo) * (tw + 2 * halo) * bytes_per_pixel
        workers = max(1, min(workers, int(budget_bytes // max(per_tile, 1))))
    return (th, tw), workers


def run_tiled(
    fn: Callable[[dict[str, np.ndarray], tuple[int, int, int, int]], tuple[dict[str, np.ndarray], Any]],
    inputs: dict[str, np.ndarray],
    outputs: dict[str, np.ndarray],
    tile: Tile,
    halo: int,
    cancel_check: Callable[[], None] | None = None,
    workers: int = 1,
) -> list[Any]:
    """Run ``fn`` per tile. ``fn(tile_inputs, inner_local)`` returns (interior_outputs, extra); ``inner_local``
    is the interior box in tile-local coordinates and the returned arrays are already interior-sized.
    They are written into the preallocated ``outputs``. With ``workers > 1`` tiles run on a thread pool."""
    any_in = next(iter(inputs.values()))
    h, w = any_in.shape[:2]
    boxes = list(tile_grid(h, w, tile, halo))
    failed = threading.Event()

    def one(box) -> Any:
        if failed.is_set():
            return None
        (oy0, oy1, ox0, ox1), (iy0, iy1, ix0, ix1) = box
        try:
            if cancel_check:
                cancel_check()
            tile_in = {k: v[oy0:oy1, ox0:ox1] for k, v in inputs.items()}
            inner_local = (iy0 - oy0, iy1 - oy0, ix0 - ox0, ix1 - ox0)
            tile_out, extra = fn(tile_in, inner_local)
            for k, arr in tile_out.items():
                outputs[k][iy0:iy1, ix0:ix1] = arr
            return extra
        except BaseException:
            failed.set()
            raise

    if workers <= 1 or len(boxes) == 1:
        return [one(b) for b in boxes]
    with ThreadPoolExecutor(max_workers=min(workers, len(boxes)), thread_name_prefix="eae-tile") as ex:
        futures = [ex.submit(one, b) for b in boxes]
        extras: list[Any] = []
        error: BaseException | None = None
        for f in futures:  # in tile order; the first failure (cancel, error) wins once all tiles have stopped
            try:
                extras.append(f.result())
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                error = error or exc
        if error is not None:
            raise error
        return extras
