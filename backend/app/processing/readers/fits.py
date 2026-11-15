"""FITS intake and reading (Astropy).

Scaling strategy (documented, applied exactly once): Astropy applies BSCALE/BZERO when data
is accessed, so we request physical values, copy the header *before* touching ``hdu.data`` and
never rescale. The original scaling cards are recorded in metadata and in the saved header.

Row order: FITS row 0 is the bottom of the image. For display the rows are flipped once (unless
ROWORDER is TOP-DOWN) and flipped back on FITS export so WCS and array order stay consistent.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from ..imagedata import ImageData, ProcessingError
from .build import build_image
from .common import check_pixel_limit, question_state

_NON_COLOR_CTYPES = ("VRAD", "VELO", "FREQ", "WAVE", "AWAV", "STOKES", "TIME", "COMPLEX", "VOPT", "ZOPT")
_SENSITIVE_KEYS = (
    "OBSERVER", "OBSERVAT", "SITELAT", "SITELONG", "SITEELEV", "LATITUDE", "LONGITUD", "LONGITUDE",
    "LAT-OBS", "LONG-OBS", "ALT-OBS", "GEOLAT", "GEOLON", "GEOELEV", "OBSGEO-X", "OBSGEO-Y", "OBSGEO-Z",
    "OBSGEO-L", "OBSGEO-B", "OBSGEO-H", "OBSLAT", "OBSLON", "OBSALT", "GPSLAT", "GPSLONG", "GPSLON",
    "SITENAME", "CITY", "CONTACT", "AUTHOR", "USERNAME",
)
SENSITIVE_KEYS = frozenset(_SENSITIVE_KEYS)


def _classify(hdu_index: int, hdu: Any) -> dict[str, Any] | None:
    if not isinstance(hdu, (fits.PrimaryHDU, fits.ImageHDU, fits.CompImageHDU)):
        return None
    header = hdu.header
    naxis = int(header.get("ZNAXIS", header.get("NAXIS", 0)) or 0)
    if naxis == 0:
        return None
    key = "ZNAXIS" if "ZNAXIS" in header else "NAXIS"
    dims_fits = [int(header[f"{key}{i}"]) for i in range(1, naxis + 1)]  # NAXIS1 = fastest axis
    np_shape = tuple(reversed(dims_fits))
    squeezed = tuple(d for d in np_shape if d != 1)
    bitpix = int(header.get("ZBITPIX", header.get("BITPIX", 0)))
    name = str(header.get("EXTNAME", "") or hdu.name or ("PRIMARY" if hdu_index == 0 else f"HDU {hdu_index}"))
    cand: dict[str, Any] = {
        "index": hdu_index,
        "name": name,
        "shape": list(np_shape),
        "bitpix": bitpix,
        "kind": "other",
        "supported": False,
        "documented": True,
        "message": "",
    }
    bayer = header.get("BAYERPAT") or header.get("CFA") or header.get("COLORTYP")
    if len(squeezed) == 2:
        if bayer:
            cand.update(
                kind="cfa",
                message="This file needs debayering or stacking first. Export a stacked RGB or monochrome image and add it here.",
            )
        else:
            cand.update(kind="mono", supported=True)
            if len(np_shape) > 2:
                cand["message"] = f"Length-1 axes {np_shape} were treated as a single 2-D image."
        cand["height"], cand["width"] = squeezed
    elif len(squeezed) == 3 and np_shape == squeezed and squeezed[0] == 3:
        ctype3 = str(header.get("CTYPE3", "") or "").strip().upper()
        if ctype3 and ctype3 != "RGB" and ctype3 in _NON_COLOR_CTYPES:
            cand.update(kind="cube", message=f"This is a data cube with a {ctype3} axis, not a color image.")
        else:
            cand.update(kind="rgb_planes", supported=True, documented=(ctype3 == "RGB"))
            cand["height"], cand["width"] = squeezed[1], squeezed[2]
    elif len(squeezed) == 3 and np_shape == squeezed and squeezed[2] == 3:
        cand.update(kind="rgb_last", supported=True, documented=False)
        cand["height"], cand["width"] = squeezed[0], squeezed[1]
    elif len(squeezed) >= 3:
        cand.update(
            kind="cube",
            message=f"This is a {len(squeezed)}-dimensional data cube {squeezed}. Export a single stacked RGB or "
            "monochrome image instead; cubes are not supported in version 1.",
        )
    else:
        cand.update(kind="other", message="This HDU does not contain a 2-D image.")
    return cand


def inspect_fits(path: Path, max_pixels: int) -> dict[str, Any]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with fits.open(path, memmap=False, lazy_load_hdus=True, ignore_missing_end=False) as hdul:
                candidates = []
                for i, hdu in enumerate(hdul):
                    c = _classify(i, hdu)
                    if c:
                        candidates.append(c)
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError("CORRUPT_FILE", "This FITS file could not be read. It may be damaged or truncated.", str(exc)) from exc
    if not candidates:
        raise ProcessingError("NO_IMAGE_HDU", "This FITS file does not contain an image.")
    supported = [c for c in candidates if c["supported"]]
    if not supported:
        first = candidates[0]
        code = {"cfa": "UNSUPPORTED_CFA", "cube": "UNSUPPORTED_CUBE"}.get(first["kind"], "UNSUPPORTED_FITS")
        raise ProcessingError(code, first["message"] or "This FITS image layout is not supported.")
    for c in supported:
        check_pixel_limit(c["width"], c["height"], max_pixels)
    primary = supported[0]
    questions = [question_state()]
    if len(supported) > 1:
        questions.insert(
            0,
            {
                "id": "hdu",
                "kind": "hdu",
                "title": "Which image should be used?",
                "options": [
                    {"value": c["index"], "label": f"{c['name']} — {c['width']}×{c['height']}", "help": c["kind"]}
                    for c in supported
                ],
            },
        )
    return {
        "format": "fits",
        "width": int(primary["width"]),
        "height": int(primary["height"]),
        "channel_layout": "rgb" if primary["kind"] in ("rgb_planes", "rgb_last") else "mono",
        "bit_depth": abs(primary["bitpix"]),
        "dtype": f"bitpix{primary['bitpix']}",
        "info": {},
        "questions": questions,
        "candidates": candidates,
    }


def layout_question(candidate: dict[str, Any]) -> dict[str, Any]:
    where = "first" if candidate["kind"] == "rgb_planes" else "last"
    return {
        "id": "layout",
        "kind": "layout",
        "title": "Are these red, green and blue channels?",
        "help": f"The {where} axis has 3 entries, but the file does not say they are RGB. A shape starting with 3 is not always color.",
        "options": [
            {"value": candidate["kind"], "label": "Yes — red, green, blue", "help": "Use as a color image."},
            {"value": "not_rgb", "label": "No", "help": "These are not color channels; the file will be rejected with an explanation."},
        ],
    }


def is_seestar(header) -> bool:
    text = " ".join(str(header.get(k, "") or "") for k in ("CREATOR", "INSTRUME", "TELESCOP"))
    return "seestar" in text.lower()


def row_order(header) -> tuple[bool, str]:
    """Return (flip_rows_for_display, orientation note).

    FITS assumes row 0 is the bottom of the image. ZWO Seestar stacks are written top-down without a ROWORDER
    keyword (verified against the telescope's own JPG), so they are kept as stored.
    """
    roworder = str(header.get("ROWORDER", "") or "").strip().upper()
    if roworder == "TOP-DOWN":
        return False, "ROWORDER=TOP-DOWN: rows kept as stored"
    if roworder == "BOTTOM-UP":
        return True, "ROWORDER=BOTTOM-UP: rows flipped vertically once for display; flipped back on FITS export"
    if is_seestar(header):
        return False, "ZWO Seestar file without ROWORDER: rows are stored top-down and kept as stored (matches the telescope's JPG)"
    return True, "FITS rows flipped vertically once for display (row 0 is the bottom of the image); flipped back on FITS export"


def sensitive_keywords_in(header) -> list[str]:
    return [k for k in header.keys() if k.upper() in SENSITIVE_KEYS]


def header_to_text(header) -> str:
    return header.tostring(sep="\n", endcard=True)


def read_fits(
    path: Path,
    source_hash: str,
    max_pixels: int,
    state: str,
    hdu_index: int | None = None,
    layout: str | None = None,
) -> ImageData:
    insp = inspect_fits(path, max_pixels)
    cands = {c["index"]: c for c in insp["candidates"] if c["supported"]}
    if hdu_index is None:
        hdu_index = next(iter(cands))
    if hdu_index not in cands:
        raise ProcessingError("INVALID_HDU", "The selected HDU is not a supported image.")
    cand = cands[hdu_index]
    if cand["kind"] in ("rgb_planes", "rgb_last") and not cand["documented"] and layout != cand["kind"]:
        raise ProcessingError(
            "AMBIGUOUS_LAYOUT",
            "Please confirm whether the three planes are red, green and blue channels before processing.",
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with fits.open(path, memmap=False, do_not_scale_image_data=False, uint=True) as hdul:
                hdu = hdul[hdu_index]
                header = hdu.header.copy()  # copied before data access; Astropy mutates scaling cards on access
                scaling = {
                    "bitpix": int(header.get("BITPIX", 0)),
                    "bscale": header.get("BSCALE"),
                    "bzero": header.get("BZERO"),
                    "blank": header.get("BLANK"),
                    "applied_by": "astropy (physical values returned once; not rescaled again)",
                }
                data = np.asarray(hdu.data)
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError("CORRUPT_FILE", "The image data in this FITS file could not be read.", str(exc)) from exc

    source_dtype = data.dtype.newbyteorder("=").name
    blank = scaling["blank"]
    data = data.astype(data.dtype.newbyteorder("="), copy=False)
    if data.dtype.kind in "iu":
        valid_raw = np.ones(data.shape, dtype=bool)
        if blank is not None and scaling["bscale"] in (None, 1) and scaling["bzero"] in (None, 0):
            valid_raw = data != blank  # BLANK applies to raw integers when no scaling converted them to NaN
        data = data.astype(np.float64 if data.dtype.itemsize >= 4 else np.float32)
    else:
        valid_raw = np.ones(data.shape, dtype=bool)
        if data.dtype == np.float16:
            data = data.astype(np.float32)

    orig_shape = list(data.shape)
    data = data.reshape([d for d in data.shape if d != 1] or [1])
    valid_raw = valid_raw.reshape(data.shape)
    if cand["kind"] == "rgb_planes":
        data = np.moveaxis(data, 0, -1)
        valid_raw = np.moveaxis(valid_raw, 0, -1)
    finite = np.isfinite(data) & valid_raw
    valid = finite.all(axis=2) if data.ndim == 3 else finite
    raw = np.where(finite, data, 0)

    flip, orient = row_order(header)
    if flip:
        raw = np.ascontiguousarray(raw[::-1])
        valid = np.ascontiguousarray(valid[::-1])
    units = str(header.get("BUNIT", "") or "unspecified (assumed ADU)")
    notes = [cand["message"]] if cand.get("message") else []
    if not valid.all():
        notes.append(f"{int((~valid).sum())} non-finite or BLANK pixels are masked (not treated as dark sky).")
    return build_image(
        raw,
        valid,
        state=state,
        source_dtype=source_dtype,
        source_bit_depth=abs(scaling["bitpix"]),
        source_format="fits",
        source_hash=source_hash,
        orientation_transform=orient,
        units=units,
        metadata={"fits": {"hdu": hdu_index, "hdu_name": cand["name"], "layout": cand["kind"], "scaling": scaling, "shape": orig_shape}},
        header=header,
        flip_rows_on_export=flip,
        notes=notes,
    )
