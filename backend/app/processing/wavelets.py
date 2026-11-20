"""Undecimated "à trous" B3-spline wavelet transform (Starck & Murtagh), written against ``xp`` so the
same code runs on NumPy and CuPy. Filtering is separable with reflect boundaries; scale ``j`` (1-based)
uses the kernel [1, 4, 6, 4, 1]/16 dilated by 2**(j-1), so its footprint radius is 2**j pixels.

Detail planes ``w_j = c_{j-1} - c_j`` sum with the final residual back to the input exactly.
"""
from __future__ import annotations

import numpy as np

B3 = (1.0 / 16.0, 4.0 / 16.0, 6.0 / 16.0, 4.0 / 16.0, 1.0 / 16.0)


def scale_radius(j: int) -> int:
    return 2 ** j


def total_radius(n_scales: int) -> int:
    """Cumulative footprint of ``n_scales`` smoothing steps (tile halo)."""
    return sum(scale_radius(j) for j in range(1, n_scales + 1))


def _taps(xp, src, out, step: int, m: int, weights, tmp=None):
    """out[r] = sum_k src[r + k*step] * weights[k] for r < m, accumulated in tap order (k = 0..4)."""
    xp.multiply(src[0:m], weights[0], out=out)
    tmp = xp.empty_like(out) if tmp is None else tmp
    for k in range(1, 5):
        xp.multiply(src[k * step : k * step + m], weights[k], out=tmp)
        xp.add(out, tmp, out=out)
    return out


def _smooth_axis(xp, a, step: int, axis: int):
    """One dilated B3 pass with reflect boundaries.

    The interior is computed directly from ``a`` and only the two boundary bands are padded, accumulating the taps in
    the same order as a full ``pad`` + sum, so results are bitwise identical to that formulation but much cheaper."""
    n = a.shape[axis]
    pad = 2 * step
    weights = [a.dtype.type(wk) for wk in B3]
    src = xp.moveaxis(a, axis, 0)
    out = xp.empty(src.shape, dtype=a.dtype)
    if n <= 2 * pad:  # small inputs: pad everything (edge padding when reflect needs n > pad)
        widths = [(pad, pad)] + [(0, 0)] * (a.ndim - 1)
        p = xp.pad(src, widths, mode="edge" if n <= pad else "reflect")
        _taps(xp, p, out, step, n, weights)
        return xp.moveaxis(out, 0, axis)
    _taps(xp, src, out[pad : n - pad], step, n - 2 * pad, weights)
    rest = [(0, 0)] * (a.ndim - 1)
    head = xp.pad(src[: 2 * pad], [(pad, 0)] + rest, mode="reflect")
    _taps(xp, head, out[:pad], step, pad, weights)
    tail = xp.pad(src[n - 2 * pad :], [(0, pad)] + rest, mode="reflect")
    _taps(xp, tail, out[n - pad :], step, pad, weights)
    return xp.moveaxis(out, 0, axis)


def smooth(xp, a, j: int):
    """One à trous smoothing step at scale ``j`` (1-based) over the two spatial axes."""
    step = 2 ** (j - 1)
    return _smooth_axis(xp, _smooth_axis(xp, a, step, 0), step, 1)


def decompose(xp, a, n_scales: int):
    """Return ([w_1 .. w_n], residual) with sum(w) + residual == a."""
    planes = []
    c = a
    for j in range(1, n_scales + 1):
        c_next = smooth(xp, c, j)
        planes.append(c - c_next)
        c = c_next
    return planes, c


def white_noise_factors(n_scales: int, size: int = 256, seed: int = 7) -> list[float]:
    """Standard deviation of each detail plane for unit white Gaussian noise (measured once, deterministic)."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal((size, size)).astype(np.float64)
    planes, _ = decompose(np, noise, n_scales)
    m = 2 * total_radius(n_scales)
    core = (slice(m, size - m), slice(m, size - m)) if size > 4 * m else (slice(None), slice(None))
    return [float(p[core].std()) for p in planes]
