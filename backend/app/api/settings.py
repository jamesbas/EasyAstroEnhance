from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..models.api import ComputePatch, SettingsPatch
from .common import cfg_of, coord_of, db_of, run_worker_task, settings_snapshot

router = APIRouter(tags=["settings"])

# Execution policy per the specification (GPU eligibility depends on measured parity tests).
STAGE_POLICY = [
    {"stage": "Gaussian filtering, denoising residuals, chroma smoothing", "gpu_eligible": True},
    {"stage": "Tone curves, saturation, mask blending, gradient evaluation", "gpu_eligible": True},
    {"stage": "Local-contrast filtering and star-mask application", "gpu_eligible": True},
    {"stage": "FITS/TIFF/JPEG decode, headers, color profiles, encoding", "gpu_eligible": False, "backend": "CPU/disk"},
    {"stage": "Sky-sample statistics, robust planar fit, star detection (connected components), job coordination", "gpu_eligible": False, "backend": "CPU"},
]


def _compute_view(request: Request) -> dict[str, Any]:
    db, coord, cfg = db_of(request), coord_of(request), cfg_of(request)
    snap = settings_snapshot(db, cfg)
    probe = coord.probe_info
    gpu_ok = bool(probe and probe.get("ok"))
    pref = snap["device"]
    resolved = "Processing: GPU + CPU" if (gpu_ok and pref in ("auto", "gpu")) else "Processing: CPU"
    note = None
    if probe is None:
        note = "GPU not checked yet. Use Check GPU setup."
    elif not gpu_ok:
        note = probe.get("note")
    elif pref == "auto":
        note = f"Auto uses the GPU for eligible stages on images of {cfg.gpu_threshold_pixels / 1e6:.0f} MP or more; smaller images run on CPU."
    return {
        "preference": pref, "gpu_memory_fraction": snap["gpu_memory_fraction"], "ram_fraction": snap["ram_fraction"],
        "probe": probe, "gpu_usable": gpu_ok, "resolved_label": resolved, "note": note, "stage_policy": STAGE_POLICY,
        "devices": [{"name": probe.get("device_name"), "compute_capability": probe.get("compute_capability"), "free_memory_bytes": probe.get("free_memory_bytes"), "total_memory_bytes": probe.get("total_memory_bytes")}] if gpu_ok else [],
        "gpu_threshold_pixels": cfg.gpu_threshold_pixels,
    }


@router.get("/compute")
async def get_compute(request: Request) -> dict[str, Any]:
    return _compute_view(request)


@router.post("/compute/probe")
async def probe_compute(request: Request) -> dict[str, Any]:
    await run_worker_task(request, "probe", {}, timeout=120)
    return _compute_view(request)


@router.patch("/settings/compute")
async def patch_compute(request: Request, body: ComputePatch) -> dict[str, Any]:
    db = db_of(request)
    for k, v in body.model_dump(exclude_none=True).items():
        db.set_setting(f"compute.{k}", v)
    return _compute_view(request)


@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    db, cfg = db_of(request), cfg_of(request)
    snap = settings_snapshot(db, cfg)
    return {
        "compute": _compute_view(request), "strip_location": snap["strip_location"],
        "limits": {"max_files": cfg.max_files, "max_file_mib": cfg.max_file_bytes // (1024 * 1024), "max_megapixels": cfg.max_pixels // 1_000_000},
        "data_dir": str(cfg.data_dir),
    }


@router.patch("/settings")
async def patch_settings(request: Request, body: SettingsPatch) -> dict[str, Any]:
    if body.strip_location is not None:
        db_of(request).set_setting("strip_location", body.strip_location)
    return await get_settings(request)
