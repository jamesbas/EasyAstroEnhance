from __future__ import annotations

import numpy as np
from scipy import ndimage

from .base import GAUSSIAN_TRUNCATE, Backend, disk_footprint, sigma_tuple


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

    def erode_disk(self, a, radius: int):
        if radius <= 0:
            return a
        return ndimage.grey_erosion(a, footprint=disk_footprint(radius, a.ndim), mode="nearest")

    def convolve2d(self, a, kernel: np.ndarray):
        """2-D convolution of a 2-D array with a small odd kernel (reflect padding, FFT)."""
        from scipy.signal import fftconvolve

        r = kernel.shape[0] // 2
        return fftconvolve(np.pad(a, r, mode="reflect"), kernel, mode="valid").astype(a.dtype, copy=False)
