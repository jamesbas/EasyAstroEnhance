"""ONNX Runtime sessions for the AI tools: GPU (DirectML on Windows, CUDA elsewhere) first, CPU as the fallback.

Sessions are cached per worker process while it is busy (loading the 450 MB denoise model takes seconds, and a batch
reuses them); the worker drops them - and the GPU memory DirectML/CUDA keeps for each model, several GB in total - once
it has been idle for a minute (``services.worker.AI_IDLE_RELEASE_S``). A failure on the GPU provider
drops that session and repeats the work on the CPU provider; the fallback is recorded in the run report.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

import numpy as np

GPU_PROVIDERS = ("DmlExecutionProvider", "CUDAExecutionProvider")
PROVIDER_LABELS = {"DmlExecutionProvider": "GPU (DirectML)", "CUDAExecutionProvider": "GPU (CUDA)", "CPUExecutionProvider": "CPU"}
_sessions: dict[tuple[str, str], Any] = {}
_lock = threading.Lock()


class AIUnavailable(RuntimeError):
    pass


def ort_module():
    try:
        import onnxruntime as ort
    except Exception as exc:  # pragma: no cover - dependency is locked, but keep the app usable without it
        raise AIUnavailable(f"ONNX Runtime is not installed ({type(exc).__name__}).") from exc
    return ort


def available_providers() -> list[str]:
    try:
        return list(ort_module().get_available_providers())
    except AIUnavailable:
        return []


def provider_order(device: str) -> list[str]:
    avail = available_providers()
    if not avail:
        raise AIUnavailable("ONNX Runtime is not installed.")
    gpu = [p for p in GPU_PROVIDERS if p in avail] if device != "cpu" else []
    return gpu[:1] + ["CPUExecutionProvider"]


def _session(path: Path, provider: str):
    key = (str(path), provider)
    with _lock:
        s = _sessions.get(key)
        if s is None:
            ort = ort_module()
            so = ort.SessionOptions()
            so.log_severity_level = 3
            if provider == "DmlExecutionProvider":  # DirectML requires these settings
                so.enable_mem_pattern = False
                so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            s = ort.InferenceSession(str(path), so, providers=[provider] if provider == "CPUExecutionProvider" else [provider, "CPUExecutionProvider"])
            _sessions[key] = s
        return s


def drop_sessions() -> bool:
    """Release every cached session (and the GPU memory its provider holds). Returns True if any were cached."""
    with _lock:
        had = bool(_sessions)
        _sessions.clear()
    if had:
        import gc

        gc.collect()  # sessions are freed when the last reference goes; collect any cycles holding one
    return had


def has_sessions() -> bool:
    with _lock:
        return bool(_sessions)


class Runner:
    """Runs one model on NHWC batches (the caller's layout); converts to the model's layout when it is NCHW."""

    def __init__(self, path: Path, device: str = "auto", nchw: bool = False) -> None:
        self.path = Path(path)
        self.order = provider_order(device)
        self.nchw = nchw
        self.fallbacks: list[dict[str, str]] = []
        self.provider = self.order[0]
        self._s = None

    @property
    def label(self) -> str:
        return PROVIDER_LABELS.get(self.provider, self.provider)

    def _get(self):
        if self._s is None:
            self._s = _session(self.path, self.provider)
            used = self._s.get_providers()[0]
            if used != self.provider:  # provider silently unavailable for this model
                self.fallbacks.append({"from": self.provider, "message": f"{PROVIDER_LABELS.get(self.provider, self.provider)} could not load the model; used {PROVIDER_LABELS.get(used, used)}."})
                self.provider = used
        return self._s

    @property
    def input_shape(self) -> list[Any]:
        return list(self._get().get_inputs()[0].shape)

    def __call__(self, batch: np.ndarray) -> np.ndarray:
        x = np.ascontiguousarray(batch.transpose(0, 3, 1, 2) if self.nchw else batch, dtype=np.float32)
        while True:
            s = self._get()
            try:
                y = s.run(None, {s.get_inputs()[0].name: x})[0]
                break
            except Exception as exc:
                if self.provider == "CPUExecutionProvider":
                    raise
                self.fallbacks.append({"from": self.provider, "message": f"{type(exc).__name__}: {str(exc)[:200]}; repeated on the CPU."})
                with _lock:
                    _sessions.pop((str(self.path), self.provider), None)
                self.provider, self._s = "CPUExecutionProvider", None
        y = np.asarray(y, dtype=np.float32)
        return y.transpose(0, 2, 3, 1) if self.nchw else y


ModelFn = Callable[[np.ndarray], np.ndarray]
