from __future__ import annotations

import numpy as np
from scipy import ndimage

from .base import GAUSSIAN_TRUNCATE, Backend, sigma_tuple


class NumpyBackend(Backend):
    name = "cpu"
    xp = np
    device_label = "CPU"

    def asarray(self, a: np.ndarray):
        return np.ascontiguousarray(a)

    def asnumpy(self, a) -> np.ndarray:
        return np.asarray(a)

    def gaussian(self, a, sigma: float):
        if sigma <= 0:
            return a
        return ndimage.gaussian_filter(
            a, sigma_tuple(a.ndim, sigma), mode="reflect", truncate=GAUSSIAN_TRUNCATE
        )
