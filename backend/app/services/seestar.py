"""Import from Seestar (H12): find a Seestar ``MyWorks`` folder and summarize it by target, read-only.

The Seestar app (or a copy of the telescope's storage) keeps one folder per target - ``M 31`` with the telescope's stacks
(``Stacked_<frames>_<target>_<exposure>s_<filter>_<date>-<time>.fit``) and ``M 31_sub`` with the sub-frames; mosaics use
``M 31_mosaic`` / ``M 31_mosaic_sub``; ``Lunar``, ``Solar`` and ``Planetary`` hold videos. Only directory listings and file
names are read here; nothing is opened, created or changed.
"""
from __future__ import annotations

import os
import re
import string
from datetime import datetime
from pathlib import Path
from typing import Any

SETTING = "seestar.myworks"
FITS = (".fit", ".fits", ".fts")
VIDEO = (".avi", ".ser")
STACKED = re.compile(r"^(?:DSO_)?Stacked_(?P<frames>\d+)_(?:mosaic_)?(?P<target>.+?)_(?P<exp>[\d.]+)s_(?:(?P<filter>[A-Za-z][A-Za-z0-9]*)_)?"
                     r"(?P<date>\d{8})[-_](?P<time>\d{6})", re.I)
SOLAR_SYSTEM = {"lunar": "moon", "lunar_video": "moon", "lunar_photo": "moon", "solar": "sun", "solar_video": "sun",
                "planetary": "planet", "planetary_video": "planet"}


def candidates(recent_stack_folders: list[str]) -> list[str]:
    """Likely MyWorks folders: parents of recently stacked folders, then common locations on every drive."""
    out: list[str] = []

    def add(p: Path) -> None:
        s = str(p)
        if s not in out and p.is_dir():
            out.append(s)

    for r in recent_stack_folders:
        parent = Path(r).parent
        if any(d.name.lower().endswith("_sub") for d in _dirs(parent)):
            add(parent)
    roots = [f"{d}:\\" for d in string.ascii_uppercase if os.path.isdir(f"{d}:\\")] if os.name == "nt" else ["/"]
    home = Path.home()
    for base in [*(Path(r) for r in roots), home, home / "Pictures", home / "Documents", home / "Desktop"]:
        for rel in ("Seestar/MyWorks", "MyWorks", "Seestar/MyWorks/MyWorks"):
            add(base / rel)
    return out


def _dirs(p: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(p) as it:
            return [e for e in it if e.is_dir(follow_symlinks=False)]
    except OSError:
        return []


def _files(p: Path, suffixes: tuple[str, ...]) -> list[os.DirEntry]:
    try:
        with os.scandir(p) as it:
            return [e for e in it if e.is_file(follow_symlinks=False) and e.name.lower().endswith(suffixes)]
    except OSError:
        return []


def _stack_info(e: os.DirEntry) -> dict[str, Any]:
    m = STACKED.match(e.name)
    info: dict[str, Any] = {"path": e.path, "name": e.name, "bytes": e.stat().st_size}
    if m:
        frames, exp = int(m["frames"]), float(m["exp"])
        when = datetime.strptime(m["date"] + m["time"], "%Y%m%d%H%M%S")
        info.update(frames=frames, exposure_s=exp, total_exposure_s=frames * exp,
                    filter=m["filter"].upper() if m["filter"] else None, taken=when.isoformat())
    else:
        info["taken"] = datetime.fromtimestamp(e.stat().st_mtime).isoformat(timespec="seconds")
    return info


def scan(path: str) -> dict[str, Any]:
    root = Path(path.strip().strip('"'))
    if not root.is_absolute() or not root.is_dir():
        return {"path": str(root), "targets": [], "error": "That folder does not exist or is not reachable."}
    dirs = {e.name: e for e in _dirs(root)}
    targets: dict[str, dict[str, Any]] = {}
    for name, e in sorted(dirs.items(), key=lambda kv: kv[0].lower()):
        lower = name.lower()
        if lower in SOLAR_SYSTEM:
            videos = _files(Path(e.path), VIDEO)
            t = targets.setdefault(SOLAR_SYSTEM[lower], {"name": {"moon": "Moon", "sun": "Sun", "planet": "Planets"}[SOLAR_SYSTEM[lower]],
                                                         "kind": SOLAR_SYSTEM[lower], "folder": e.path, "stacks": 0, "newest_stack": None,
                                                         "subs": None, "videos": []})
            t["videos"] += [{"path": v.path, "name": v.name, "bytes": v.stat().st_size,
                             "taken": datetime.fromtimestamp(v.stat().st_mtime).isoformat(timespec="seconds")} for v in videos]
            continue
        if lower.endswith("_sub"):
            continue
        key = name
        kind = "mosaic" if lower.endswith("_mosaic") else "deep-sky"
        stacks = sorted((_stack_info(f) for f in _files(Path(e.path), FITS)), key=lambda s: s["taken"], reverse=True)
        sub = dirs.get(f"{name}_sub")
        subs = None
        if sub is not None:
            n = len(_files(Path(sub.path), FITS))
            subs = {"path": sub.path, "frames": n} if n else None
        if not stacks and not subs:
            continue
        targets[key] = {"name": name[: -len("_mosaic")] + " (mosaic)" if kind == "mosaic" else name, "kind": kind, "folder": e.path,
                        "stacks": len(stacks), "newest_stack": stacks[0] if stacks else None, "subs": subs, "videos": []}
    for t in targets.values():
        t["videos"] = sorted(t["videos"], key=lambda v: v["taken"], reverse=True)[:50]
    items = sorted(targets.values(), key=lambda t: ((t["newest_stack"] or {}).get("taken") or (t["videos"][0]["taken"] if t["videos"] else "")), reverse=True)
    return {"path": str(root), "targets": items}
