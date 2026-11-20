"""Reframe a completed display image; never read or write the scientific pixel data."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from .export import _font, encode_png
from .imagedata import ProcessingError


@dataclass(frozen=True)
class Framing:
    rotation: int
    zoom: float
    pan_x: float
    pan_y: float


def reframe(display: np.ndarray, frame: Framing, max_edge: int | None = None) -> np.ndarray:
    h, w = display.shape[:2]
    if frame.rotation % 90 == 0:
        rotated = np.rot90(display, -(frame.rotation // 90))
        bh, bw = rotated.shape[:2]
    else:
        rotated = None
        angle = math.radians(frame.rotation)
        c, s = math.cos(angle), math.sin(angle)
        bw = math.ceil(w * abs(c) + h * abs(s))
        bh = math.ceil(h * abs(c) + w * abs(s))
    cw, ch = max(1, round(bw / frame.zoom)), max(1, round(bh / frame.zoom))
    left = round((bw - cw) * (frame.pan_x + 1) / 2)
    top = round((bh - ch) * (frame.pan_y + 1) / 2)
    # Bound arbitrary-angle padding on long panoramas; never create more pixels than the source.
    scale = min(1.0, math.sqrt(w * h / (cw * ch)))
    if max_edge is not None:
        scale = min(scale, max_edge / max(cw, ch))
    ow, oh = max(1, int(cw * scale)), max(1, int(ch * scale))
    if rotated is not None:
        crop = rotated[top:top + ch, left:left + cw]
        if (ow, oh) == (cw, ch):
            return crop
        source = crop
        c, s, bw, bh, left, top = 1.0, 0.0, cw, ch, 0, 0
        w, h = cw, ch
    else:
        source = display
    sx, sy = cw / ow, ch / oh
    x0 = left + (sx - bw) / 2
    y0 = top + (sy - bh) / 2
    matrix = ((c * sy, -s * sx), (s * sy, c * sx))
    offset = ((h - 1) / 2 + c * y0 - s * x0, (w - 1) / 2 + s * y0 + c * x0)
    out = np.empty((oh, ow, *source.shape[2:]), dtype=np.uint16)
    planes = ((source, out),) if source.ndim == 2 else ((source[..., i], out[..., i]) for i in range(source.shape[2]))
    for src, dst in planes:
        ndimage.affine_transform(src, matrix, offset, output=dst, order=1, mode="grid-constant", prefilter=False)
    return out


def _draw_caption(display: np.ndarray, lines: list[str]) -> None:
    h, w = display.shape[:2]
    margin = max(1, round(min(w, h) * 0.022))
    size = max(8, round(min(w, h) * 0.045))
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    text = "\n".join(lines)
    for size in range(size, 5, -1):
        font = _font(size)
        spacing = max(1, size // 5)
        x0, y0, x1, y1 = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
        pad = max(1, size // 3)
        bw, bh = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
        if bw <= w - 2 * margin and bh <= h - 2 * margin:
            break
    else:
        raise ProcessingError("CAPTION_TOO_LARGE", "The label does not fit this crop. Shorten it or zoom out.")
    mask = Image.new("L", (bw, bh))
    ImageDraw.Draw(mask).multiline_text((pad - x0, pad - y0), text, font=font, fill=255, spacing=spacing)
    a = np.asarray(mask, dtype=np.uint32)
    if display.ndim == 3:
        a = a[..., None]
    patch = display[h - margin - bh:h - margin, margin:margin + bw]
    patch[:] = (((patch.astype(np.uint32) * 35 // 100) * (255 - a) + 65535 * a + 127) // 255).astype(np.uint16)


def render_edited(display: np.ndarray, frame: Framing, lines: list[str], *, jpeg: bool,
                  metadata: bytes | None = None, preview: bool = False) -> bytes:
    image = reframe(display, frame, 1000 if preview else None)
    if lines:
        if np.shares_memory(image, display):
            image = image.copy()
        _draw_caption(image, lines)
    if not jpeg and not preview:
        return encode_png(image, edit_metadata=metadata)
    pixels = np.empty(image.shape, dtype=np.uint8)
    for start in range(0, image.shape[0], 256):
        tile = slice(start, start + 256)
        pixels[tile] = (image[tile].astype(np.uint32) * 255 + 32767) // 65535
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, "JPEG", quality=90 if preview else 95, subsampling=0, comment=metadata or b"")
    return buf.getvalue()
