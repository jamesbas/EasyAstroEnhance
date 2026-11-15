"""SYNTHETIC Seestar-like raw sub-frames (GRBG CFA, field rotation, hot pixels, a satellite trail) for stacking tests."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits

from app.processing.stacking.register import Transform

H, W = 240, 320
PATTERN = "GRBG"
SKY = np.array([300.0, 420.0, 360.0])
BIAS = 500.0
HOT = [(40, 61), (101, 200), (180, 33), (211, 290)]


def _stars(rng, n=110):
    x = rng.uniform(-40, W + 40, n)
    y = rng.uniform(-40, H + 40, n)
    flux = 10 ** rng.uniform(3.3, 5.0, n)
    colour = rng.uniform(0.6, 1.4, (n, 3))
    return x, y, flux, colour


def _render_rgb(x, y, flux, colour, sigma=1.4, sky=SKY):
    img = np.empty((H, W, 3)) ; img[:] = sky
    r = 7
    for xi, yi, f, c in zip(x, y, flux, colour):
        x0, y0 = int(round(xi)), int(round(yi))
        if x0 < -r or y0 < -r or x0 >= W + r or y0 >= H + r:
            continue
        ys, xs = np.mgrid[max(0, y0 - r) : min(H, y0 + r + 1), max(0, x0 - r) : min(W, x0 + r + 1)]
        if ys.size == 0:
            continue
        g = f / (2 * np.pi * sigma**2) * np.exp(-((xs - xi) ** 2 + (ys - yi) ** 2) / (2 * sigma**2))
        for ch in range(3):
            img[ys, xs, ch] += g * c[ch]
    return img


def _mosaic(rgb):
    out = np.empty((H, W))
    idx = {"R": 0, "G": 1, "B": 2}
    for i, ch in enumerate(PATTERN):
        dy, dx = divmod(i, 2)
        out[dy::2, dx::2] = rgb[dy::2, dx::2, idx[ch]]
    return out


def _transform(angle_deg, tx, ty) -> Transform:
    a, b = np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))
    cx, cy = W / 2, H / 2
    return Transform(a, b, cx - (a * cx - b * cy) + tx, cy - (b * cx + a * cy) + ty)


def _write(path: Path, data: np.ndarray, kind="Light", exptime=20.0, extra=None):
    hdu = fits.PrimaryHDU(np.clip(np.rint(data), 0, 65535).astype(np.uint16))
    h = hdu.header
    h["IMAGETYP"], h["EXPTIME"], h["ROWORDER"] = kind, exptime, "TOP-DOWN"
    if data.ndim == 2:
        h["BAYERPAT"] = PATTERN
    for k, v in (extra or {}).items():
        h[k] = v
    hdu.writeto(path)


def _make_subs(folder: Path, n=8, seed=3, trail_frame=3, cloudy_frame=None, vignette=None, dark_current=None):
    rng = np.random.default_rng(seed)
    folder.mkdir(parents=True, exist_ok=True)
    x, y, flux, colour = _stars(rng)
    truth = []
    for k in range(n):
        t = Transform(1.0, 0.0, 0.0, 0.0) if k == 0 else _transform(rng.uniform(-2, 2), rng.uniform(-8, 8), rng.uniform(-8, 8))
        fx, fy = t.apply(x, y)
        f = flux * (0.08 if k == cloudy_frame else 1.0)
        rgb = _render_rgb(fx, fy, f, colour)
        raw = _mosaic(rgb)
        if vignette is not None:
            raw = raw * vignette
        if k == trail_frame:
            rr = np.arange(W)
            raw[np.clip((0.4 * rr + 30).astype(int), 0, H - 1), rr] += 6000
        raw += BIAS + rng.normal(0, 18, raw.shape)
        if dark_current is not None:
            raw += dark_current
        for yy, xx in HOT:
            raw[yy, xx] += 9000
        _write(folder / f"Light_M99_20.0s_IRCUT_2025010{k % 9}-2100{k:02d}.fit", raw)
        truth.append(t)
    return truth, (x, y, flux, colour)


