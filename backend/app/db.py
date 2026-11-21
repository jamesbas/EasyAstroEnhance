"""SQLite persistence. All writes happen in the coordinator process (the worker never opens the database)."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, filename TEXT NOT NULL, format TEXT, size_bytes INTEGER,
  sha256 TEXT, status TEXT NOT NULL, error TEXT, inspection TEXT, interpretation TEXT NOT NULL DEFAULT '{}',
  regions TEXT NOT NULL DEFAULT '[]', background TEXT, prepared TEXT, original_name TEXT, current_run_id TEXT,
  last_serial INTEGER
);
CREATE TABLE IF NOT EXISTS presets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, recipe TEXT NOT NULL, schema_version INTEGER NOT NULL,
  engine_version TEXT NOT NULL, builtin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, request_key TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  state TEXT NOT NULL, recipe TEXT NOT NULL, preset_snapshot TEXT, settings_snapshot TEXT, force INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS job_items (
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, asset_id TEXT NOT NULL, position INTEGER NOT NULL,
  state TEXT NOT NULL, stage TEXT, notes TEXT, run_id TEXT, error TEXT, backend_label TEXT,
  started_at TEXT, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_job ON job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_items_asset ON job_items(asset_id);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, job_id TEXT, created_at TEXT NOT NULL, state TEXT NOT NULL,
  serial INTEGER NOT NULL, cache_key TEXT, recipe TEXT NOT NULL, recipe_hash TEXT, summary TEXT, exports TEXT,
  report_path TEXT, needs_review INTEGER DEFAULT 0, backend_label TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_asset ON runs(asset_id);
CREATE INDEX IF NOT EXISTS idx_runs_cache ON runs(cache_key);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exports (
  id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, path TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS stacks (
  id TEXT PRIMARY KEY, request_key TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, state TEXT NOT NULL,
  name TEXT NOT NULL, request TEXT NOT NULL, stage TEXT, progress REAL, report TEXT, error TEXT, asset_id TEXT,
  auto_enhance INTEGER NOT NULL DEFAULT 0, recipe TEXT, preset_snapshot TEXT, settings_snapshot TEXT, job_id TEXT,
  started_at TEXT, finished_at TEXT
);
"""

JSON_COLUMNS = {
    "inspection", "interpretation", "regions", "background", "prepared", "error", "recipe", "preset_snapshot",
    "settings_snapshot", "notes", "summary", "exports", "detail", "value", "j_recipe", "j_preset", "j_settings",
    "request", "report",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Additive column migrations for databases created by earlier versions."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(assets)").fetchall()}
        if "current_run_id" not in cols:  # the result shown, downloaded and zipped for the image (None: the newest)
            self._conn.execute("ALTER TABLE assets ADD COLUMN current_run_id TEXT")
        if "last_serial" not in cols:  # highest run number given out for the image (numbers are never reused)
            self._conn.execute("ALTER TABLE assets ADD COLUMN last_serial INTEGER")

    @staticmethod
    def _dump(v: Any) -> Any:
        return json.dumps(v) if isinstance(v, (dict, list)) else v

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out: dict[str, Any] = {}
        for k in row.keys():
            v = row[k]
            if k in JSON_COLUMNS and isinstance(v, str):
                try:
                    v = json.loads(v)
                except json.JSONDecodeError:
                    pass
            out[k] = v
        return out

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, tuple(self._dump(p) for p in params))

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            return self._row(self._conn.execute(sql, tuple(self._dump(p) for p in params)).fetchone())

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, tuple(self._dump(p) for p in params)).fetchall()
        return [self._row(r) for r in rows]  # type: ignore[misc]

    def insert(self, table: str, values: dict[str, Any]) -> None:
        cols = ",".join(values)
        marks = ",".join("?" for _ in values)
        self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))

    def update(self, table: str, row_id: str, values: dict[str, Any], key: str = "id") -> None:
        sets = ",".join(f"{k}=?" for k in values)
        self.execute(f"UPDATE {table} SET {sets} WHERE {key}=?", [*values.values(), row_id])

    def transaction(self):
        return _Tx(self)

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return default if row is None else row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class _Tx:
    def __init__(self, db: Database) -> None:
        self.db = db

    def __enter__(self):
        self.db._lock.acquire()
        self.db._conn.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db._conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()
        return False
