"""Order-preserving thread helpers for the CPU analysis (NumPy/SciPy release the GIL on large arrays).

Results are combined in input order, so a threaded computation gives exactly the same values as the sequential one."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, TypeVar

import numpy as np

T = TypeVar("T")
R = TypeVar("R")

MIN_ROWS_PER_CHUNK = 64


def thread_map(fn: Callable[[T], R], items: Iterable[T], threads: int) -> list[R]:
    seq = list(items)
    if threads <= 1 or len(seq) <= 1:
        return [fn(x) for x in seq]
    with ThreadPoolExecutor(max_workers=min(threads, len(seq)), thread_name_prefix="eae-stat") as ex:
        return list(ex.map(fn, seq))


def rowwise(fn: Callable[[slice], np.ndarray], height: int, threads: int) -> np.ndarray:
    """Evaluate a strictly per-pixel function on row bands and stack them (identical to ``fn(slice(None))``)."""
    n = min(threads, height // MIN_ROWS_PER_CHUNK)
    if n <= 1:
        return fn(slice(None))
    edges = np.linspace(0, height, n + 1).astype(int)
    parts = thread_map(lambda i: fn(slice(int(edges[i]), int(edges[i + 1]))), range(n), n)
    return np.concatenate(parts, axis=0)


class Background:
    """A single computation started on a helper thread and joined later; ``result()`` re-raises its exception."""

    def __init__(self, fn: Callable[[], Any], enabled: bool = True) -> None:
        self._ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eae-bg") if enabled else None
        self._fut = self._ex.submit(fn) if self._ex else None
        self._value = None if self._ex else fn()

    def result(self) -> Any:
        if self._fut is not None:
            try:
                self._value = self._fut.result()
            finally:
                self._ex.shutdown(wait=True)
                self._fut = None
        return self._value
