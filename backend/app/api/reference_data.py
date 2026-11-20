"""Optional reference data (star and deep-sky object catalogs): status, verified downloads and removal."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..processing.catalogs import registry
from .common import ApiError

router = APIRouter(prefix="/reference-data", tags=["reference-data"])


def _mgr(request: Request):
    return request.app.state.reference_data


def _ids(key: str) -> list[str]:
    if key in registry.DATA:
        return [key]
    if key in registry.GROUPS:
        return registry.GROUPS[key]
    raise ApiError(404, "REFERENCE_NOT_FOUND", "That reference catalog is not known to this version.")


@router.get("")
def overview(request: Request) -> dict[str, Any]:
    return _mgr(request).overview()


@router.post("/{key}/download", status_code=202)
def download(request: Request, key: str) -> dict[str, Any]:
    """Accepts an item id or a group (stars, objects)."""
    mgr = _mgr(request)
    for i in _ids(key):
        if not registry.DATA[i].sha256:
            raise ApiError(409, "REFERENCE_UNAVAILABLE", "This catalog is not published for this version yet.")
        mgr.start(i)
    return mgr.overview()


@router.post("/{key}/cancel")
def cancel(request: Request, key: str) -> dict[str, Any]:
    mgr = _mgr(request)
    for i in _ids(key):
        mgr.cancel(i)
    return mgr.overview()


@router.delete("/{key}")
def delete(request: Request, key: str) -> dict[str, Any]:
    mgr = _mgr(request)
    for i in _ids(key):
        mgr.delete(i)
    return mgr.overview()
