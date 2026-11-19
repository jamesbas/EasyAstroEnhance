"""Offline reference-star RGB calibration, using an existing FITS sky solution."""
from __future__ import annotations

import csv
import io
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.wcs import NoConvergence, WCS
from astropy.wcs.utils import skycoord_to_pixel
from scipy.spatial import cKDTree

from .imagedata import ImageData, ProcessingError
from .linear_prep import measure_star_fluxes

MAX_BYTES = 2 * 1024 * 1024
MIN_MATCHES = 8
COLUMNS = ("ra_deg", "dec_deg", "r_over_g", "b_over_g")


def parse_catalog(data: bytes) -> np.ndarray:
    if len(data) > MAX_BYTES:
        raise ProcessingError("CATALOG_TOO_LARGE", "Use a catalog field extract no larger than 2 MiB.")
    try:
        rows = csv.DictReader(io.StringIO(data.decode("utf-8-sig")), strict=True)
        if not rows.fieldnames or len(set(rows.fieldnames)) != len(rows.fieldnames) or not set(COLUMNS) <= set(rows.fieldnames):
            raise ValueError(f"Required columns: {', '.join(COLUMNS)}.")
        values = np.asarray([[float(row[key]) for key in COLUMNS] for row in rows], dtype=np.float64).reshape(-1, 4)
        if len(values) < MIN_MATCHES or not np.isfinite(values).all():
            raise ValueError(f"Supply at least {MIN_MATCHES} rows with finite coordinates and color ratios.")
        if ((values[:, 0] < 0) | (values[:, 0] >= 360) | (np.abs(values[:, 1]) > 90)).any() or (values[:, 2:] <= 0).any():
            raise ValueError("RA must be in [0, 360), Dec in [-90, 90], and ratios must be positive.")
        if len(np.unique(values[:, :2], axis=0)) != len(values):
            raise ValueError("Reference positions must not be duplicated.")
        return values
    except (UnicodeError, ValueError, TypeError, csv.Error) as exc:
        raise ProcessingError("BAD_CATALOG", f"Cannot read the reference CSV: {exc}") from exc


def load_catalog(folder: Path | None, digest: str) -> np.ndarray:
    if folder is None:
        raise ProcessingError("CATALOG_MISSING", "Import a local reference catalog first.")
    try:
        with (folder / f"{digest}.csv").open("rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ProcessingError("CATALOG_MISSING", "The local reference catalog is unavailable. Reimport it.") from exc
    if sha256(data).hexdigest() != digest:
        raise ProcessingError("CATALOG_CHANGED", "The local reference catalog changed on disk. Reimport it.")
    return parse_catalog(data)


def celestial_wcs(header) -> WCS | None:
    if header is None:
        return None
    try:
        wcs = WCS(header, naxis=[1, 2]).celestial
        return wcs if wcs.has_celestial else None
    except (ValueError, TypeError):
        return None


def catalog_balance(image: ImageData, corrected: np.ndarray, mask: np.ndarray | None, saturated: np.ndarray,
                    valid: np.ndarray, sigma: float, folder: Path | None, digest: str) -> dict[str, Any]:
    def skipped(reason: str, **facts) -> dict[str, Any]:
        return {"sha256": digest, "status": "skipped", "reason": reason, **facts}

    wcs = celestial_wcs(image.header)
    if wcs is None:
        return skipped("Catalog calibration needs a solved FITS with celestial WCS.")
    if mask is None:
        return skipped("No reliable field stars were detected.")
    try:
        refs = load_catalog(folder, digest)
    except ProcessingError as exc:
        return skipped(exc.message)
    try:
        coords = SkyCoord(ra=refs[:, 0], dec=refs[:, 1], unit="deg", frame="icrs")
        x, y = skycoord_to_pixel(coords, wcs, origin=0)
    except (ValueError, NoConvergence) as exc:
        return skipped(f"Could not project the reference catalog with this WCS: {exc}")
    if image.flip_rows_on_export:
        y = image.height - 1 - y
    in_view = (x >= 0) & (x < image.width) & (y >= 0) & (y < image.height)
    positions = np.column_stack((x[in_view], y[in_view]))
    if len(positions) < MIN_MATCHES:
        return skipped("Too few reference stars land in the image; check the catalog field and WCS.", in_view=len(positions))
    samples = list(measure_star_fluxes(corrected, mask, saturated, sigma, valid))
    if len(samples) < MIN_MATCHES:
        return skipped("Too few isolated, unsaturated stars can be measured.")
    distances, neighbors = cKDTree(positions).query(np.asarray([p for p, _ in samples]), k=2, distance_upper_bound=2.5)
    pairs: dict[int, tuple[int, float]] = {}
    for j in np.argsort(distances[:, 0]):
        d0, d1 = distances[j]
        if np.isfinite(d0) and d1 - d0 > 0.75:
            pairs.setdefault(int(neighbors[j, 0]), (int(j), float(d0)))
    if len(pairs) < MIN_MATCHES:
        return skipped("Too few unambiguous WCS matches within 2.5 pixels.", matched=len(pairs))
    expected = refs[in_view][:, 2:]
    flux = np.asarray([samples[j][1] for j, _ in pairs.values()], dtype=np.float64)
    log_ratio = np.log(expected[list(pairs)]) - np.log(flux[:, [0, 2]] / flux[:, [1]])
    center = np.median(log_ratio, axis=0)
    error = np.max(np.abs(log_ratio - center), axis=1)
    keep = error <= min(0.25, max(0.06, 3 * float(np.median(error))))
    if keep.sum() < max(MIN_MATCHES, 0.65 * len(pairs)):
        return skipped("Reference and measured star colors disagree too much. Check passbands and WCS.", matched=len(pairs))
    r, b = np.exp(np.median(log_ratio[keep], axis=0))
    if not (0.25 <= r <= 4 and 0.25 <= b <= 4):
        return skipped("The fitted channel gain is outside the safe 0.25x to 4x range.", matched=len(pairs))
    return {
        "sha256": digest, "status": "applied", "reason": None, "matched": len(pairs), "used": int(keep.sum()),
        "rms_px": float(np.sqrt(np.mean(np.square([d for _, d in pairs.values()])))),
        "gains_rgb": [float(r), 1.0, float(b)],
        "method": "Robust WCS-matched reference RGB ratios; relative color, not an absolute flux calibration.",
    }
