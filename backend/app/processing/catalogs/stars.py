"""Built-in star catalog (Gaia DR3 subset): file format, writer and cone reader.

Layout (little-endian): ``b"EAESTARS"``, uint32 header length, UTF-8 JSON header, zero padding to 8 bytes, then
``uint64 offsets[n_cells + 1]`` and four column arrays of ``n_stars`` values each: ``uint32 ra`` (ra / 360 * 2**32),
``int32 dec`` (dec / 90 * (2**31 - 1)), ``uint16 g`` (G magnitude in millimag) and ``int16 bp_rp`` (millimag; -32768 =
unknown). Stars are grouped into sky cells: 1-degree declination zones, each split into right-ascension cells no wider
than 1 degree on the sky; within a cell, brightest first. Positions are at the Gaia DR3 epoch (J2016.0); proper motion
is ignored (negligible at Seestar pixel scales for all but a handful of stars).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

MAGIC = b"EAESTARS"
FORMAT_VERSION = 1
G_LIMIT = 13.5
ZONE_DEG = 1.0
N_ZONES = 180
BPRP_UNKNOWN = -32768


def _zone_cells() -> np.ndarray:
    """Number of RA cells in each declination zone (cells at most 1 degree wide on the sky)."""
    out = np.empty(N_ZONES, np.int64)
    for k in range(N_ZONES):
        lo, hi = -90.0 + k * ZONE_DEG, -90.0 + (k + 1) * ZONE_DEG
        near_eq = 0.0 if lo < 0 < hi else min(abs(lo), abs(hi))
        out[k] = max(1, math.ceil(360.0 * math.cos(math.radians(near_eq))))
    return out


ZONE_CELLS = _zone_cells()
ZONE_START = np.concatenate([[0], np.cumsum(ZONE_CELLS)])
N_CELLS = int(ZONE_START[-1])


def cell_of(ra: np.ndarray, dec: np.ndarray) -> np.ndarray:
    zone = np.clip(np.floor((np.asarray(dec) + 90.0) / ZONE_DEG).astype(np.int64), 0, N_ZONES - 1)
    n = ZONE_CELLS[zone]
    col = np.minimum(np.floor(np.mod(ra, 360.0) / 360.0 * n).astype(np.int64), n - 1)
    return ZONE_START[zone] + col


def write_catalog(path: Path, ra, dec, g, bp_rp, source: str = "Gaia DR3 (gaiadr3.gaia_source)") -> dict[str, Any]:
    ra, dec, g, bp_rp = (np.asarray(a, np.float64) for a in (ra, dec, g, bp_rp))
    keep = np.isfinite(ra) & np.isfinite(dec) & np.isfinite(g) & (g < G_LIMIT)
    ra, dec, g, bp_rp = ra[keep], dec[keep], g[keep], bp_rp[keep]
    cell = cell_of(ra, dec)
    order = np.lexsort((dec, ra, g, cell))  # deterministic: cell, then brightness, then position
    ra, dec, g, bp_rp, cell = ra[order], dec[order], g[order], bp_rp[order], cell[order]
    counts = np.bincount(cell, minlength=N_CELLS)
    offsets = np.concatenate([[0], np.cumsum(counts)]).astype("<u8")
    header = {"format": FORMAT_VERSION, "g_limit": G_LIMIT, "zone_deg": ZONE_DEG, "n_cells": N_CELLS, "n_stars": int(ra.size),
              "epoch": "J2016.0", "source": source, "licence": "CC BY-SA 3.0 IGO",
              "credit": "ESA/Gaia/DPAC; Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1"}
    hb = json.dumps(header, sort_keys=True).encode()
    pad = (-(len(MAGIC) + 4 + len(hb))) % 8
    with open(path, "wb") as fh:
        fh.write(MAGIC + np.uint32(len(hb)).astype("<u4").tobytes() + hb + b"\0" * pad)
        fh.write(offsets.tobytes())
        fh.write(np.clip(np.round(np.mod(ra, 360.0) / 360.0 * 2**32), 0, 2**32 - 1).astype("<u4").tobytes())
        fh.write(np.round(dec / 90.0 * (2**31 - 1)).astype("<i4").tobytes())
        fh.write(np.round(g * 1000).astype("<u2").tobytes())
        bp = np.where(np.isfinite(bp_rp), np.round(np.clip(bp_rp, -32.7, 32.7) * 1000), BPRP_UNKNOWN)
        fh.write(bp.astype("<i2").tobytes())
    return header


def angular_distance(ra0, dec0, ra, dec):
    r0, d0, r, d = map(np.radians, (ra0, dec0, ra, dec))
    s = np.sin((d - d0) / 2) ** 2 + np.cos(d0) * np.cos(d) * np.sin((r - r0) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(s, 0, 1))))


class StarCatalog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        raw = np.memmap(self.path, dtype=np.uint8, mode="r")
        if bytes(raw[:8]) != MAGIC:
            raise ValueError("Not an EasyAstroEnhance star catalog.")
        hl = int(np.frombuffer(bytes(raw[8:12]), "<u4")[0])
        self.header: dict[str, Any] = json.loads(bytes(raw[12:12 + hl]).decode())
        if self.header.get("format") != FORMAT_VERSION or self.header.get("n_cells") != N_CELLS:
            raise ValueError("Unsupported star catalog format.")
        base = 12 + hl + ((-(12 + hl)) % 8)
        n, nc = int(self.header["n_stars"]), N_CELLS
        self.offsets = np.frombuffer(raw, "<u8", nc + 1, base)
        p = base + 8 * (nc + 1)
        self._ra = np.frombuffer(raw, "<u4", n, p)
        self._dec = np.frombuffer(raw, "<i4", n, p + 4 * n)
        self._g = np.frombuffer(raw, "<u2", n, p + 8 * n)
        self._bprp = np.frombuffer(raw, "<i2", n, p + 10 * n)
        self._raw = raw

    def cells_in_cone(self, ra0: float, dec0: float, radius: float) -> list[int]:
        dlo, dhi = max(-90.0, dec0 - radius), min(90.0, dec0 + radius)
        out: list[int] = []
        for k in range(int((dlo + 90) // ZONE_DEG), min(N_ZONES, int((dhi + 90) // ZONE_DEG) + 1)):
            n = int(ZONE_CELLS[k])
            zlo, zhi = -90.0 + k * ZONE_DEG, -90.0 + (k + 1) * ZONE_DEG
            far = max(abs(zlo), abs(zhi))  # the zone edge nearest the pole has the widest RA span per degree
            cosd = math.cos(math.radians(min(far, 89.999)))
            half = radius / cosd + 360.0 / n
            if half >= 180.0 or dhi >= 89.5 or dlo <= -89.5:
                out.extend(range(int(ZONE_START[k]), int(ZONE_START[k]) + n))
                continue
            c0 = math.floor(((ra0 - half) % 360.0) / 360.0 * n)
            span = math.ceil(2 * half / 360.0 * n) + 1
            out.extend(int(ZONE_START[k]) + ((c0 + j) % n) for j in range(min(span, n)))
        return sorted(set(out))

    def cone(self, ra0: float, dec0: float, radius: float, g_max: float | None = None) -> dict[str, np.ndarray]:
        """Stars within ``radius`` degrees of (ra0, dec0), brightest first: ra, dec (deg), g, bp_rp (NaN when unknown)."""
        idx = [np.arange(int(self.offsets[c]), int(self.offsets[c + 1])) for c in self.cells_in_cone(ra0, dec0, radius)]
        sel = np.concatenate(idx) if idx else np.zeros(0, np.int64)
        ra = self._ra[sel].astype(np.float64) / 2**32 * 360.0
        dec = self._dec[sel].astype(np.float64) / (2**31 - 1) * 90.0
        g = self._g[sel].astype(np.float64) / 1000.0
        bp = self._bprp[sel].astype(np.float64)
        bp = np.where(bp == BPRP_UNKNOWN, np.nan, bp / 1000.0)
        keep = angular_distance(ra0, dec0, ra, dec) <= radius
        if g_max is not None:
            keep &= g <= g_max
        order = np.argsort(g[keep], kind="stable")
        return {k: v[keep][order] for k, v in (("ra", ra), ("dec", dec), ("g", g), ("bp_rp", bp))}


@lru_cache(maxsize=2)
def open_catalog(path: str) -> StarCatalog:
    return StarCatalog(Path(path))
