"""Runtime configuration (environment-driven; no secrets, no cloud settings)."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


def _default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return Path(base) / "EasyAstroEnhance"


@dataclass(frozen=True)
class Config:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    max_files: int = 20
    max_file_bytes: int = 512 * 1024 * 1024
    max_pixels: int = 100_000_000
    frontend_dist: Path | None = None
    dev_origins: tuple[str, ...] = ()
    ram_fraction: float = 0.6
    gpu_memory_fraction: float = 0.7
    gpu_threshold_pixels: int = 2_000_000
    min_free_bytes: int = 256 * 1024 * 1024
    cpu_only: bool = False
    cpu_threads: int = 0  # 0 = automatic (up to 8 threads for CPU pixel work and analysis)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def ai_models_dir(self) -> Path:
        return self.data_dir / "ai-models"

    @property
    def reference_data_dir(self) -> Path:
        return self.data_dir / "reference-data"

    @property
    def color_catalog_dir(self) -> Path:
        return self.data_dir / "color-catalogs"

    @property
    def allowed_hosts(self) -> set[str]:
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        hosts.update(o.split("://", 1)[-1] for o in self.dev_origins)
        return hosts

    @property
    def allowed_origins(self) -> set[str]:
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}", *self.dev_origins}


def load_config(**overrides) -> Config:
    env = os.environ
    repo_root = Path(__file__).resolve().parents[2]
    dist = repo_root / "frontend" / "dist"
    dev = tuple(o for o in env.get("EASYASTRO_DEV_ORIGINS", "").split(",") if o)
    cfg = Config(
        data_dir=Path(env.get("EASYASTRO_DATA_DIR") or _default_data_dir()),
        port=int(env.get("EASYASTRO_PORT", 8765)),
        max_files=int(env.get("EASYASTRO_MAX_FILES", 20)),
        max_file_bytes=int(env.get("EASYASTRO_MAX_FILE_MB", 512)) * 1024 * 1024,
        max_pixels=int(float(env.get("EASYASTRO_MAX_MEGAPIXELS", 100)) * 1_000_000),
        frontend_dist=dist if dist.exists() else None,
        dev_origins=dev,
        gpu_threshold_pixels=int(env.get("EASYASTRO_GPU_THRESHOLD_PIXELS", 2_000_000)),
        cpu_only=env.get("EASYASTRO_CPU_ONLY") == "1",
        cpu_threads=max(0, int(env.get("EASYASTRO_CPU_THREADS", 0) or 0)),
    )
    return replace(cfg, **overrides) if overrides else cfg


def ensure_dirs(cfg: Config) -> None:
    for d in (cfg.data_dir, cfg.assets_dir, cfg.runs_dir, cfg.exports_dir, cfg.tmp_dir, cfg.ai_models_dir, cfg.color_catalog_dir, cfg.reference_data_dir):
        d.mkdir(parents=True, exist_ok=True)
