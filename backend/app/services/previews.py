"""Preview and ROI rendering from the stored uint16 display arrays (memory-mapped; never the full file in RAM)."""
from __future__ import annotations

import io
from collections import OrderedDict
from pathlib import Path
from threading import Lock

import numpy as np
from PIL import Image

from ..processing.imagedata import ProcessingError

MAX_EDGE = 2048
_cache: "OrderedDict[tuple, tuple[bytes, dict[str, str], str]]" = OrderedDict()
_lock = Lock()


def u16_to_u8(a: np.ndarray) -> np.ndarray:
    return ((a.astype(np.uint32) * 255 + 32767) // 65535).astype(np.uint8)


def open_display(path: Path) -> np.ndarray:
    if not path.exists():
        raise ProcessingError("NOT_FOUND", "The requested image is not available.")
    return np.load(path, mmap_mode="r")


def render(path: Path, roi: tuple[int, int, int, int] | None, max_edge: int = MAX_EDGE) -> tuple[bytes, dict[str, str], str]:
    """Render the whole image (JPEG, downsampled to ``max_edge``) or a full-resolution ROI tile (PNG)."""
    if not path.exists():
        raise ProcessingError("NOT_FOUND", "The requested image is not available.")
    key = (str(path), path.stat().st_mtime_ns, roi, max_edge)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    arr = open_display(path)
    H, W = arr.shape[:2]
    if roi:
        x, y, w, h = roi
        x, y = max(0, min(x, W - 1)), max(0, min(y, H - 1))
        w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
    else:
        x, y, w, h = 0, 0, W, H
    scale = min(1.0, max_edge / max(w, h))
    tile = u16_to_u8(np.asarray(arr[y : y + h, x : x + w]))
    mode = "RGB" if tile.ndim == 3 else "L"
    im = Image.fromarray(tile, mode)
    if scale < 1.0:
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    if roi:
        im.save(buf, "PNG", compress_level=1)
        media = "image/png"
    else:
        im.save(buf, "JPEG", quality=92, subsampling=0)
        media = "image/jpeg"
    headers = {
        "X-Source-Width": str(W),
        "X-Source-Height": str(H),
        "X-Preview-Scale": f"{scale:.6f}",
        "X-Preview-Downsampled": "1" if scale < 1.0 else "0",
        "X-Roi": f"{x},{y},{w},{h}",
        "Cache-Control": "private, max-age=3600",
        "Access-Control-Expose-Headers": "X-Source-Width, X-Source-Height, X-Preview-Scale, X-Preview-Downsampled, X-Roi",
    }
    out = (buf.getvalue(), headers, media)
    with _lock:
        _cache[key] = out
        while len(_cache) > 24:
            _cache.popitem(last=False)
    return out


def clipping_overlay(baseline_path: Path, display_path: Path, max_edge: int = MAX_EDGE) -> bytes:
    """RGBA overlay: blue = newly clipped to black, red = newly clipped to white (per-pixel transitions)."""
    base = open_display(baseline_path)
    out = open_display(display_path)
    H, W = out.shape[:2]
    new_black = np.zeros((H, W), dtype=bool)
    new_white = np.zeros((H, W), dtype=bool)
    step = 512
    for y in range(0, H, step):
        b = np.asarray(base[y : y + step])
        o = np.asarray(out[y : y + step])
        nb = (o == 0) & (b > 0)
        nw = (o == 65535) & (b < 65535)
        if o.ndim == 3:
            nb, nw = nb.any(axis=2), nw.any(axis=2)
        new_black[y : y + step], new_white[y : y + step] = nb, nw
    scale = min(1.0, max_edge / max(H, W))
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[new_black] = (60, 120, 255, 200)
    rgba[new_white] = (255, 60, 60, 200)
    im = Image.fromarray(rgba, "RGBA")
    if scale < 1.0:
        im = im.resize((max(1, round(W * scale)), max(1, round(H * scale))), Image.Resampling.BOX)
        a = np.asarray(im).copy()
        a[..., 3] = np.where(a[..., 3] > 0, np.maximum(a[..., 3], 160), 0)  # keep isolated pixels visible
        im = Image.fromarray(a, "RGBA")
    buf = io.BytesIO()
    im.save(buf, "PNG", compress_level=1)
    return buf.getvalue()
