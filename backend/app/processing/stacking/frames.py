"""Read-only discovery and reading of frames for stacking.

Folders are scanned non-recursively; only FITS files are considered and nothing is ever written there. Frames are
classified from the IMAGETYP keyword (or the file-name prefix Seestar and most capture programs use) and by layout:
raw colour-filter-array (CFA) sub-frames, monochrome sub-frames, or already stacked RGB images (for merging nights).
"""
from __future__ import annotations

import warnings
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from ..imagedata import ProcessingError
from ..readers.fits import row_order

FITS_SUFFIXES = {".fit", ".fits", ".fts"}
MAX_FILES = 5000
_KIND_WORDS = {
    "light": ("light", "science", "object"),
    "dark": ("dark",),
    "flat": ("flat",),
    "bias": ("bias", "offset", "zero"),
}
BAYER_PATTERNS = ("RGGB", "BGGR", "GRBG", "GBRG")


@dataclass
class FrameInfo:
    path: str
    name: str
    kind: str  # light | dark | flat | bias | darkflat
    layout: str  # cfa | mono | rgb
    width: int
    height: int
    bayer: str | None
    exposure: float | None
    gain: float | None
    filter: str | None
    date_obs: str | None
    instrument: str | None
    stack_count: int
    flip_rows: bool
    hdu: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "FrameInfo":
        return FrameInfo(**{k: d[k] for k in FrameInfo.__dataclass_fields__})


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _kind_from(header, name: str) -> str | None:
    text = str(header.get("IMAGETYP", "") or header.get("FRAME", "") or "").strip().lower()
    stem = name.lower()
    if ("flat" in text and "dark" in text) or stem.startswith(("darkflat", "dark_flat", "flatdark", "flat_dark")):
        return "darkflat"
    for kind, words in _KIND_WORDS.items():
        if any(w in text for w in words):
            return kind
    for kind, words in _KIND_WORDS.items():
        if any(stem.startswith(w) for w in words):
            return kind
    return None


def flipped_pattern(pattern: str, height: int, flip: bool) -> str:
    """Bayer pattern after flipping rows for display: with an even height the two pattern rows swap."""
    if not flip or height % 2:
        return pattern
    return pattern[2:] + pattern[:2]


def inspect_frame(path: Path) -> FrameInfo | str:
    """Return frame metadata, or a short reason why the file cannot be used."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with fits.open(path, memmap=False, lazy_load_hdus=True) as hdul:
                for i, hdu in enumerate(hdul):
                    h = hdu.header
                    naxis = int(h.get("NAXIS", 0) or 0)
                    if naxis < 2 or not isinstance(hdu, (fits.PrimaryHDU, fits.ImageHDU)):
                        continue
                    dims = [int(h[f"NAXIS{k}"]) for k in range(1, naxis + 1)]
                    shape = tuple(reversed(dims))
                    sq = tuple(d for d in shape if d != 1)
                    bayer = str(h.get("BAYERPAT") or h.get("COLORTYP") or "").strip().upper() or None
                    flip, _ = row_order(h)
                    if len(sq) == 2:
                        layout = "cfa" if bayer in BAYER_PATTERNS else "mono"
                        hgt, wid = sq
                    elif len(sq) == 3 and sq[0] == 3:
                        layout, (hgt, wid), bayer = "rgb", sq[1:], None
                    elif len(sq) == 3 and sq[2] == 3:
                        layout, (hgt, wid), bayer = "rgb", sq[:2], None
                    else:
                        return f"unsupported layout {shape}"
                    kind = _kind_from(h, path.name) or "light"
                    return FrameInfo(
                        path=str(path), name=path.name, kind=kind, layout=layout, width=int(wid), height=int(hgt),
                        bayer=flipped_pattern(bayer, int(hgt), flip) if layout == "cfa" else None,
                        exposure=_num(h.get("EXPTIME", h.get("EXPOSURE"))), gain=_num(h.get("GAIN")),
                        filter=(str(h.get("FILTER")).strip() if h.get("FILTER") is not None else None),
                        date_obs=(str(h.get("DATE-OBS")) if h.get("DATE-OBS") else None),
                        instrument=(str(h.get("INSTRUME")).strip() if h.get("INSTRUME") else None),
                        stack_count=int(_num(h.get("STACKCNT")) or 1), flip_rows=bool(flip), hdu=i,
                    )
    except Exception as exc:  # unreadable/corrupt file: reported, never fatal for the scan
        return f"could not be read ({type(exc).__name__})"
    return "no image data"


def read_frame(info: FrameInfo) -> tuple[np.ndarray, Any]:
    """Physical values (BSCALE/BZERO applied once) as float32 in display orientation, plus a header copy.
    CFA/mono -> H x W; RGB -> H x W x 3."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with fits.open(info.path, memmap=False, do_not_scale_image_data=False, uint=True) as hdul:
            hdu = hdul[info.hdu]
            header = hdu.header.copy()
            data = np.asarray(hdu.data)
    data = data.astype(np.float32).reshape([d for d in data.shape if d != 1])
    if data.ndim == 3 and data.shape[0] == 3:
        data = np.moveaxis(data, 0, -1)
    if info.flip_rows:
        data = data[::-1]
    data = np.ascontiguousarray(data)
    data[~np.isfinite(data)] = 0.0
    return data, header


@dataclass
class FrameGroup:
    frames: list[FrameInfo] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ScanResult:
    folder: str
    frames: list[FrameInfo]
    skipped: list[dict[str, str]]

    def by_kind(self, kind: str) -> list[FrameInfo]:
        return [f for f in self.frames if f.kind == kind]


def scan_folder(folder: str | Path, force_kind: str | None = None) -> ScanResult:
    p = Path(folder)
    if not p.is_absolute():
        raise ProcessingError("FOLDER_NOT_ABSOLUTE", "Enter the full folder path, for example D:\\Seestar\\MyWorks\\M 45_sub.")
    if not p.is_dir():
        raise ProcessingError("FOLDER_NOT_FOUND", f"The folder {p} does not exist or is not a folder.")
    files = sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in FITS_SUFFIXES)
    if len(files) > MAX_FILES:
        raise ProcessingError("TOO_MANY_FRAMES", f"The folder has {len(files)} FITS files; at most {MAX_FILES} can be stacked at once.")
    frames, skipped = [], []
    for f in files:
        info = inspect_frame(f)
        if isinstance(info, str):
            skipped.append({"name": f.name, "reason": info})
            continue
        if force_kind:
            info.kind = force_kind
        frames.append(info)
    return ScanResult(str(p), frames, skipped)


def choose_lights(frames: list[FrameInfo], mode: str) -> tuple[str, FrameGroup]:
    """Pick the light frames to stack: raw sub-frames ("subs") or stacked RGB images ("sessions").

    Raw subs must share size, Bayer pattern and filter; the largest consistent group is used and the rest are listed
    with a reason. Stacked sessions may differ in size (they are registered and resampled)."""
    lights = [f for f in frames if f.kind == "light"]
    raw = [f for f in lights if f.layout in ("cfa", "mono")]
    rgb = [f for f in lights if f.layout == "rgb"]
    if mode == "auto":
        mode = "subs" if raw else "sessions"
    group = FrameGroup()
    pool = raw if mode == "subs" else rgb
    for f in lights:
        if f not in pool:
            group.excluded.append({"name": f.name, "reason": "stacked image (use 'Combine stacked images')" if f.layout == "rgb" else "raw sub-frame (use 'Stack sub-frames')"})
    if not pool:
        return mode, group
    if mode == "subs":
        key = lambda f: (f.layout, f.width, f.height, f.bayer, (f.filter or "").upper())  # noqa: E731
        counts = Counter(key(f) for f in pool)
        best = counts.most_common(1)[0][0]
        for f in pool:
            k = key(f)
            if k == best:
                group.frames.append(f)
            else:
                why = "different size" if (k[1], k[2]) != (best[1], best[2]) else "different filter" if k[4] != best[4] else "different colour pattern"
                group.excluded.append({"name": f.name, "reason": f"{why} from the main group"})
    else:
        filters = Counter((f.filter or "").upper() for f in pool)
        main = filters.most_common(1)[0][0]
        for f in pool:
            if (f.filter or "").upper() == main:
                group.frames.append(f)
            else:
                group.excluded.append({"name": f.name, "reason": "different filter from the main group"})
    return mode, group


def summarize(frames: list[FrameInfo]) -> dict[str, Any]:
    if not frames:
        return {"count": 0}
    exps = [(f.exposure or 0.0) * f.stack_count for f in frames]
    dates = sorted(f.date_obs[:10] for f in frames if f.date_obs)
    f0 = frames[0]
    return {
        "count": len(frames), "layout": f0.layout, "width": f0.width, "height": f0.height, "bayer": f0.bayer,
        "filter": f0.filter, "instrument": f0.instrument,
        "exposures": sorted({round(f.exposure, 3) for f in frames if f.exposure}),
        "total_exposure_s": float(sum(exps)) if any(exps) else None,
        "sub_frames": int(sum(f.stack_count for f in frames)), "nights": sorted(set(dates)),
    }
