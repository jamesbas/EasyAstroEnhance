"""Optional result retention: keep only the newest N results per image (setting ``results.keep_per_image``, 0 = keep all)."""
from __future__ import annotations

import shutil
from typing import Any

from ..config import Config
from ..db import Database

SETTING = "results.keep_per_image"
MAX_KEEP = 50


def keep_per_image(db: Database) -> int:
    try:
        return max(0, min(MAX_KEEP, int(db.get_setting(SETTING, 0) or 0)))
    except (TypeError, ValueError):
        return 0


def prune_runs(cfg: Config, db: Database, asset_id: str) -> list[str]:
    """Remove the oldest results of one image beyond the configured count. Never removes the result the image's latest
    job item uses (an older, reused result can be the one on screen), and does nothing while a ZIP is being built."""
    keep = keep_per_image(db)
    if keep <= 0 or db.one("SELECT 1 AS x FROM exports WHERE state='building'"):
        return []
    runs: list[dict[str, Any]] = db.all("SELECT id FROM runs WHERE asset_id=? ORDER BY created_at DESC", (asset_id,))
    item = db.one(
        "SELECT i.run_id FROM job_items i JOIN jobs j ON j.id=i.job_id WHERE i.asset_id=? ORDER BY j.created_at DESC, i.position DESC LIMIT 1",
        (asset_id,),
    )
    pinned = {item["run_id"]} if item and item.get("run_id") else set()
    removed = []
    for r in runs[keep:]:
        if r["id"] in pinned:
            continue
        db.execute("DELETE FROM runs WHERE id=?", (r["id"],))
        db.execute("UPDATE job_items SET run_id=NULL WHERE run_id=?", (r["id"],))
        shutil.rmtree(cfg.runs_dir / r["id"], ignore_errors=True)
        removed.append(r["id"])
    return removed
