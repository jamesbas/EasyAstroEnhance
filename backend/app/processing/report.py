"""Dependency/engine identity recorded in every report and cache key."""
from __future__ import annotations

import platform
import sys
from functools import lru_cache
from importlib import metadata
from typing import Any

from .recipe import PIPELINE_VERSION, RECIPE_SCHEMA_VERSION

_PACKAGES = ("numpy", "scipy", "astropy", "tifffile", "imagecodecs", "pillow", "pydantic", "fastapi", "cupy-cuda13x", "onnxruntime-directml", "onnxruntime")


@lru_cache(maxsize=1)
def dependency_versions() -> dict[str, Any]:
    versions: dict[str, str] = {}
    for name in _PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": versions,
        "engine_version": PIPELINE_VERSION,
        "recipe_schema_version": RECIPE_SCHEMA_VERSION,
    }
