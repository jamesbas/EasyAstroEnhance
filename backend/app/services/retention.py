"""Optional result retention: keep only the newest N results per image (setting ``results.keep_per_image``, 0 = keep all)."""
from __future__ import annotations

from typing import Any

from ..config import Config
from ..db import Database
from .results import delete_run

SETTING = "results.keep_per_image"
MAX_KEEP = 50


def keep_per_image(db: Database) -> int:
    try:
        return max(0, min(MAX_KEEP, int(db.get_setting(SETTING, 0) or 0)))
    except (TypeError, ValueError):
        return 0


def prune_runs(cfg: Config, db: Database, asset_id: str) -> list[str]:
    """Remove the oldest results of one image beyond the configured count. Never removes the image's current result or
    the one its latest job item uses, and does nothing while a ZIP is being built."""
    keep = keep_per_image(db)
    if keep <= 0 or db.one("SELECT 1 AS x FROM exports WHERE state='building'"):
        return []
    runs: list[dict[str, Any]] = db.all("SELECT id, asset_id FROM runs WHERE asset_id=? ORDER BY created_at DESC", (asset_id,))
    item = db.one(
        "SELECT i.run_id FROM job_items i JOIN jobs j ON j.id=i.job_id WHERE i.asset_id=? ORDER BY j.created_at DESC, i.position DESC LIMIT 1",
        (asset_id,),
    )
    pinned = {item["run_id"]} if item and item.get("run_id") else set()
    cur = db.one("SELECT current_run_id FROM assets WHERE id=?", (asset_id,))
    if cur and cur.get("current_run_id"):
        pinned.add(cur["current_run_id"])
    removed = []
    for r in runs[keep:]:
        if r["id"] in pinned:
            continue
        delete_run(cfg, db, r)
        removed.append(r["id"])
    return removed
