"""Batch ZIP export (built in a background thread; only allow-listed artifacts of completed runs)."""
from __future__ import annotations

import json
import threading
import zipfile
from pathlib import Path
from typing import Any

from ..config import Config
from ..db import Database, new_id, now

ALLOWED_KINDS = {"png", "tiff", "jpeg", "comparison", "report", "summary", "fits", "linear-tiff"}
DEFAULT_KINDS = ("png", "report", "summary")
_STORED = {".png", ".jpg", ".tif"}  # already compressed


def start_batch(cfg: Config, db: Database, run_ids: list[str], include: list[str]) -> str:
    export_id = new_id("zip_")
    db.insert("exports", {"id": export_id, "state": "building", "created_at": now(), "path": None, "detail": {"done": 0, "total": len(run_ids)}})
    threading.Thread(target=_build, args=(cfg, db, export_id, run_ids, include), daemon=True).start()
    return export_id


def _build(cfg: Config, db: Database, export_id: str, run_ids: list[str], include: list[str]) -> None:
    kinds = set(DEFAULT_KINDS) | (set(include) & ALLOWED_KINDS)
    out = cfg.exports_dir / f"{export_id}.zip"
    partial = out.with_suffix(".zip.partial")
    summary: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(partial, "w") as zf:
            for i, rid in enumerate(run_ids, start=1):
                run = db.one("SELECT * FROM runs WHERE id=?", (rid,))
                if not run:
                    continue
                asset = db.one("SELECT filename FROM assets WHERE id=?", (run["asset_id"],))
                folder = (run["summary"] or {}).get("run_name") or rid
                run_dir = cfg.runs_dir / rid
                files = []
                for e in run["exports"] or []:
                    if e["kind"] not in kinds:
                        continue
                    src = run_dir / e["filename"]
                    if not src.exists():
                        continue
                    ext = Path(e["filename"]).suffix.lower()
                    zf.write(src, f"{folder}/{e['filename']}", compress_type=zipfile.ZIP_STORED if ext in _STORED else zipfile.ZIP_DEFLATED)
                    files.append(e["filename"])
                summary.append({"run_id": rid, "folder": folder, "source": asset["filename"] if asset else None, "state": run["state"], "result": (run["summary"] or {}).get("text"), "files": files})
                db.update("exports", export_id, {"detail": {"done": i, "total": len(run_ids)}})
            lines = ["EasyAstroEnhance batch summary", f"Created: {now()}", ""]
            for s in summary:
                lines += [f"{s['folder']}/  ({s['source']})", f"  {s['state']}: {s['result']}", f"  files: {', '.join(s['files'])}", ""]
            zf.writestr("batch-summary.txt", "\n".join(lines))
            zf.writestr("batch-summary.json", json.dumps(summary, indent=2))
        partial.replace(out)
        db.update("exports", export_id, {"state": "ready", "path": str(out), "detail": {"done": len(run_ids), "total": len(run_ids), "bytes": out.stat().st_size}})
    except Exception as exc:
        partial.unlink(missing_ok=True)
        db.update("exports", export_id, {"state": "failed", "detail": {"error": {"code": "ZIP_FAILED", "message": "The ZIP file could not be created.", "detail": str(exc)}}})
