"""OpenNGC deep-sky object catalog: positions, sizes and names (CC BY-SA 4.0, Mattia Verga and contributors).

Used to turn a typed target name into approximate solve coordinates and to place labels on a sharing copy. Object
identity never changes pixel values (fidelity rule 2)."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

# OpenNGC types worth labelling (stars, duplicates and non-existent entries are left out)
TYPE_LABELS = {
    "G": "galaxy", "GPair": "galaxy pair", "GTrpl": "galaxy triplet", "GGroup": "galaxy group", "OCl": "open cluster",
    "GCl": "globular cluster", "Cl+N": "cluster with nebula", "PN": "planetary nebula", "HII": "emission nebula",
    "EmN": "emission nebula", "RfN": "reflection nebula", "Neb": "nebula", "SNR": "supernova remnant", "DrkN": "dark nebula",
    "*Ass": "stellar association", "Nova": "nova",
}


@dataclass(frozen=True)
class DeepSkyObject:
    name: str  # display name, e.g. "M 31" or "NGC 7000"
    id: str  # catalog designation, e.g. "NGC0224"
    type: str
    ra: float
    dec: float
    major_arcmin: float | None
    minor_arcmin: float | None
    pa_deg: float | None
    mag: float | None
    aliases: tuple[str, ...]
    common: tuple[str, ...]


def _sexa(value: str, hours: bool) -> float:
    parts = [float(p) for p in value.replace("+", "").replace("-", " ").split(":")]
    sign = -1.0 if value.strip().startswith("-") else 1.0
    deg = abs(parts[0]) + parts[1] / 60 + parts[2] / 3600
    return deg * 15.0 if hours else sign * deg


def _designation(raw: str) -> str:
    m = re.match(r"^(NGC|IC)0*(\d+)(.*)$", raw)
    return f"{m.group(1)} {m.group(2)}{m.group(3)}" if m else raw


def _float(v: str) -> float | None:
    try:
        return float(v) if v.strip() else None
    except ValueError:
        return None


def load_objects(paths: list[Path]) -> list[DeepSkyObject]:
    out: list[DeepSkyObject] = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                t = row.get("Type", "")
                if t not in TYPE_LABELS or not row.get("RA") or not row.get("Dec"):
                    continue
                messier = row.get("M", "").strip()
                name = f"M {int(messier)}" if messier else _designation(row["Name"])
                aliases = {_designation(row["Name"])}
                if messier:
                    aliases.add(f"M {int(messier)}")
                for key, prefix in (("NGC", "NGC"), ("IC", "IC")):
                    for v in filter(None, (row.get(key) or "").split(",")):
                        aliases.add(f"{prefix} {v.lstrip('0')}")
                for ident in (row.get("Identifiers") or "").split(","):
                    m = re.match(r"^C 0*(\d+)$", ident.strip())  # Caldwell number
                    if m:
                        aliases.add(f"C {m.group(1)}")
                common = tuple(c.strip() for c in (row.get("Common names") or "").split(",") if c.strip())
                out.append(DeepSkyObject(
                    name=name, id=row["Name"], type=t, ra=_sexa(row["RA"], True), dec=_sexa(row["Dec"], False),
                    major_arcmin=_float(row.get("MajAx", "")), minor_arcmin=_float(row.get("MinAx", "")),
                    pa_deg=_float(row.get("PosAng", "")), mag=_float(row.get("V-Mag", "")) or _float(row.get("B-Mag", "")),
                    aliases=tuple(sorted(aliases)), common=common,
                ))
    return out


@lru_cache(maxsize=1)
def objects_from(paths: tuple[str, ...]) -> tuple[DeepSkyObject, ...]:
    return tuple(load_objects([Path(p) for p in paths]))


def _norm(s: str) -> str:
    s = s.strip().upper().replace("MESSIER", "M")
    s = re.sub(r"[\s_\-]+", "", s)
    return re.sub(r"^(M|NGC|IC|C)0*(\d)", r"\1\2", s)


def resolve_name(objects: tuple[DeepSkyObject, ...], name: str) -> DeepSkyObject | None:
    """A typed target ("M31", "NGC 7000", "Orion Nebula", Seestar's "M 31_mosaic") resolved to its catalog entry."""
    q = _norm(re.sub(r"(_mosaic|_sub)$", "", name.strip(), flags=re.I))
    if not q:
        return None
    for o in objects:
        if any(_norm(a) == q for a in o.aliases):
            return o
    for o in objects:
        if any(_norm(c) == q for c in o.common):
            return o
    return None


def in_cone(objects: tuple[DeepSkyObject, ...], ra0: float, dec0: float, radius: float) -> list[DeepSkyObject]:
    if not objects:
        return []
    ra = np.array([o.ra for o in objects])
    dec = np.array([o.dec for o in objects])
    r0, d0, r, d = map(np.radians, (ra0, dec0, ra, dec))
    cosd = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(r - r0)
    keep = np.degrees(np.arccos(np.clip(cosd, -1, 1))) <= radius
    return [o for o, k in zip(objects, keep) if k]
