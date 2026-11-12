"""Build ImageData from decoded numeric arrays (shared by the TIFF and FITS readers)."""
from __future__ import annotations

from typing import Any

import numpy as np

from ..imagedata import ImageData, Normalization

_INT_FULL_SCALE = {"uint8": 255.0, "uint16": 65535.0}


def build_image(
    raw: np.ndarray,
    valid: np.ndarray,
    *,
    state: str,
    source_dtype: str,
    source_bit_depth: int,
    source_format: str,
    source_hash: str,
    orientation_transform: str,
    units: str,
    metadata: dict[str, Any],
    header: Any = None,
    flip_rows_on_export: bool = False,
    notes: list[str] | None = None,
) -> ImageData:
    """``raw`` holds physical values (scaling already applied once) in display orientation."""
    keep64 = raw.dtype == np.float64 and source_dtype in ("float64", "int32", "int64", "uint32")
    work = np.float64 if keep64 else np.float32
    pixels = np.where(valid[..., None] if raw.ndim == 3 else valid, raw, 0).astype(work, copy=False)
    h, w = pixels.shape[:2]
    notes = list(notes or [])
    if state == "linear":
        return ImageData(
            pixels=pixels,
            channel_layout="mono" if pixels.ndim == 2 else "rgb",
            domain="linear",
            units=units,
            valid_mask=valid,
            protected_mask=np.zeros((h, w), dtype=bool),
            metadata=metadata,
            source_hash=source_hash,
            orientation_transform=orientation_transform,
            normalization=Normalization("linear_shared", note="resolved from valid pixels by the linear pipeline"),
            source_format=source_format,
            source_dtype=source_dtype,
            source_bit_depth=source_bit_depth,
            flip_rows_on_export=flip_rows_on_export,
            header=header,
            notes=notes,
        )
    # Rendered / already processed: one shared normalization to display range, never per channel.
    if source_dtype in _INT_FULL_SCALE:
        norm = Normalization("unit_range", scale=_INT_FULL_SCALE[source_dtype], offset=0.0, note=f"{source_dtype} / full scale")
    else:
        vals = pixels[valid] if valid.any() else pixels.reshape(-1)
        lo = float(vals.min()) if vals.size else 0.0
        hi = float(vals.max()) if vals.size else 1.0
        if lo >= 0.0 and hi <= 1.0 + 1e-6:
            norm = Normalization("unit_range", scale=1.0, offset=0.0, note="values already within 0..1")
        else:
            span = hi - lo if hi > lo else 1.0
            norm = Normalization(
                "shared_minmax", scale=span, offset=lo,
                note="shared minimum/maximum across all channels (no per-channel scaling)",
            )
            notes.append("Values outside 0..1 were mapped to display range with one shared scale for all channels.")
    display = ((pixels.astype(np.float64) - norm.offset) / norm.scale).astype(np.float32)
    display = np.where(valid[..., None] if display.ndim == 3 else valid, display, np.float32(0))
    return ImageData(
        pixels=display,
        channel_layout="mono" if display.ndim == 2 else "rgb",
        domain="display",
        units="display range, shared normalization",
        valid_mask=valid,
        protected_mask=np.zeros((h, w), dtype=bool),
        metadata=metadata,
        source_hash=source_hash,
        orientation_transform=orientation_transform,
        normalization=norm,
        source_format=source_format,
        source_dtype=source_dtype,
        source_bit_depth=source_bit_depth,
        flip_rows_on_export=flip_rows_on_export,
        header=header,
        notes=notes,
    )
