"""Read-only folder browsing for the Stack frames dialog: one level at a time, directory names and FITS counts only.

Nothing is opened except directory listings; files are never read, created or changed."""
from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Any

FITS_SUFFIXES = (".fit", ".fits", ".fts")
MAX_DIRS = 400
MAX_COUNT = 9999
RECENT_SETTING = "stack.recent_folders"
MAX_RECENT = 8


def _fits_count(path: str) -> int:
    n = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.lower().endswith(FITS_SUFFIXES) and e.is_file(follow_symlinks=False):
                    n += 1
                    if n >= MAX_COUNT:
                        break
    except OSError:
        return 0
    return n


def _entry(path: str, name: str | None = None) -> dict[str, Any]:
    p = Path(path)
    label = name or p.name or str(p)
    return {"name": label, "path": str(p), "fits": _fits_count(str(p)), "is_sub": p.name.lower().endswith("_sub")}


def roots() -> list[dict[str, Any]]:
    out = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.isdir(drive):
                out.append({"name": drive, "path": drive, "fits": 0, "is_sub": False})
    else:
        out.append({"name": "/", "path": "/", "fits": 0, "is_sub": False})
    home = Path.home()
    for sub in ("Pictures", "Desktop", "Downloads", "Documents"):
        d = home / sub
        if d.is_dir():
            out.append({"name": f"{sub} ({home.name})", "path": str(d), "fits": 0, "is_sub": False})
    return out


def browse(path: str | None, recent: list[str]) -> dict[str, Any]:
    recent_ok = [_entry(r) for r in recent if r and os.path.isdir(r)]
    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in recent_ok:  # sibling *_sub folders of recently stacked ones (for example other targets in a Seestar MyWorks folder)
        parent = Path(r["path"]).parent
        try:
            with os.scandir(parent) as it:
                for e in sorted(it, key=lambda e: e.name.lower()):
                    if e.is_dir() and e.name.lower().endswith("_sub") and e.path not in seen and len(suggestions) < 30:
                        seen.add(e.path)
                        suggestions.append(_entry(e.path))
        except OSError:
            continue
    if not path:
        return {"path": None, "parent": None, "fits": 0, "folders": roots(), "recent": recent_ok, "suggestions": suggestions}
    p = Path(path.strip().strip('"'))
    if not p.is_absolute() or not p.is_dir():
        return {"path": str(p), "parent": None, "fits": 0, "folders": [], "recent": recent_ok, "suggestions": suggestions,
                "error": "That folder does not exist or is not reachable."}
    folders = []
    try:
        with os.scandir(p) as it:
            for e in sorted(it, key=lambda e: e.name.lower()):
                if len(folders) >= MAX_DIRS:
                    break
                if e.name.startswith((".", "$")):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        folders.append(_entry(e.path, e.name))
                except OSError:
                    continue
    except OSError:
        return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "fits": 0, "folders": [], "recent": recent_ok,
                "suggestions": suggestions, "error": "This folder cannot be read."}
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "fits": _fits_count(str(p)), "folders": folders,
            "recent": recent_ok, "suggestions": suggestions}


def remember(recent: list[str], folder: str) -> list[str]:
    folder = str(Path(folder.strip().strip('"')))
    return ([folder] + [r for r in recent if r != folder])[:MAX_RECENT]
