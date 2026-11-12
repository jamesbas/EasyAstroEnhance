"""Shared reader helpers: signatures, hashing, limits and orientation."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from ..imagedata import ProcessingError

# Orientation values follow the EXIF/TIFF convention. Implemented with NumPy so every
# reader applies orientation exactly once and identically (verified against Pillow in tests).
ORIENTATION_NAMES = {
    1: "none",
    2: "mirror horizontal",
    3: "rotate 180",
    4: "mirror vertical",
    5: "transpose",
    6: "rotate 90 clockwise",
    7: "transverse",
    8: "rotate 90 counter-clockwise",
}


def apply_orientation(a: np.ndarray, orientation: int) -> np.ndarray:
    if orientation == 2:
        out = a[:, ::-1]
    elif orientation == 3:
        out = a[::-1, ::-1]
    elif orientation == 4:
        out = a[::-1, :]
    elif orientation == 5:
        out = np.swapaxes(a, 0, 1)
    elif orientation == 6:
        out = np.rot90(a, k=3)
    elif orientation == 7:
        out = np.swapaxes(a, 0, 1)[::-1, ::-1]
    elif orientation == 8:
        out = np.rot90(a, k=1)
    else:
        return a
    return np.ascontiguousarray(out)


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def detect_format(path: Path) -> str:
    """Validate the file signature (never trust the extension alone)."""
    with open(path, "rb") as fh:
        head = fh.read(32)
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return "tiff"
    if head[:9] == b"SIMPLE  =":
        return "fits"
    raise ProcessingError(
        "UNSUPPORTED_FORMAT",
        "This file is not a supported image. EasyAstroEnhance reads JPEG, TIFF and FITS files.",
        f"signature={head[:8]!r}",
    )


def check_pixel_limit(width: int, height: int, max_pixels: int) -> None:
    if width * height > max_pixels:
        raise ProcessingError(
            "IMAGE_TOO_LARGE",
            f"This image is {width * height / 1e6:.0f} megapixels; the limit is {max_pixels / 1e6:.0f} megapixels.",
        )


def question_state() -> dict[str, Any]:
    return {
        "id": "state",
        "kind": "state",
        "title": "How was this image saved?",
        "options": [
            {
                "value": "linear",
                "label": "Linear stack",
                "help": "Straight from stacking, before any stretch. Uses the separate linear pipeline.",
            },
            {
                "value": "rendered",
                "label": "Already processed",
                "help": "Already stretched or adjusted for viewing. Uses the display-image pipeline.",
            },
            {
                "value": "unsure",
                "label": "I'm not sure",
                "help": "Shows a clearly labeled preview only. Enhancement stays blocked until you confirm.",
            },
        ],
    }
