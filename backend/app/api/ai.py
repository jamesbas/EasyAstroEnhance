"""Optional AI tools: model status, downloads (fixed, verified files only) and removal."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..processing.ai import registry
from .common import ApiError

router = APIRouter(prefix="/ai", tags=["ai"])


def _mgr(request: Request):
    return request.app.state.ai_models


def _spec_ids(key: str) -> list[str]:
    if key in registry.MODELS:
        return [key]
    if key in registry.TOOL_MODELS:
        return registry.TOOL_MODELS[key]
    raise ApiError(404, "MODEL_NOT_FOUND", "That AI model is not known to this version.")


@router.get("/models")
async def list_models(request: Request) -> dict[str, Any]:
    return _mgr(request).overview()


@router.post("/models/{key}/download", status_code=202)
async def download(request: Request, key: str) -> dict[str, Any]:
    """Accepts a model id or a tool name (background, denoise, stars) to fetch every model that tool needs."""
    mgr = _mgr(request)
    for mid in _spec_ids(key):
        mgr.start(mid)
    return mgr.overview()


@router.post("/models/{key}/cancel")
async def cancel(request: Request, key: str) -> dict[str, Any]:
    mgr = _mgr(request)
    for mid in _spec_ids(key):
        mgr.cancel(mid)
    return mgr.overview()


@router.delete("/models/{key}")
async def delete(request: Request, key: str) -> dict[str, Any]:
    mgr = _mgr(request)
    for mid in _spec_ids(key):
        mgr.delete(mid)
    return mgr.overview()
