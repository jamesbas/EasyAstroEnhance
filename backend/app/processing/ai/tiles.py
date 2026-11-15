"""Overlapping tiles for fixed-size image-to-image models, stitched without seams.

Each tile drops ``margin`` pixels at its borders (where a convolutional network lacks context) and neighbouring kept
regions are cross-faded linearly over their overlap. With no overlap left (``step == tile - 2*margin``) this is exact
centre-crop stitching (GraXpert's scheme). The image is reflect-padded so every pixel is covered by a kept region.
"""
from __future__ import annotations

from typing import Callable

import numpy as np


def _weights_1d(tile: int, margin: int, step: int) -> np.ndarray:
    kept = tile - 2 * margin
    ov = max(0, kept - step)
    i = np.arange(tile, dtype=np.float64)
    w = np.minimum.reduce([np.ones(tile), (i - margin + 1) / (ov + 1), (tile - margin - i) / (ov + 1)])
    w[(i < margin) | (i >= tile - margin)] = 0.0
    return np.clip(w, 0.0, 1.0)


def _positions(n_padded: int, tile: int, step: int) -> list[int]:
    return list(range(0, n_padded - tile + 1, step))


def _pad_amount(n: int, tile: int, step: int, margin: int) -> int:
    total = n + 2 * margin
    if total <= tile:
        return tile - total
    return (-(total - tile)) % step


def tile_apply(img: np.ndarray, fn: Callable[[np.ndarray], np.ndarray], tile: int, step: int, margin: int, batch: int = 1,
               check: Callable[[], None] | None = None, progress: Callable[[float], None] | None = None) -> np.ndarray:
    """img: H x W x C float32 -> model output of the same shape (fn maps N x T x T x C to N x T x T x C)."""
    if step <= 0 or step > tile - 2 * margin:
        raise ValueError("step must be in 1 .. tile - 2*margin")
    h, w, c = img.shape
    ey, ex = _pad_amount(h, tile, step, margin), _pad_amount(w, tile, step, margin)
    padded = np.pad(img, ((margin, margin + ey), (margin, margin + ex), (0, 0)), mode="reflect" if min(h, w) > 1 else "edge")
    H, W = padded.shape[:2]
    acc = np.zeros((H, W, c), np.float32)
    wsum = np.zeros((H, W), np.float32)
    w1 = _weights_1d(tile, margin, step).astype(np.float32)
    w2 = np.outer(w1, w1)
    coords = [(y, x) for y in _positions(H, tile, step) for x in _positions(W, tile, step)]
    for k in range(0, len(coords), batch):
        if check:
            check()
        group = coords[k : k + batch]
        out = fn(np.stack([padded[y : y + tile, x : x + tile] for y, x in group]))
        for (y, x), o in zip(group, out):
            acc[y : y + tile, x : x + tile] += o[..., :c] * w2[..., None]
            wsum[y : y + tile, x : x + tile] += w2
        if progress:
            progress(min(1.0, (k + len(group)) / len(coords)))
    res = acc[margin : margin + h, margin : margin + w] / np.maximum(wsum[margin : margin + h, margin : margin + w, None], 1e-12)
    return res.astype(np.float32)


def resize_linear(img: np.ndarray, oh: int, ow: int) -> np.ndarray:
    """Separable bilinear resize with pixel-centre alignment (the convention of OpenCV's INTER_LINEAR)."""

    def axis(a: np.ndarray, n_out: int, ax: int) -> np.ndarray:
        n_in = a.shape[ax]
        src = np.clip((np.arange(n_out) + 0.5) * n_in / n_out - 0.5, 0, n_in - 1)
        i0 = np.floor(src).astype(np.int64)
        i1 = np.minimum(i0 + 1, n_in - 1)
        f = (src - i0).astype(np.float32)
        shape = [1] * a.ndim
        shape[ax] = n_out
        f = f.reshape(shape)
        return np.take(a, i0, axis=ax) * (1 - f) + np.take(a, i1, axis=ax) * f

    return axis(axis(img.astype(np.float32), oh, 0), ow, 1).astype(np.float32)
