"""Backend selection and the CUDA probe (device discovery is never sufficient on its own)."""
from __future__ import annotations

from typing import Any

import numpy as np

from .base import Backend, BackendUnavailable, RecoverableBackendError
from .numpy_backend import NumpyBackend

__all__ = [
    "Backend",
    "BackendUnavailable",
    "RecoverableBackendError",
    "NumpyBackend",
    "get_backend",
    "probe_cuda",
]


def get_backend(name: str, memory_limit_bytes: int | None = None) -> Backend:
    if name == "cpu":
        return NumpyBackend()
    if name == "gpu":
        from .cupy_backend import CupyBackend

        return CupyBackend(memory_limit_bytes)
    raise ValueError(f"unknown backend {name!r}")


def probe_cuda() -> dict[str, Any]:
    """Probe the CUDA runtime: import, driver/runtime versions, device, allocation, filter parity.

    Must run inside the spawned worker (never in a parent that may fork).
    """
    info: dict[str, Any] = {"ok": False, "status": "unavailable", "note": None}
    try:
        import cupy as cp
        from cupyx.scipy import ndimage as cnd
    except Exception as exc:
        info["note"] = (
            "CuPy is not installed or could not load its CUDA libraries "
            f"({type(exc).__name__}). CPU processing is fully functional; run scripts\\setup-gpu.ps1 "
            "to add optional NVIDIA acceleration."
        )
        return info
    try:
        info["cupy_version"] = cp.__version__
        info["cuda_runtime_version"] = int(cp.cuda.runtime.runtimeGetVersion())
        info["cuda_driver_version"] = int(cp.cuda.runtime.driverGetVersion())
        count = int(cp.cuda.runtime.getDeviceCount())
        info["device_count"] = count
        if count < 1:
            info["note"] = "No CUDA device was found."
            return info
        props = cp.cuda.runtime.getDeviceProperties(0)
        info["device_name"] = props["name"].decode()
        info["compute_capability"] = f"{props['major']}.{props['minor']}"
        free, total = cp.cuda.runtime.memGetInfo()
        info["free_memory_bytes"] = int(free)
        info["total_memory_bytes"] = int(total)

        # Execution check: allocation + filter + synchronized numeric comparison with SciPy.
        from scipy import ndimage

        rng = np.random.default_rng(1234)
        host = rng.random((96, 80, 3), dtype=np.float32)
        dev = cp.asarray(host)
        out = cnd.gaussian_filter(dev, (1.5, 1.5, 0.0), mode="reflect", truncate=4.0)
        cp.cuda.Stream.null.synchronize()
        got = cp.asnumpy(out)
        ref = ndimage.gaussian_filter(host, (1.5, 1.5, 0.0), mode="reflect", truncate=4.0)
        err = float(np.max(np.abs(got - ref)))
        info["probe_max_abs_error"] = err
        if not np.isfinite(err) or err > 1e-5:
            info["status"] = "failed"
            info["note"] = f"GPU filter result disagreed with the CPU reference (max error {err:.2e})."
            return info
        info["ok"] = True
        info["status"] = "ready"
        return info
    except Exception as exc:
        info["status"] = "failed"
        info["note"] = f"GPU probe failed: {type(exc).__name__}: {exc}"
        return info
