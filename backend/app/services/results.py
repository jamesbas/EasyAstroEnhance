"""Results of one image: which one is current, going back to an earlier one, and deleting one.

The current result is the one the image card, viewer, downloads and Download all use. It is the newest finished result
unless the user went back to an earlier one, or an identical earlier result was reused. Results are never changed:
going back only moves the pointer, and deleting removes the result's own files (never the original).
"""
from __future__ import annotations

import shutil
from typing import Any

from ..config import Config
from ..db import Database


def current_run(db: Database, asset_id: str) -> dict[str, Any] | None:
    a = db.one("SELECT current_run_id FROM assets WHERE id=?", (asset_id,))
    if a and a.get("current_run_id"):
        run = db.one("SELECT * FROM runs WHERE id=? AND asset_id=?", (a["current_run_id"], asset_id))
        if run:
            return run
    return db.one("SELECT * FROM runs WHERE asset_id=? ORDER BY created_at DESC LIMIT 1", (asset_id,))


def set_current(db: Database, asset_id: str, run_id: str | None) -> None:
    db.execute("UPDATE assets SET current_run_id=? WHERE id=?", (run_id, asset_id))


def next_serial(db: Database, asset_id: str) -> int:
    """The next run number for the image. Numbers are never reused after results are deleted, so "Run 3" always means
    the same result (the image remembers the highest number it gave out)."""
    row = db.one("SELECT MAX(serial) AS n FROM runs WHERE asset_id=?", (asset_id,))
    a = db.one("SELECT last_serial FROM assets WHERE id=?", (asset_id,))
    serial = max(int((row or {}).get("n") or 0), int((a or {}).get("last_serial") or 0)) + 1
    db.execute("UPDATE assets SET last_serial=? WHERE id=?", (serial, asset_id))
    return serial


def delete_run(cfg: Config, db: Database, run: dict[str, Any]) -> None:
    """Remove one result. If it was the current one, the newest remaining result becomes current."""
    asset = db.one("SELECT current_run_id FROM assets WHERE id=?", (run["asset_id"],))
    db.execute("DELETE FROM runs WHERE id=?", (run["id"],))
    db.execute("UPDATE job_items SET run_id=NULL WHERE run_id=?", (run["id"],))
    if asset and asset.get("current_run_id") == run["id"]:
        set_current(db, run["asset_id"], None)  # falls back to the newest remaining result
    shutil.rmtree(cfg.runs_dir / run["id"], ignore_errors=True)
