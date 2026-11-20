"""Optional CuPy/CUDA backend. CuPy is imported lazily and only inside the worker process."""
from __future__ import annotations

import numpy as np

from .base import (
    GAUSSIAN_TRUNCATE,
    Backend,
    BackendUnavailable,
    RecoverableBackendError,
    disk_footprint,
    sigma_tuple,
)


class CupyBackend(Backend):
    name = "gpu"
    device_label = "NVIDIA GPU"

    def __init__(self, memory_limit_bytes: int | None = None) -> None:
        super().__init__()
        try:
            import cupy as cp
            from cupyx.scipy import ndimage as cndimage
        except Exception as exc:  # ImportError or a broken CUDA runtime
            raise BackendUnavailable(f"CuPy could not be imported: {exc}") from exc
        self.cp = cp
        self.xp = cp
        self._nd = cndimage
        try:
            self.device_label = cp.cuda.runtime.getDeviceProperties(0)["name"].decode()
        except Exception:
            pass
        if memory_limit_bytes:
            # Bound the allocator pool so idle buffers cannot exceed the VRAM budget.
            cp.get_default_memory_pool().set_limit(size=int(memory_limit_bytes))

    def asarray(self, a: np.ndarray):
        t = self.timed()
        with t:
            out = self.cp.asarray(np.ascontiguousarray(a))
        self.transfers.h2d_bytes += int(a.nbytes)
        self.transfers.h2d_count += 1
        self.transfers.seconds += t.seconds
        return out

    def asnumpy(self, a) -> np.ndarray:
        if isinstance(a, np.ndarray):
            return a
        t = self.timed()
        with t:
            out = self.cp.asnumpy(a)  # synchronizes the null stream
        self.transfers.d2h_bytes += int(out.nbytes)
        self.transfers.d2h_count += 1
        self.transfers.seconds += t.seconds
        return out

    def gaussian(self, a, sigma: float):
        if sigma <= 0:
            return a
        return self._nd.gaussian_filter(
            a, sigma_tuple(a.ndim, sigma), mode="reflect", truncate=GAUSSIAN_TRUNCATE
        )

    def erode_disk(self, a, radius: int):
        if radius <= 0:
            return a
        return self._nd.grey_erosion(a, footprint=self.cp.asarray(disk_footprint(radius, a.ndim)), mode="nearest")

    def convolve2d(self, a, kernel: np.ndarray):
        from cupyx.scipy.signal import fftconvolve

        r = kernel.shape[0] // 2
        return fftconvolve(self.cp.pad(a, r, mode="reflect"), self.cp.asarray(kernel, dtype=a.dtype), mode="valid").astype(a.dtype, copy=False)

    def synchronize(self) -> None:
        self.cp.cuda.Stream.null.synchronize()

    def release(self) -> None:
        try:
            self.cp.get_default_memory_pool().free_all_blocks()
            self.cp.get_default_pinned_memory_pool().free_all_blocks()
        except Exception:
            pass

    def free_memory(self) -> int | None:
        """Currently free VRAM (not the nominal total), used for the budget."""
        try:
            return int(self.cp.cuda.runtime.memGetInfo()[0])
        except Exception:
            return None

    def classify_error(self, exc: BaseException) -> RecoverableBackendError | None:
        cp = self.cp
        if isinstance(exc, cp.cuda.memory.OutOfMemoryError):
            return RecoverableBackendError("oom", "GPU out of memory")
        if isinstance(exc, (cp.cuda.runtime.CUDARuntimeError, cp.cuda.driver.CUDADriverError)):
            text = str(exc)
            if "OutOfMemory" in text or "out of memory" in text.lower():
                return RecoverableBackendError("oom", "GPU out of memory")
            return RecoverableBackendError("device", f"CUDA runtime failure: {text}")
        return None
