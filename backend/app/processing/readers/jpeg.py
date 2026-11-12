from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms, ImageOps

from ..imagedata import ImageData, Normalization, ProcessingError
from .common import ORIENTATION_NAMES, check_pixel_limit

EXIF_ORIENTATION = 0x0112


def inspect_jpeg(path: Path, max_pixels: int) -> dict[str, Any]:
    try:
        with Image.open(path) as im:
            width, height = im.size
            mode = im.mode
            orientation = int(im.getexif().get(EXIF_ORIENTATION, 1) or 1)
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError(
            "CORRUPT_FILE", "This JPEG could not be read. It may be damaged or incomplete.", str(exc)
        ) from exc
    if mode not in ("L", "RGB"):
        raise ProcessingError(
            "UNSUPPORTED_COLOR_MODE",
            f"This JPEG uses the {mode} color mode, which is not supported. "
            "Export it again as an RGB or grayscale JPEG, or as a TIFF.",
        )
    if orientation in (5, 6, 7, 8):
        width, height = height, width
    check_pixel_limit(width, height, max_pixels)
    return {
        "format": "jpeg",
        "width": width,
        "height": height,
        "channel_layout": "mono" if mode == "L" else "rgb",
        "bit_depth": 8,
        "dtype": "uint8",
        "info": {"exif_orientation": orientation},
        "candidates": [],
    }


def _is_srgb(profile: ImageCms.ImageCmsProfile) -> bool:
    try:
        return "srgb" in ImageCms.getProfileDescription(profile).lower()
    except Exception:
        return False


def read_jpeg(path: Path, source_hash: str, max_pixels: int) -> ImageData:
    meta = inspect_jpeg(path, max_pixels)
    notes: list[str] = []
    icc_state = "none"
    try:
        with Image.open(path) as im:
            im.load()
            orientation = meta["info"]["exif_orientation"]
            icc = im.info.get("icc_profile")
            img = ImageOps.exif_transpose(im) if orientation != 1 else im.copy()
            if icc and img.mode == "RGB":
                try:
                    src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                    if _is_srgb(src):
                        icc_state = "srgb"
                    else:
                        dst = ImageCms.createProfile("sRGB")
                        img = ImageCms.profileToProfile(
                            img, src, dst, outputMode="RGB", flags=ImageCms.Flags.BLACKPOINTCOMPENSATION
                        )
                        icc_state = "converted_to_srgb"
                except Exception:
                    icc_state = "unreadable_assumed_srgb"
                    notes.append("The embedded color profile could not be read; sRGB was assumed.")
            arr = np.asarray(img)
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError("CORRUPT_FILE", "This JPEG could not be decoded.", str(exc)) from exc

    pixels = arr.astype(np.float32) / np.float32(255.0)
    h, w = pixels.shape[:2]
    return ImageData(
        pixels=pixels,
        channel_layout="mono" if pixels.ndim == 2 else "rgb",
        domain="display",
        units="display sRGB, 1.0 = 8-bit white",
        valid_mask=np.ones((h, w), dtype=bool),
        protected_mask=np.zeros((h, w), dtype=bool),
        metadata={"exif_orientation": orientation, "icc": icc_state},
        source_hash=source_hash,
        orientation_transform=f"EXIF orientation {orientation} ({ORIENTATION_NAMES.get(orientation, '?')}) applied once",
        normalization=Normalization("unit_range", scale=255.0, offset=0.0, note="8-bit JPEG / 255"),
        source_format="jpeg",
        source_dtype="uint8",
        source_bit_depth=8,
        notes=notes,
    )
