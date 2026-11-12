"""Canonical image container and shared processing errors (no HTTP, DB or UI dependencies)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


class ProcessingError(Exception):
    """Error with a stable code and a readable message; ``detail`` is for developers only."""

    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class Cancelled(Exception):
    """Cooperative cancellation between stages."""


@dataclass
class Normalization:
    """Reversible *shared* scale/offset: normalized = (source_units - offset) / scale.

    The same pair is used for every channel; channels are never scaled independently.
    """

    kind: str  # "unit_range" | "shared_minmax" | "linear_shared"
    scale: float = 1.0
    offset: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "scale": self.scale, "offset": self.offset, "note": self.note}


@dataclass
class ImageData:
    """ImageData(pixels, channel_layout, domain, units, valid_mask, protected_mask, metadata,
    source_hash, orientation_transform, normalization).

    ``pixels`` is H x W (mono) or H x W x 3 (RGB), already in display orientation.
    Display-domain pixels are normalized so that 1.0 is the source's full-scale white.
    Linear-domain pixels are in source units; ``normalization`` is applied only for processing.
    """

    pixels: np.ndarray
    channel_layout: str  # "mono" | "rgb"
    domain: str  # "display" | "linear"
    units: str
    valid_mask: np.ndarray
    protected_mask: np.ndarray
    metadata: dict[str, Any]
    source_hash: str
    orientation_transform: str
    normalization: Normalization
    source_format: str = "jpeg"
    source_dtype: str = "uint8"
    source_bit_depth: int = 8
    flip_rows_on_export: bool = False  # FITS: rows were flipped for display; undo for FITS export
    header: Any = None  # astropy Header copy for FITS sources (never serialized by hash)
    notes: list[str] = field(default_factory=list)

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def channels(self) -> int:
        return 1 if self.pixels.ndim == 2 else int(self.pixels.shape[2])


LUMA = (0.2126, 0.7152, 0.0722)
