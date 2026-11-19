"""Downloads of the pinned AI models into the app's data folder (user-initiated; fixed URLs; SHA-256 verified).

Runs in the server process on background threads (network/disk bound). A file is only published after its size and
SHA-256 match the registry; a sidecar records the verified hash so runs do not re-hash 450 MB on every use. When an
existing GraXpert installation already holds the identical file it is copied instead of downloaded.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..processing.ai import registry
from ..processing.ai.runtime import PROVIDER_LABELS, available_providers

if sys.platform == "win32":
    import truststore

CHUNK = 1024 * 1024
TIMEOUT_S = 60


def _download_context() -> ssl.SSLContext | None:
    if sys.platform == "win32":
        # Native chain validation can fetch missing intermediates on a fresh Windows install.
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return None


class ModelManager:
    def __init__(self, models_dir: Path, min_free_bytes: int = 256 * 1024 * 1024, graxpert_root: Path | None = None) -> None:
        self.dir = Path(models_dir)
        self.min_free = min_free_bytes
        local = os.environ.get("LOCALAPPDATA")
        self.graxpert_root = graxpert_root if graxpert_root is not None else (Path(local) / "GraXpert" / "GraXpert" if local else None)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancel: dict[str, threading.Event] = {}

    # ------------------------------------------------------------------ queries
    def status(self, spec: registry.ModelSpec) -> dict[str, Any]:
        job = self._jobs.get(spec.id) or {}
        installed = registry.installed(self.dir, spec) is not None
        state = "installed" if installed else job.get("state", "missing")
        if installed and job.get("state") == "downloading":
            state = "downloading"
        return {
            **{k: v for k, v in spec.to_dict().items() if k != "graxpert_dir"},
            "state": state, "received": job.get("received", 0), "error": job.get("error") if state == "error" else None,
            "local_graxpert_copy": self._graxpert_copy(spec) is not None,
        }

    def overview(self) -> dict[str, Any]:
        provs = available_providers()
        gpu = next((p for p in ("DmlExecutionProvider", "CUDAExecutionProvider") if p in provs), None)
        models = [self.status(m) for m in registry.MODELS.values()]
        by_id = {m["id"]: m for m in models}
        tools = {}
        for tool, ids in registry.TOOL_MODELS.items():
            states = [by_id[i]["state"] for i in ids]
            tools[tool] = {
                "models": ids, "ready": by_id[ids[0]]["state"] == "installed",
                "state": "installed" if all(s == "installed" for s in states) else "downloading" if "downloading" in states else "error" if "error" in states else "missing",
                "download_bytes": sum(registry.MODELS[i].size for i in ids if by_id[i]["state"] != "installed"),
            }
        return {
            "models": models, "tools": tools, "runtime_available": bool(provs),
            "provider_label": PROVIDER_LABELS.get(gpu, "CPU") if gpu else ("CPU" if provs else None),
            "models_dir": str(self.dir),
            "note": "Optional learned (AI) tools. Each model is a trained neural network run on this computer; files are downloaded "
                    "once from the listed source and verified by SHA-256.",
        }

    # ------------------------------------------------------------------ actions
    def start(self, model_id: str) -> dict[str, Any]:
        spec = registry.MODELS[model_id]
        with self._lock:
            if registry.installed(self.dir, spec) or (self._jobs.get(model_id) or {}).get("state") == "downloading":
                return self.status(spec)
            self._jobs[model_id] = {"state": "downloading", "received": 0, "started": time.time()}
            self._cancel[model_id] = threading.Event()
        threading.Thread(target=self._run, args=(spec,), daemon=True, name=f"ai-download-{model_id}").start()
        return self.status(spec)

    def cancel(self, model_id: str) -> None:
        ev = self._cancel.get(model_id)
        if ev:
            ev.set()

    def delete(self, model_id: str) -> None:
        spec = registry.MODELS[model_id]
        self.cancel(model_id)
        p = registry.model_file(self.dir, spec)
        for f in (p.with_name(p.name + registry.VERIFIED_SUFFIX), p, p.with_name(p.name + ".part")):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        with self._lock:
            self._jobs.pop(model_id, None)

    def wait(self, model_id: str, timeout: float = 60.0) -> dict[str, Any]:
        t0 = time.time()
        while time.time() - t0 < timeout and (self._jobs.get(model_id) or {}).get("state") == "downloading":
            time.sleep(0.05)
        return self.status(registry.MODELS[model_id])

    # ------------------------------------------------------------------ internals
    def _graxpert_copy(self, spec: registry.ModelSpec) -> Path | None:
        if not (self.graxpert_root and spec.graxpert_dir):
            return None
        p = self.graxpert_root / spec.graxpert_dir / spec.version / "model.onnx"
        try:
            return p if p.stat().st_size == spec.size else None
        except OSError:
            return None

    def _run(self, spec: registry.ModelSpec) -> None:
        job, cancel = self._jobs[spec.id], self._cancel[spec.id]
        final = registry.model_file(self.dir, spec)
        part = final.with_name(final.name + ".part")
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.dir).free < spec.size + self.min_free:
                raise RuntimeError(f"Not enough free disk space for {spec.size / 1e6:.0f} MB.")
            h = hashlib.sha256()
            local = self._graxpert_copy(spec)
            src = open(local, "rb") if local else urllib.request.urlopen(  # noqa: SIM115 - closed below
                urllib.request.Request(spec.url, headers={"User-Agent": "EasyAstroEnhance"}),
                timeout=TIMEOUT_S,
                context=_download_context(),
            )
            try:
                with open(part, "wb") as out:
                    while chunk := src.read(CHUNK):
                        if cancel.is_set():
                            raise InterruptedError("Download cancelled.")
                        out.write(chunk)
                        h.update(chunk)
                        job["received"] += len(chunk)
                        if job["received"] > spec.size:
                            raise RuntimeError("The download is larger than expected; it was discarded.")
            finally:
                src.close()
            if job["received"] != spec.size or h.hexdigest() != spec.sha256:
                raise RuntimeError("The downloaded file did not match the expected SHA-256; it was discarded.")
            part.replace(final)
            final.with_name(final.name + registry.VERIFIED_SUFFIX).write_text(spec.sha256, encoding="ascii")
            job.update(state="installed", source="local GraXpert installation" if local else spec.url)
        except BaseException as exc:  # never leave a partial file behind
            part.unlink(missing_ok=True)
            if isinstance(exc, InterruptedError):
                job.update(state="missing", error=None)
            elif isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, ssl.SSLCertVerificationError):
                job.update(
                    state="error",
                    error="Could not verify the model download site's HTTPS certificate. "
                          "Check this computer's date, time and trusted certificates. "
                          "On a managed network, ask your administrator to check the proxy certificate.",
                )
            else:
                job.update(state="error", error=str(exc) or type(exc).__name__)
