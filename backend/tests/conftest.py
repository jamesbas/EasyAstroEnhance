"""Shared fixtures. Synthetic images here are TEST FIXTURES ONLY and never user output content."""
from __future__ import annotations

import io
import os
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

SAMPLES = Path(__file__).resolve().parents[2] / "samplepics"


def real_file(pattern: str) -> Path | None:
    if not SAMPLES.exists():
        return None
    hits = sorted(SAMPLES.glob(pattern))
    return hits[0] if hits else None


# ------------------------------------------------------------------ synthetic fixtures (labelled)
def synthetic_field(h=192, w=256, rgb=True, seed=0, sky=0.08, noise=0.01, n_stars=40, galaxy=True):
    """SYNTHETIC test field: gaussian stars, an extended faint elliptical blob and noise."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.full((h, w), sky, np.float32)
    if galaxy:
        img += 0.12 * np.exp(-(((xx - w * 0.4) / 40) ** 2 + ((yy - h * 0.5) / 22) ** 2))
    stars = []
    for _ in range(n_stars):
        sy, sx = rng.uniform(8, h - 8), rng.uniform(8, w - 8)
        amp = rng.uniform(0.2, 0.8)
        sig = rng.uniform(1.0, 1.8)
        img += amp * np.exp(-(((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * sig**2)))
        stars.append((sy, sx, amp))
    out = np.stack([img * 1.0, img * 0.95, img * 0.85], -1) if rgb else img
    out = out + rng.normal(0, noise, out.shape).astype(np.float32)
    return np.clip(out, 0, 1).astype(np.float32), stars


def write_jpeg(path: Path, arr: np.ndarray, quality=95) -> Path:
    u8 = np.rint(np.clip(arr, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(u8, "RGB" if u8.ndim == 3 else "L").save(path, "JPEG", quality=quality)
    return path


@pytest.fixture()
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture()
def client(data_dir):
    from fastapi.testclient import TestClient

    from app.config import load_config
    from app.main import create_app

    cfg = load_config(data_dir=data_dir, port=8765)
    app = create_app(cfg)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        token = c.get("/api/v1/session").json()["token"]
        c.headers.update({"X-EAE-Token": token})
        c.cfg = cfg  # type: ignore[attr-defined]
        yield c


def wait_for(fn, timeout=120.0, interval=0.25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    raise TimeoutError("condition not met")


def make_image(pixels, domain="display", valid=None, fmt="jpeg", dtype="uint8", bits=8, norm=None, header=None):
    """Build an ImageData directly (synthetic test input)."""
    from app.processing.imagedata import ImageData, Normalization

    pixels = np.asarray(pixels)
    h, w = pixels.shape[:2]
    return ImageData(
        pixels=pixels, channel_layout="mono" if pixels.ndim == 2 else "rgb", domain=domain, units="test",
        valid_mask=np.ones((h, w), bool) if valid is None else valid, protected_mask=np.zeros((h, w), bool), metadata={},
        source_hash="0" * 64, orientation_transform="test", normalization=norm or Normalization("unit_range", 255.0),
        source_format=fmt, source_dtype=dtype, source_bit_depth=bits, header=header,
    )


def linear_field(h=160, w=200, rgb=True, seed=1, sky=1000.0, noise=20.0, n_stars=30, gradient=(0.0, 0.0), negatives=False):
    """SYNTHETIC linear stack: sky + noise + faint extended blob + Gaussian stars (+ optional plane gradient)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    base = np.full((h, w), sky) + gradient[0] * (xx / w - 0.5) + gradient[1] * (yy / h - 0.5)
    base += 150.0 * np.exp(-(((xx - w * 0.5) / 30) ** 2 + ((yy - h * 0.5) / 18) ** 2))
    for _ in range(n_stars):
        sy, sx = rng.uniform(6, h - 6), rng.uniform(6, w - 6)
        base += rng.uniform(800, 6000) * np.exp(-(((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * rng.uniform(1.0, 1.6) ** 2)))
    out = np.stack([base, base * 0.9, base * 0.8], -1) if rgb else base
    out = out + rng.normal(0, noise, out.shape)
    if negatives:
        out = out - sky * 1.05
    return out.astype(np.float32)
