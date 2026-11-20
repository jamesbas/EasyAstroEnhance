"""Downloads of the pinned reference data (star and deep-sky object catalogs): user-initiated, verified like the AI
models (see ai_models.ModelManager)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..processing.catalogs import registry
from .ai_models import ModelManager


class ReferenceDataManager(ModelManager):
    def __init__(self, data_dir: Path, min_free_bytes: int = 256 * 1024 * 1024) -> None:
        super().__init__(data_dir, min_free_bytes, graxpert_root=Path("."), specs=registry.DATA)

    def overview(self) -> dict[str, Any]:
        items = [self.status(s) for s in registry.DATA.values()]
        by_id = {i["id"]: i for i in items}
        groups = {}
        for g, ids in registry.GROUPS.items():
            states = [by_id[i]["state"] for i in ids]
            groups[g] = {
                "items": ids, "ready": all(s == "installed" for s in states),
                "state": "installed" if all(s == "installed" for s in states) else "downloading" if "downloading" in states
                else "error" if "error" in states else "missing",
                "download_bytes": sum(registry.DATA[i].size for i in ids if by_id[i]["state"] != "installed"),
                "available": all(registry.DATA[i].sha256 for i in ids),
            }
        return {"items": items, "groups": groups, "dir": str(self.dir),
                "note": "Optional numeric catalogs, used only to check or work out where the image points on the sky, to "
                        "fit star colours and to label objects on a sharing copy. They never change how an object looks."}

    def start(self, model_id: str) -> dict[str, Any]:
        if not registry.DATA[model_id].sha256:
            raise KeyError(model_id)
        return super().start(model_id)
