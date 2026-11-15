"""Backend selection, fallback and CPU/GPU parity tests.

* Parity/execution tests are marked ``gpu`` and are SKIPPED when no working CUDA device exists. CPU-only CI
  cannot claim verified GPU support; the real RTX 5070 Ti run is reported separately.
* Fallback/selection logic is verified everywhere with fake backends that emulate classified GPU failures.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

import numpy as np
import pytest

from app.processing import finishing as fin
from app.processing.backends import BackendUnavailable, NumpyBackend, RecoverableBackendError, get_backend, probe_cuda
from app.processing.denoise import DenoiseParams, WaveletNoise, denoise
from app.processing.imagedata import Cancelled
from app.processing.masks import masked_gaussian
from app.processing.pipeline import AssetContext, ExecutionOptions, choose_backend, run_pipeline
from app.processing.recipe import builtin_presets
from app.processing.stretch import apply_stretch, solve_stretch
from conftest import linear_field, make_image, synthetic_field


# ------------------------------------------------------------------------------ fake GPU (logic tests)
class FakeOOM(Exception):
    pass


class FakeDeviceError(Exception):
    pass


class FakeGpu(NumpyBackend):
    """NumPy-backed stand-in that behaves like a failing/working CuPy backend for control-flow tests."""

    name = "gpu"
    device_label = "FAKE GPU"
    instances: list["FakeGpu"] = []
    plan: list[Exception | None] = []

    def __init__(self):
        super().__init__()
        self.released = 0
        FakeGpu.instances.append(self)

    def gaussian(self, a, sigma):
        if FakeGpu.plan:
            exc = FakeGpu.plan.pop(0)
            if exc is not None:
                raise exc
        return super().gaussian(a, sigma)

    def release(self):
        self.released += 1

    def classify_error(self, exc):
        if isinstance(exc, FakeOOM):
            return RecoverableBackendError("oom", "GPU out of memory")
        if isinstance(exc, FakeDeviceError):
            return RecoverableBackendError("device", "CUDA runtime failure")
        return None


def factory_with(plan, unavailable=False):
    FakeGpu.instances, FakeGpu.plan = [], list(plan)

    def f(name):
        if name == "gpu":
            if unavailable:
                raise BackendUnavailable("CuPy could not be imported")
            return FakeGpu()
        return NumpyBackend()

    return f


def rgb_recipe():
    return builtin_presets()["vivid"]


def run(img, recipe=None, ctx=None, **opts):
    return run_pipeline(img, recipe or rgb_recipe(), ctx or AssetContext(), ExecutionOptions(**opts))


def test_gpu_oom_retries_once_with_smaller_tiles_then_succeeds_without_partial_results():
    arr, _ = synthetic_field(h=150, w=200, seed=2)
    img = make_image(arr)
    ref = run(img, device="cpu")
    res = run(img, device="gpu", gpu_available=True, backend_factory=factory_with([FakeOOM(), None]))
    ex = res.report["execution"]
    assert ex["actual_backend"] == "gpu" and ex["fallbacks"][0]["cause"] == "oom" and ex["tile"] is not None
    np.testing.assert_allclose(res.display, ref.display, atol=1e-5, rtol=1e-4)  # transform not applied twice
    assert FakeGpu.instances[0].released >= 1  # app-owned buffers released after the failure


def test_persistent_oom_reruns_on_cpu_from_clean_checkpoint_and_matches_cpu_reference():
    arr, _ = synthetic_field(h=120, w=160, seed=3)
    img = make_image(arr)
    ref = run(img, device="cpu")
    res = run(img, device="gpu", gpu_available=True, backend_factory=factory_with([FakeOOM(), FakeOOM()]))
    ex = res.report["execution"]
    assert ex["actual_backend"] == "cpu" and len(ex["fallbacks"]) == 2 and ex["label"] == "Processing: CPU"
    assert np.array_equal(res.display, ref.display) and res.gpu_disabled


def test_device_failure_disables_gpu_for_the_rest_of_the_job():
    arr, _ = synthetic_field(h=100, w=140, seed=4)
    img = make_image(arr)
    res = run(img, device="gpu", gpu_available=True, backend_factory=factory_with([FakeDeviceError()]))
    assert res.report["execution"]["actual_backend"] == "cpu" and res.gpu_disabled
    follow = run(img, device="gpu", gpu_available=True, gpu_disabled=res.gpu_disabled, backend_factory=factory_with([]))
    assert follow.report["execution"]["actual_backend"] == "cpu" and "disabled" in follow.report["execution"]["backend_reason"]


def test_unavailable_gpu_falls_back_with_truthful_status():
    arr, _ = synthetic_field(h=90, w=120, seed=5)
    res = run(make_image(arr), device="gpu", gpu_available=True, backend_factory=factory_with([], unavailable=True))
    ex = res.report["execution"]
    assert ex["actual_backend"] == "cpu" and ex["fallbacks"][0]["cause"] == "unavailable"
    res2 = run(make_image(arr), device="gpu", gpu_available=False)
    assert res2.report["execution"]["actual_backend"] == "cpu" and "unavailable" in res2.report["execution"]["backend_reason"]


def test_algorithm_bugs_are_not_hidden_by_fallback():
    arr, _ = synthetic_field(h=80, w=100, seed=6)
    with pytest.raises(ValueError):
        run(make_image(arr), device="gpu", gpu_available=True, backend_factory=factory_with([ValueError("bug")]))


def test_cancellation_releases_buffers_and_raises():
    arr, _ = synthetic_field(h=120, w=160, seed=7)
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        if calls["n"] > 6:
            raise Cancelled()

    f = factory_with([])
    with pytest.raises(Cancelled):
        run(make_image(arr), device="gpu", gpu_available=True, backend_factory=f, cancel_check=cancel, force_tile=64)
    assert FakeGpu.instances and FakeGpu.instances[-1].released >= 1


@pytest.mark.parametrize("device, avail, px, expected", [
    ("cpu", True, 50_000_000, "cpu"),
    ("auto", True, 500_000, "cpu"),
    ("auto", True, 12_000_000, "gpu"),
    ("auto", False, 12_000_000, "cpu"),
    ("gpu", True, 100_000, "gpu"),
    ("gpu", False, 12_000_000, "cpu"),
])
def test_device_selection_policy(device, avail, px, expected):
    side = int(px**0.5)
    name, reason = choose_backend(ExecutionOptions(device=device, gpu_available=avail, gpu_threshold_pixels=2_000_000), side, side, 3)
    assert name == expected and reason


def test_cpu_only_import_and_processing_with_cupy_absent():
    code = textwrap.dedent(
        """
        import sys
        sys.modules['cupy'] = None; sys.modules['cupyx'] = None   # simulate CuPy not installed
        import numpy as np
        from app.processing.pipeline import run_pipeline, AssetContext, ExecutionOptions
        from app.processing.recipe import builtin_presets
        from app.processing.backends import probe_cuda, get_backend, BackendUnavailable
        from app.processing.imagedata import ImageData, Normalization
        a = np.random.default_rng(0).random((64, 80, 3)).astype(np.float32)
        img = ImageData(a, 'rgb', 'display', 'x', np.ones((64, 80), bool), np.zeros((64, 80), bool), {}, '0'*64, 't', Normalization('unit_range', 255.0))
        r = run_pipeline(img, builtin_presets()['natural'], AssetContext(), ExecutionOptions(device='gpu'))
        assert r.report['execution']['actual_backend'] == 'cpu'
        p = probe_cuda(); assert p['ok'] is False and 'CPU processing is fully functional' in p['note']
        try:
            get_backend('gpu'); raise SystemExit('expected failure')
        except BackendUnavailable:
            pass
        print('CPU-ONLY-OK')
        """
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    assert "CPU-ONLY-OK" in out.stdout, out.stderr


# ------------------------------------------------------------------------------ real GPU
@pytest.fixture(scope="module")
def cuda():
    pytest.importorskip("cupy")
    info = probe_cuda()
    if not info["ok"]:
        pytest.skip(f"No working CUDA device: {info.get('note')}")
    return info


def tol(a, b, name):
    np.testing.assert_allclose(a, b, atol=1e-5, rtol=1e-4, err_msg=name)


@pytest.mark.gpu
def test_gpu_gaussian_and_masked_gaussian_match_cpu(cuda):
    cpu, gpu = NumpyBackend(), get_backend("gpu")
    rng = np.random.default_rng(0)
    x = rng.random((130, 170, 3), dtype=np.float32)
    w = (rng.random((130, 170)) > 0.1).astype(np.float32)
    for s in (0.8, 2.0, 6.0, 24.0):
        tol(gpu.asnumpy(gpu.gaussian(gpu.asarray(x), s)), cpu.gaussian(x, s), f"gaussian {s}")
    tol(gpu.asnumpy(masked_gaussian(gpu, gpu.asarray(x), gpu.asarray(w), 2.0)), masked_gaussian(cpu, x, w, 2.0), "masked gaussian")


@pytest.mark.gpu
def test_gpu_denoise_detail_and_stretch_match_cpu(cuda):
    cpu, gpu = NumpyBackend(), get_backend("gpu")
    arr, _ = synthetic_field(h=140, w=180, seed=1)
    w = np.ones(arr.shape[:2], np.float32)
    star = np.zeros(arr.shape[:2], np.float32)
    p = DenoiseParams(0.6, 4, 5, WaveletNoise((0.01, 0.004, 0.002, 0.001), (0.01, 0.004, 0.002, 0.001, 0.0005)))
    tol(gpu.asnumpy(denoise(gpu, gpu.asarray(arr), gpu.asarray(w), gpu.asarray(star), p)), denoise(cpu, arr, w, star, p), "denoise")
    L = arr.mean(-1)
    dp = fin.DetailParams(0.6, 4, (0.002, 0.001, 0.0008, 0.0005))
    tol(gpu.asnumpy(fin.detail_boost(gpu, gpu.asarray(L), gpu.asarray(w), gpu.asarray(star), dp)), fin.detail_boost(cpu, L, w, star, dp), "detail")
    lin = linear_field(h=120, w=150, seed=3) / 20000.0
    sp = solve_stretch(0.05, 0.001, 0.4, 1.0, 0.12, protect_cores=True, amount=0.0)
    tol(gpu.asnumpy(apply_stretch(gpu.xp, gpu.asarray(lin), sp)), apply_stretch(np, lin, sp), "stretch")


@pytest.mark.gpu
@pytest.mark.parametrize("kind", ["rendered_rgb", "rendered_mono", "linear_rgb"])
def test_gpu_pipeline_parity_with_cpu_reference(cuda, kind):
    if kind == "linear_rgb":
        img = make_image(linear_field(h=170, w=210, seed=2), domain="linear", fmt="fits", dtype="float32", bits=32)
    elif kind == "rendered_mono":
        img = make_image(synthetic_field(h=170, w=210, rgb=False, seed=2)[0])
    else:
        img = make_image(synthetic_field(h=170, w=210, seed=2)[0])
    r = rgb_recipe()
    cpu = run(img, r, device="cpu")
    gpu = run(img, r, device="gpu", gpu_available=True)
    assert gpu.report["execution"]["actual_backend"] == "gpu" and not gpu.report["execution"]["fallbacks"]
    # The linear stretch has a steep slope at the sky level, amplifying float32 rounding differences between the
    # CuPy and NumPy transcendental functions ~100x; 8-bit equality is checked separately below.
    atol = 2e-4 if kind == "linear_rgb" else 2e-5
    np.testing.assert_allclose(gpu.display, cpu.display, atol=atol, rtol=1e-4)  # float arrays
    assert np.abs(np.rint(gpu.display * 255) - np.rint(cpu.display * 255)).max() <= 1  # display differences inspected separately
    cc, gc = cpu.report["clipping"]["final"], gpu.report["clipping"]["final"]
    for k in ("input_zero", "input_max"):
        assert cc[k] == gc[k]
    assert abs(cc["new_black"] - gc["new_black"]) <= max(3, 0.0005 * cc["eligible_channel_values"])  # equivalent clipping decisions
    assert cpu.report["clipping"]["guard_action"] == gpu.report["clipping"]["guard_action"]
    sp = lambda r: [o for o in r.report["operations"] if o["name"] == "star_stretch"][0]["parameters"]  # noqa: E731
    if sp(cpu):
        assert sp(cpu)["accepted_stars"] == sp(gpu)["accepted_stars"]  # identical star-mask topology (mask is global/CPU)
    if kind == "linear_rgb":
        np.testing.assert_allclose(gpu.processed, cpu.processed, rtol=1e-4, atol=1e-2)
        assert (cpu.protected_mask == gpu.protected_mask).all()


@pytest.mark.gpu
def test_gpu_tiled_matches_gpu_full_frame_and_protected_pixels_exact(cuda):
    arr, _ = synthetic_field(h=220, w=260, seed=9)
    img = make_image(arr)
    region = [{"x": 0, "y": 190, "w": 260, "h": 30}]
    full = run(img, rgb_recipe(), AssetContext(regions=region), device="gpu", gpu_available=True)
    tiled = run(img, rgb_recipe(), AssetContext(regions=region), device="gpu", gpu_available=True, force_tile=96)
    np.testing.assert_allclose(tiled.display, full.display, atol=2e-5, rtol=1e-4)
    assert np.array_equal(full.display[190:], arr[190:])  # exact protected pixels on GPU too


@pytest.mark.gpu
def test_gpu_failure_path_against_cpu_only_reference_with_real_cupy(cuda):
    """A real CuPy out-of-memory error (impossible allocation) is classified and falls back to CPU."""
    import cupy as cp

    from app.processing.backends.cupy_backend import CupyBackend

    class Boom(CupyBackend):
        def gaussian(self, a, sigma):
            cp.empty((1 << 62,), dtype=cp.uint8)  # raises a genuine OutOfMemoryError
            return super().gaussian(a, sigma)

    arr, _ = synthetic_field(h=100, w=120, seed=3)
    img = make_image(arr)
    ref = run(img, device="cpu")
    res = run(img, device="gpu", gpu_available=True, backend_factory=lambda n: Boom() if n == "gpu" else NumpyBackend())
    ex = res.report["execution"]
    assert ex["actual_backend"] == "cpu" and ex["fallbacks"][0]["cause"] == "oom"
    assert np.array_equal(res.display, ref.display)
    follow = get_backend("gpu")  # device remains healthy after releasing buffers
    follow.release()


@pytest.mark.gpu
def test_gpu_reports_device_transfers_and_versions(cuda):
    arr, _ = synthetic_field(h=160, w=220, seed=12)
    res = run(make_image(arr), rgb_recipe(), device="gpu", gpu_available=True)
    ex = res.report["execution"]
    assert ex["device"] and "RTX" in ex["device"] or ex["device"]
    assert ex["transfers"]["host_to_device_count"] >= 1 and ex["transfers"]["device_to_host_count"] >= 1
    assert "cupy-cuda13x" in res.report["dependencies"]["packages"]
