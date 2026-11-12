"""GPU through the full stack (worker process, probe, settings, truthful labels). Skipped without CUDA."""
from __future__ import annotations

import imagecodecs
import numpy as np
import pytest

from app.processing.backends import probe_cuda
from conftest import synthetic_field, write_jpeg
from integration.test_jpeg_slice import default_recipe, ready, run_job, upload

pytestmark = pytest.mark.gpu


@pytest.fixture(scope="module")
def cuda_ok():
    pytest.importorskip("cupy")
    if not probe_cuda()["ok"]:
        pytest.skip("No working CUDA device")


def test_gpu_job_reports_actual_backend_and_matches_cpu_output(client, tmp_path, cuda_ok):
    arr, _ = synthetic_field(h=1080, w=1920, n_stars=300, seed=5)
    a = ready(client, upload(client, write_jpeg(tmp_path / "wide.jpg", arr))["id"])
    probed = client.post("/api/v1/compute/probe").json()
    assert probed["gpu_usable"] and probed["probe"]["device_name"] and probed["resolved_label"] == "Processing: GPU + CPU"
    client.patch("/api/v1/settings/compute", json={"device": "gpu"})
    g = run_job(client, [a["id"]], default_recipe(client, "brighter-detail"), key="gpu-api-0001")
    client.patch("/api/v1/settings/compute", json={"device": "cpu"})
    c = run_job(client, [a["id"]], default_recipe(client, "brighter-detail"), key="cpu-api-0001")
    rg = client.get(f"/api/v1/runs/{g['items'][0]['run_id']}").json()
    rc = client.get(f"/api/v1/runs/{c['items'][0]['run_id']}").json()
    assert rg["applied"]["execution"]["actual_backend"] == "gpu" and rg["backend_label"] == "Processing: GPU + CPU"
    assert rc["applied"]["execution"]["actual_backend"] == "cpu" and rc["backend_label"] == "Processing: CPU"
    assert rg["id"] != rc["id"]  # backend is part of the cache key
    pg = imagecodecs.png_decode(client.get(f"/api/v1/runs/{rg['id']}/exports/png").content).astype(int)
    pc = imagecodecs.png_decode(client.get(f"/api/v1/runs/{rc['id']}/exports/png").content).astype(int)
    assert np.abs(pg - pc).max() <= 1  # no bitwise identity promise, but visually equivalent within one display level
    rep = client.get(f"/api/v1/runs/{rg['id']}/exports/report").json()
    assert rep["applied"]["dependencies"]["packages"]["cupy-cuda13x"] and rep["gpu_probe"]["cuda_driver_version"]
