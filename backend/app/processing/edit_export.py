"""Reframe a completed display image; never read or write the scientific pixel data."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from .export import _font, encode_png
from .imagedata import ProcessingError


@dataclass(frozen=True)
class Framing:
    rotation: int
    zoom: float
    pan_x: float
    pan_y: float


# Caption fonts: OFL fonts shipped in app/fonts (see SOURCES.txt), all with accented Latin letters.
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
FONT_FILES = {"sans": "Lato-Regular.ttf", "serif": "PTSerif-Regular.ttf", "script": "GreatVibes-Regular.ttf",
              "mono": "SpaceMono-Regular.ttf"}
POSITIONS = ("bottom-left", "bottom-center", "bottom-right", "top-left", "top-center", "top-right")
BASE_TEXT_SIZE = 0.045  # caption height at size 1.0, as a share of the output's short edge


@dataclass(frozen=True)
class Caption:
    text: str
    position: str = "bottom-left"
    size: float = 1.0  # relative to BASE_TEXT_SIZE


@dataclass(frozen=True)
class TextStyle:
    font: str = "sans"
    color: tuple[int, int, int] = (255, 255, 255)
    box: bool = True  # dark box behind the text; without it the text gets a dark outline


@lru_cache(maxsize=64)
def caption_font(name: str, size: int):
    try:
        return ImageFont.truetype(str(FONT_DIR / FONT_FILES.get(name, FONT_FILES["sans"])), size)
    except OSError:  # a damaged install: fall back to Pillow's built-in font
        return _font(size)


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


def _overlaps(a: tuple[int, int, int, int], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _layout_group(draw: ImageDraw.ImageDraw, group: list[Caption], style: TextStyle, w: int, h: int, margin: int):
    """Fonts and line boxes for captions sharing one position, shrunk together until the block fits the image."""
    base = max(8, round(min(w, h) * BASE_TEXT_SIZE))
    for step in range(60):
        sizes = [max(6, round(base * c.size * 0.94 ** step)) for c in group]
        lines = []
        for c, size in zip(group, sizes):
            font = caption_font(style.font, size)
            stroke = 0 if style.box else max(1, size // 14)
            lines.append((c.text, font, stroke, draw.textbbox((0, 0), c.text, font=font, stroke_width=stroke), max(1, size // 5)))
        pad = max(1, min(sizes) // 3)
        bw = max(b[2] - b[0] for _, _, _, b, _ in lines) + 2 * pad
        bh = sum(b[3] - b[1] for _, _, _, b, _ in lines) + sum(s for *_, s in lines[1:]) + 2 * pad
        if bw <= w - 2 * margin and bh <= h - 2 * margin:
            return lines, pad, bw, bh
        if max(sizes) == 6:
            break
    raise ProcessingError("CAPTION_TOO_LARGE", "The text does not fit this crop. Shorten it, make it smaller or zoom out.")


def _draw_captions(display: np.ndarray, captions: list[Caption], style: TextStyle = TextStyle(),
                   avoid: list[tuple[float, float, float, float]] | None = None) -> None:
    """Draw captions grouped by position (the target name above the label when they share one), keeping clear of
    ``avoid`` boxes (compass, scale bar) and of each other."""
    h, w = display.shape[:2]
    margin = max(1, round(min(w, h) * 0.022))
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    taken = list(avoid or [])
    groups: dict[str, list[Caption]] = {}
    for c in captions:
        if c.text:
            groups.setdefault(c.position if c.position in POSITIONS else "bottom-left", []).append(c)
    r, g, b = style.color
    color = [v * 257 for v in style.color] if display.ndim == 3 else [round(0.2126 * r + 0.7152 * g + 0.0722 * b) * 257]
    for position, group in groups.items():
        lines, pad, bw, bh = _layout_group(draw, group, style, w, h, margin)
        vertical, horizontal = position.split("-")
        x = {"left": margin, "center": (w - bw) // 2, "right": w - margin - bw}[horizontal]
        y = margin if vertical == "top" else h - margin - bh
        for _ in range(len(taken)):
            hit = next((t for t in taken if _overlaps((x, y, x + bw, y + bh), t)), None)
            if hit is None:
                break
            y = round(hit[3]) + margin // 2 if vertical == "top" else round(hit[1]) - margin // 2 - bh
        y = min(max(y, 0), h - bh)
        taken.append((x, y, x + bw, y + bh))
        fill = Image.new("L", (bw, bh))
        outline = Image.new("L", (bw, bh))
        fd, od = ImageDraw.Draw(fill), ImageDraw.Draw(outline)
        cy = pad
        for text, font, stroke, box, spacing in lines:
            lw = box[2] - box[0]
            lx = {"left": pad, "center": (bw - lw) // 2, "right": bw - pad - lw}[horizontal]
            origin = (lx - box[0], cy - box[1])
            if stroke:
                od.text(origin, text, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
            fd.text(origin, text, font=font, fill=255)
            cy += box[3] - box[1] + spacing
        a = np.asarray(fill, dtype=np.uint32)
        patch = display[y:y + bh, x:x + bw]
        if style.box:
            base = patch.astype(np.uint32) * 35 // 100
        else:
            s = np.asarray(outline, dtype=np.uint32)
            base = patch.astype(np.uint32) * (255 - (s[..., None] if patch.ndim == 3 else s)) // 255
        if patch.ndim == 3:
            a = a[..., None]
            col = np.array(color[: patch.shape[2]], dtype=np.uint32)
        else:
            col = np.uint32(color[0])
        patch[:] = ((base * (255 - a) + col * a + 127) // 255).astype(np.uint16)


def render_edited(display: np.ndarray, frame: Framing, captions: list[Caption], *, jpeg: bool,
                  metadata: bytes | None | Callable[[Any], bytes] = None, preview: bool = False,
                  overlay: Callable[[np.ndarray, int | None], Any] | None = None, style: TextStyle = TextStyle()) -> bytes:
    """``overlay(image, max_edge)`` draws annotations on the framed copy and may list boxes the captions must avoid
    under ``"reserved"``; ``metadata`` may be a function of what it drew."""
    max_edge = 1000 if preview else None
    image = reframe(display, frame, max_edge)
    captions = [c for c in captions if c.text]
    drawn = None
    reserved: list = []
    if captions or overlay is not None:
        if np.shares_memory(image, display):
            image = image.copy()
    if overlay is not None:
        drawn = overlay(image, max_edge)
        if isinstance(drawn, dict):
            reserved = drawn.pop("reserved", [])
    if captions:
        _draw_captions(image, captions, style, reserved)
    if callable(metadata):
        metadata = metadata(drawn)
    if not jpeg and not preview:
        return encode_png(image, edit_metadata=metadata)
    pixels = np.empty(image.shape, dtype=np.uint8)
    for start in range(0, image.shape[0], 256):
        tile = slice(start, start + 256)
        pixels[tile] = (image[tile].astype(np.uint32) * 255 + 32767) // 65535
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, "JPEG", quality=90 if preview else 95, subsampling=0, comment=metadata or b"")
    return buf.getvalue()
