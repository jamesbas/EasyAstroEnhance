"""Array backend interface.

Stage code is written once against ``Backend.xp`` (NumPy- or CuPy-compatible) and
``Backend.gaussian`` so CPU and GPU share identical algorithm definitions, dtypes,
boundary mode (reflect) and kernel truncation (4 sigma).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

GAUSSIAN_TRUNCATE = 4.0


class BackendUnavailable(RuntimeError):
    """The requested backend cannot be used (missing package, no device, failed probe)."""


class RecoverableBackendError(RuntimeError):
    """A classified, recoverable execution failure (for example GPU out-of-memory)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # "oom" | "device"


def kernel_radius(sigma: float, truncate: float = GAUSSIAN_TRUNCATE) -> int:
    return int(truncate * float(sigma) + 0.5)


@dataclass
class TransferStats:
    h2d_bytes: int = 0
    d2h_bytes: int = 0
    h2d_count: int = 0
    d2h_count: int = 0
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "host_to_device_bytes": self.h2d_bytes,
            "device_to_host_bytes": self.d2h_bytes,
            "host_to_device_count": self.h2d_count,
            "device_to_host_count": self.d2h_count,
            "seconds": round(self.seconds, 4),
        }


class Backend:
    name: str = "cpu"
    xp: Any = np
    device_label: str = "CPU"

    def __init__(self) -> None:
        self.transfers = TransferStats()

    def asarray(self, a: np.ndarray):
        raise NotImplementedError

    def asnumpy(self, a) -> np.ndarray:
        raise NotImplementedError

    def gaussian(self, a, sigma: float):
        """Gaussian filter over the two spatial axes (axis 2, if present, is not filtered)."""
        raise NotImplementedError

    def synchronize(self) -> None:
        pass

    def release(self) -> None:
        pass

    def classify_error(self, exc: BaseException) -> RecoverableBackendError | None:
        return None

    def timed(self):
        return _Timer()


class _Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.t0
        return False


def sigma_tuple(a_ndim: int, sigma: float) -> tuple[float, ...]:
    return (sigma, sigma) if a_ndim == 2 else (sigma, sigma, 0.0)


def disk_footprint(radius: int, ndim: int) -> np.ndarray:
    """A flat disk over the two spatial axes (channels are filtered independently)."""
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    fp = (yy**2 + xx**2) <= radius * radius + 0.5
    return fp if ndim == 2 else fp[..., None]
