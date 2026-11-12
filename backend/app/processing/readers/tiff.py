from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
from PIL import Image, ImageCms

from ..imagedata import ImageData, ProcessingError
from .build import build_image
from .common import ORIENTATION_NAMES, apply_orientation, check_pixel_limit, question_state

SUPPORTED_DTYPES = ("uint8", "uint16", "float32")


def _unsupported(code: str, message: str, detail: str | None = None) -> ProcessingError:
    return ProcessingError(code, message, detail)


def inspect_tiff(path: Path, max_pixels: int) -> dict[str, Any]:
    try:
        with tifffile.TiffFile(path) as tif:
            if len(tif.pages) != 1 or len(tif.series) != 1:
                raise _unsupported(
                    "MULTIPAGE_TIFF",
                    "This TIFF contains several images or pages. Export a single stacked image "
                    "(one page) and add that file instead.",
                )
            page = tif.pages[0]
            series = tif.series[0]
            shape = tuple(int(s) for s in series.shape)
            axes = series.axes
            dtype = np.dtype(series.dtype)
            photometric = page.photometric.name if page.photometric is not None else "UNKNOWN"
            extra = tuple(page.extrasamples or ())
            samples = int(page.samplesperpixel)
            tags = page.tags
            orientation = int(tags["Orientation"].value) if "Orientation" in tags else 1
            icc = tags["InterColorProfile"].value if "InterColorProfile" in tags else None
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError(
            "CORRUPT_FILE", "This TIFF could not be read. It may be damaged or use an unsupported compression.", str(exc)
        ) from exc

    if np.iscomplexobj(np.empty(0, dtype)):
        raise _unsupported("UNSUPPORTED_SAMPLE_TYPE", "Complex-valued TIFF data is not supported.")
    if dtype.name not in SUPPORTED_DTYPES:
        raise _unsupported(
            "UNSUPPORTED_SAMPLE_TYPE",
            f"This TIFF stores {dtype.name} samples. Version 1 reads uint8, uint16 and float32 TIFF; "
            "export the image in one of those formats (16-bit or float32 keeps full precision).",
        )
    if photometric == "PALETTE":
        raise _unsupported("UNSUPPORTED_COLOR_MODE", "Palette (indexed-color) TIFFs are not supported. Export as RGB or grayscale.")
    if photometric == "SEPARATED":
        raise _unsupported("UNSUPPORTED_COLOR_MODE", "CMYK TIFFs are not supported. Export the image as RGB or grayscale.")
    if photometric == "MINISWHITE":
        raise _unsupported("UNSUPPORTED_COLOR_MODE", "Inverted (white-is-zero) grayscale TIFFs are not supported. Export with black as zero.")
    if photometric not in ("MINISBLACK", "RGB"):
        raise _unsupported("UNSUPPORTED_COLOR_MODE", f"TIFF photometric type {photometric} is not supported. Export as RGB or grayscale.")
    if extra or samples == 4:
        raise _unsupported(
            "ALPHA_NOT_SUPPORTED",
            "This TIFF has an alpha (transparency) channel, which is not supported. Export it without alpha.",
        )

    if photometric == "MINISBLACK" and axes == "YX" and samples == 1:
        layout, (h, w) = "mono", shape
    elif photometric == "RGB" and axes == "YXS" and shape[2] == 3:
        layout, (h, w) = "rgb", shape[:2]
    elif photometric == "RGB" and axes == "SYX" and shape[0] == 3:
        layout, (h, w) = "rgb", shape[1:]
    else:
        raise _unsupported(
            "UNSUPPORTED_TIFF_LAYOUT",
            f"This TIFF has an unsupported layout (axes {axes}, shape {shape}). "
            "Export a single grayscale or RGB image.",
        )
    if orientation in (5, 6, 7, 8):
        w, h = h, w
    check_pixel_limit(w, h, max_pixels)
    return {
        "format": "tiff",
        "width": int(w),
        "height": int(h),
        "channel_layout": layout,
        "bit_depth": dtype.itemsize * 8,
        "dtype": dtype.name,
        "info": {
            "axes": axes,
            "shape": list(shape),
            "photometric": photometric,
            "orientation": orientation,
            "has_icc_profile": icc is not None,
        },
        "questions": [question_state()],
        "candidates": [],
    }


def read_tiff(path: Path, source_hash: str, max_pixels: int, state: str) -> ImageData:
    meta = inspect_tiff(path, max_pixels)
    info = meta["info"]
    try:
        arr = tifffile.imread(path)
        with tifffile.TiffFile(path) as tif:
            icc = tif.pages[0].tags["InterColorProfile"].value if "InterColorProfile" in tif.pages[0].tags else None
    except Exception as exc:
        raise ProcessingError("CORRUPT_FILE", "This TIFF could not be decoded.", str(exc)) from exc
    if info["axes"] == "SYX":
        arr = np.moveaxis(arr, 0, -1)
    orientation = int(info["orientation"])
    arr = apply_orientation(arr, orientation)
    notes: list[str] = []
    icc_state = "none"
    if icc is not None and meta["channel_layout"] == "rgb":
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            if "srgb" in ImageCms.getProfileDescription(src).lower():
                icc_state = "srgb"
            elif arr.dtype == np.uint8 and state == "rendered":
                dst = ImageCms.createProfile("sRGB")
                img = ImageCms.profileToProfile(Image.fromarray(arr, "RGB"), src, dst, outputMode="RGB")
                arr = np.asarray(img)
                icc_state = "converted_to_srgb"
            else:
                icc_state = "present_not_applied"
                notes.append(
                    "The embedded color profile is not sRGB and was not applied (no precision-preserving conversion path); "
                    "values are treated as already sRGB-encoded."
                )
        except Exception:
            icc_state = "unreadable"
    valid = np.isfinite(arr) if arr.dtype.kind == "f" else np.ones(arr.shape[:2] if arr.ndim == 3 else arr.shape, dtype=bool)
    if valid.ndim == 3:
        valid = valid.all(axis=2)
    return build_image(
        arr.astype(np.float32) if arr.dtype != np.float32 else arr,
        valid,
        state=state,
        source_dtype=arr.dtype.name if arr.dtype.name != "float32" else "float32",
        source_bit_depth=meta["bit_depth"],
        source_format="tiff",
        source_hash=source_hash,
        orientation_transform=f"TIFF orientation {orientation} ({ORIENTATION_NAMES.get(orientation, '?')}) applied once",
        units="TIFF sample values" if state == "linear" else "display",
        metadata={"tiff": info, "icc": icc_state},
        notes=notes,
    )
