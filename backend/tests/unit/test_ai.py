"""Optional AI tools: exact mechanics with tiny synthetic ONNX models, pipeline wiring, model downloads, migration.

Tests marked ``aimodels`` use the real downloaded models (EAE_AI_MODELS_DIR, default: the app's ai-models folder) on a
real Seestar stack and are skipped when either is missing.
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import numpy as np
import pytest

from app.processing.ai import registry
from app.processing.ai import runtime as rt
from app.processing.ai.tiles import resize_linear, tile_apply
from app.processing.ai.tools import ai_background, ai_denoise, separate_stars
from app.processing.pipeline import AssetContext, ExecutionOptions, prepare_linear_frame, run_pipeline
from app.processing.recipe import AIRecipe, RECIPE_SCHEMA_VERSION, builtin_presets, parse_recipe
from conftest import linear_field, make_image, synthetic_field

onnx = pytest.importorskip("onnx")
from onnx import TensorProto, helper  # noqa: E402


# ------------------------------------------------------------------------------ synthetic models (test fixtures only)
def _model(path: Path, kind: str, nchw: bool, name_in: str) -> Path:
    shape = ["N", 3, 256, 256] if nchw else ["N", 256, 256, 3]
    x = helper.make_tensor_value_info(name_in, TensorProto.FLOAT, shape)
    y = helper.make_tensor_value_info("output", TensorProto.FLOAT, shape)
    node = helper.make_node("Identity", [name_in], ["output"]) if kind == "identity" else helper.make_node("Sub", [name_in, name_in], ["output"])
    m = helper.make_model(helper.make_graph([node], kind, [x], [y]), opset_imports=[helper.make_opsetid("", 13)])
    m.ir_version = 8
    onnx.save(m, str(path))
    return path


def _cpu(path: Path, nchw=False) -> rt.Runner:
    return rt.Runner(path, "cpu", nchw=nchw)


@pytest.fixture()
def models(tmp_path, monkeypatch):
    """Install synthetic stand-ins under the registry ids (background: zeros, denoise/stars: identity)."""
    d = tmp_path / "ai-models"
    d.mkdir()
    import hashlib

    patched = {}
    for mid, spec in registry.MODELS.items():
        kind = "zero" if spec.tool == "background" else "identity"
        p = _model(d / spec.file, kind, spec.tool == "stars", "input" if spec.tool == "stars" else "gen_input_image")
        data = p.read_bytes()
        new = dataclasses.replace(spec, sha256=hashlib.sha256(data).hexdigest(), size=len(data), url=p.as_uri())
        (d / (spec.file + registry.VERIFIED_SUFFIX)).write_text(new.sha256, encoding="ascii")
        patched[mid] = new
    monkeypatch.setattr(registry, "MODELS", patched)
    rt.drop_sessions()
    return d


# ------------------------------------------------------------------------------ tiling
@pytest.mark.parametrize("shape", [(37, 53, 3), (300, 517, 3), (256, 256, 1), (600, 250, 3)])
@pytest.mark.parametrize("tile, step, margin", [(256, 128, 64), (256, 208, 8)])
def test_tiles_reproduce_identity_and_offsets_exactly(shape, tile, step, margin):
    rng = np.random.default_rng(0)
    img = rng.normal(size=shape).astype(np.float32)
    out = tile_apply(img, lambda b: b, tile, step, margin, batch=3)
    assert out.shape == img.shape and np.allclose(out, img, atol=1e-5)
    out2 = tile_apply(img, lambda b: b + 2.0, tile, step, margin)
    assert np.allclose(out2, img + 2.0, atol=1e-5)  # weights are normalized everywhere


def test_resize_linear_keeps_constants_and_ramps():
    a = np.full((40, 60, 2), 3.5, np.float32)
    assert np.allclose(resize_linear(a, 7, 11), 3.5)
    ramp = np.tile(np.arange(64, dtype=np.float32), (8, 1))[..., None]
    up = resize_linear(ramp, 8, 128)[0, 10:-10, 0]
    assert np.allclose(np.diff(up), 0.5, atol=1e-5)


# ------------------------------------------------------------------------------ tools with synthetic models
def test_denoise_identity_model_roundtrip_and_strength(tmp_path):
    x = linear_field(h=300, w=260, seed=3) / 7000.0
    valid = np.ones(x.shape[:2], bool)
    valid[:5] = False
    run = _cpu(_model(tmp_path / "id.onnx", "identity", False, "gen_input_image"))
    out, info = ai_denoise(x, valid, 1.0, run)
    assert np.allclose(out, x, rtol=1e-4, atol=1e-6)
    zero = _cpu(_model(tmp_path / "z.onnx", "zero", False, "gen_input_image"))
    flat, _ = ai_denoise(x, valid, 1.0, zero)
    half, _ = ai_denoise(x, valid, 0.5, zero)
    assert np.allclose(half, 0.5 * (flat + x), atol=1e-6)
    sub = x[::4, ::4].reshape(-1, 3)
    med = np.median(sub, 0)
    mad = np.median(np.abs(sub - med), 0)
    bright = ((x - med) / mad * 0.04 >= 10.0) & valid[..., None]
    assert bright.any() and np.array_equal(flat[bright], x[bright])  # bright cores pass through unchanged
    assert np.array_equal(flat[~valid], x[~valid])  # masked pixels untouched
    mono, _ = ai_denoise(x[..., 1], valid, 1.0, run)
    assert mono.shape == x.shape[:2] and np.allclose(mono, x[..., 1], rtol=1e-4, atol=1e-6)


def test_background_zero_model_changes_nothing(tmp_path):
    x = linear_field(h=200, w=300, seed=2) / 7000.0
    bg, info = ai_background(x, np.ones(x.shape[:2], bool), _cpu(_model(tmp_path / "z.onnx", "zero", False, "gen_input_image")))
    assert bg.shape == x.shape and np.abs(bg).max() < 1e-6


def test_star_separation_identity_is_lossless_and_sums_exactly(tmp_path):
    x = linear_field(h=280, w=330, seed=5) / 7000.0
    valid = np.ones(x.shape[:2], bool)
    starless, stars, info = separate_stars(x, valid, _cpu(_model(tmp_path / "id.onnx", "identity", True, "input"), nchw=True), 256)
    assert np.array_equal(starless + stars, x) or np.allclose(starless + stars, x, atol=1e-7)
    assert stars.min() >= 0 and stars.max() < 1e-4
    assert info["temporary_stretch"].startswith("unlinked")


def test_star_separation_keeps_extended_structure_out_of_the_star_layer(tmp_path):
    """A 'remove everything' model: stars land in the star layer, a large bright galaxy core does not."""
    h, w = 400, 400
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    rng = np.random.default_rng(1)
    base = 0.02 + 0.6 * np.exp(-(((xx - 200) / 70) ** 2 + ((yy - 200) / 45) ** 2))
    pos = [(60, 60), (330, 80), (80, 320), (340, 340), (200, 330)]
    for sy, sx in pos:
        base += 0.3 * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * 1.5**2))
    x = np.stack([base] * 3, -1).astype(np.float32) + rng.normal(0, 0.002, (h, w, 3)).astype(np.float32)
    starless, stars, info = separate_stars(x, np.ones((h, w), bool), _cpu(_model(tmp_path / "z.onnx", "zero", True, "input"), nchw=True), 256)
    assert np.allclose(starless + stars, x, atol=1e-6)
    for sy, sx in pos:
        assert stars[sy, sx, 1] > 0.5 * (x[sy, sx, 1] - starless[sy - 8, sx - 8, 1]) * 0.5
    assert stars[195:205, 195:205].max() < 0.05 * x[200, 200, 1]  # the core stays in the starless image


def test_runner_falls_back_to_cpu_when_the_gpu_provider_fails(tmp_path, monkeypatch):
    path = _model(tmp_path / "id.onnx", "identity", False, "gen_input_image")
    real = rt._session

    class Broken:
        def get_providers(self):
            return ["DmlExecutionProvider"]

        def get_inputs(self):
            return real(path, "CPUExecutionProvider").get_inputs()

        def run(self, *a, **k):
            raise RuntimeError("device removed")

    monkeypatch.setattr(rt, "provider_order", lambda device: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(rt, "_session", lambda p, prov: Broken() if prov == "DmlExecutionProvider" else real(p, prov))
    run = rt.Runner(path, "auto")
    b = np.random.default_rng(0).normal(size=(2, 256, 256, 3)).astype(np.float32)
    assert np.allclose(run(b), b) and run.provider == "CPUExecutionProvider" and "device removed" in run.fallbacks[0]["message"]


# ------------------------------------------------------------------------------ pipeline wiring
def _linear_image():
    arr = linear_field(h=180, w=220, seed=4, gradient=(300.0, 200.0))
    return make_image(arr, domain="linear", fmt="fits", dtype="float32", bits=32)


def _run(img, ai: AIRecipe, models_dir):
    r = builtin_presets()["natural"].model_copy(update={"ai": ai})
    return run_pipeline(img, r, AssetContext(frame=prepare_linear_frame(img).to_dict()), ExecutionOptions(device="cpu", ai_models_dir=models_dir))


def test_pipeline_runs_ai_tools_and_discloses_them(models):
    img = _linear_image()
    res = _run(img, AIRecipe(background=True, denoise=True, stars=True), models)
    ops = {o["name"]: o for o in res.report["operations"]}
    for name in ("ai_background", "ai_denoise", "ai_stars"):
        assert ops[name]["status"] == "applied", ops[name]
        p = ops[name]["parameters"]
        assert p["model"]["sha256"] == registry.MODELS[p["model"]["id"]].sha256 and p["execution_provider"] == "CPU" and p["kind"].startswith("learned")
    assert ops["gradient"]["status"] == "inactive" and ops["denoise"]["status"] == "inactive"
    assert ops["star_stretch"]["status"] == "applied" and "added back" in ops["star_stretch"]["parameters"]["method"]
    assert res.report["learned_processing"] == ["ai_background", "ai_denoise", "ai_stars"]
    assert "Learned (AI) processing was used" in res.report["scientific_disclosure"]
    assert "AI noise reduction" in res.summary and np.isfinite(res.display).all()
    # star separation is display-only: the processed-linear output is the same with and without it
    no_sep = _run(img, AIRecipe(background=True, denoise=True), models)
    assert np.allclose(res.processed, no_sep.processed)


def test_pipeline_identity_star_separation_matches_plain_main_stretch(models):
    img = _linear_image()
    natural = builtin_presets()["natural"]
    # noise reduction off: the measured sky noise is above the source-noise floor, so both runs solve the same stretch
    plain = natural.model_copy(update={"auto": natural.auto.model_copy(update={"star_stretch": False}), "look": natural.look.model_copy(update={"noise": 0.0})})
    a = run_pipeline(img, plain.model_copy(update={"ai": AIRecipe(stars=True)}), AssetContext(frame=prepare_linear_frame(img).to_dict()),
                     ExecutionOptions(device="cpu", ai_models_dir=models))
    b = run_pipeline(img, plain, AssetContext(frame=prepare_linear_frame(img).to_dict()), ExecutionOptions(device="cpu", ai_models_dir=models))
    assert np.abs(a.display - b.display).max() < 2e-3  # nothing separated -> same finishing as without the tool


def test_ai_smoothing_does_not_drive_a_deeper_stretch(models, monkeypatch):
    """A model that flattens the sky completely must not make the stretch solver lift everything (engine 1.2 noise floor)."""
    import hashlib

    spec = registry.MODELS["graxpert-denoise"]
    p = _model(models / spec.file, "zero", False, "gen_input_image")
    data = p.read_bytes()
    (models / (spec.file + registry.VERIFIED_SUFFIX)).write_text(hashlib.sha256(data).hexdigest(), encoding="ascii")
    monkeypatch.setitem(registry.MODELS, spec.id, dataclasses.replace(spec, sha256=hashlib.sha256(data).hexdigest(), size=len(data)))
    rt.drop_sessions()
    img = _linear_image()
    full = builtin_presets()["natural"]
    full = full.model_copy(update={"look": full.look.model_copy(update={"noise": 1.0})})
    ctx = lambda: AssetContext(frame=prepare_linear_frame(img).to_dict())  # noqa: E731
    opts = ExecutionOptions(device="cpu", ai_models_dir=models)
    classic = run_pipeline(img, full, ctx(), opts).report
    flat = run_pipeline(img, full.model_copy(update={"ai": AIRecipe(denoise=True)}), ctx(), opts).report
    assert flat["decisions"]["stretch_noise_floor"]["used"] > flat["decisions"]["stretch_noise_floor"]["measured_sigma"]
    assert flat["enhanced_frame"]["D"] < 5 * classic["enhanced_frame"]["D"]
    assert "stretch_noise_floor" not in classic["decisions"]  # classical runs are unchanged


def test_missing_models_skip_with_reason_and_classical_steps_run(tmp_path):
    img = _linear_image()
    res = _run(img, AIRecipe(background=True, denoise=True, stars=True), tmp_path / "none")
    ops = {o["name"]: o for o in res.report["operations"]}
    for name in ("ai_background", "ai_denoise", "ai_stars"):
        assert ops[name]["status"] == "skipped" and "not downloaded" in ops[name]["reason"]
    assert ops["denoise"]["status"] == "applied" and ops["gradient"]["status"] in ("applied", "skipped")
    assert res.report["learned_processing"] == [] and "No pixels were generated" in res.report["scientific_disclosure"]


def test_rendered_images_only_get_ai_denoise(models):
    arr, _ = synthetic_field()
    img = make_image(arr)
    r = builtin_presets()["natural"].model_copy(update={"ai": AIRecipe(background=True, denoise=True, stars=True)})
    res = run_pipeline(img, r, AssetContext(), ExecutionOptions(device="cpu", ai_models_dir=models))
    ops = {o["name"]: o for o in res.report["operations"]}
    assert ops["ai_background"]["status"] == "inactive" and ops["ai_stars"]["status"] == "inactive"
    assert ops["ai_denoise"]["status"] == "applied"


def test_schema3_recipes_and_presets_migrate_with_ai_off():
    old = builtin_presets()["vivid"].model_dump()
    old.pop("ai")
    old["schema_version"] = 3
    r = parse_recipe(old)
    assert r.schema_version == RECIPE_SCHEMA_VERSION and r.ai == AIRecipe() and r.look.color == builtin_presets()["vivid"].look.color
    for p in builtin_presets().values():
        assert p.ai == AIRecipe()  # AI tools are opt-in, never part of a built-in preset


# ------------------------------------------------------------------------------ real models on a real stack
AI_DIR = Path(os.environ.get("EAE_AI_MODELS_DIR") or Path(os.environ.get("LOCALAPPDATA", "~")) / "EasyAstroEnhance" / "ai-models")
M31 = Path(os.environ.get("EAE_SEESTAR_DIR", r"D:\Seestar\MyWorks")) / "M 31" / "Stacked_232_M 31_30.0s_IRCUT_20261108-210941.fit"


def _real(tool_id):
    spec = registry.MODELS[tool_id]
    p = registry.installed(AI_DIR, spec)
    if p is None or not M31.exists():
        pytest.skip("real AI models or the real M31 stack are not available")
    return p


def _m31_crop():
    from app.processing.stacking.frames import inspect_frame, read_frame

    img, _ = read_frame(inspect_frame(M31))
    x = img / img.max()
    h, w = x.shape[:2]
    return x[h // 2 - 512 : h // 2 + 512, w // 2 - 512 : w // 2 + 512].copy()  # galaxy core, dust lanes and stars


@pytest.mark.aimodels
@pytest.mark.realfiles
def test_real_ai_denoise_removes_colour_mottle_and_keeps_stars():
    from scipy import ndimage

    run = rt.Runner(_real("graxpert-denoise"), "auto")
    x = _m31_crop()
    valid = np.ones(x.shape[:2], bool)
    out, info = ai_denoise(x, valid, 1.0, run)

    def chroma(a):
        rg, bg = a[..., 0] - a[..., 1], a[..., 2] - a[..., 1]
        return np.median(np.abs(rg - ndimage.median_filter(rg, 21))) + np.median(np.abs(bg - ndimage.median_filter(bg, 21)))

    assert chroma(out) < 0.6 * chroma(x)
    peaks = x.mean(2) > np.percentile(x.mean(2), 99.9)
    assert np.median(out.mean(2)[peaks] / x.mean(2)[peaks]) > 0.95  # star and core peaks are kept


@pytest.mark.aimodels
@pytest.mark.realfiles
def test_real_star_separation_keeps_the_galaxy_core_and_sums_exactly():
    run = rt.Runner(_real("darkstar-color"), "auto", nchw=True)
    x = _m31_crop()
    starless, stars, info = separate_stars(x, np.ones(x.shape[:2], bool), run, run.input_shape[2])
    assert np.allclose(starless + stars, x, atol=1e-6) and stars.min() >= 0
    c = 512
    assert stars[c - 30 : c + 30, c - 30 : c + 30].mean() < 0.02 * x[c - 30 : c + 30, c - 30 : c + 30].mean()  # core is not a star
    assert 0.02 < info["star_flux_fraction"] < 0.6


@pytest.mark.aimodels
@pytest.mark.realfiles
def test_real_ai_background_removes_an_added_gradient():
    run = rt.Runner(_real("graxpert-background"), "auto")
    from app.processing.stacking.frames import inspect_frame, read_frame

    img, _ = read_frame(inspect_frame(M31))
    x = (img / img.max())[::2, ::2].copy()
    h, w = x.shape[:2]
    ramp = (np.linspace(0, 1, w)[None, :, None] * 0.6 * np.median(x)).astype(np.float32)
    bg, _ = ai_background(x + ramp, np.ones((h, w), bool), run)
    corrected = x + ramp - bg
    sky = lambda a, sl: float(np.median(a[h // 10 : h // 4, sl, 1]))  # noqa: E731 - star-field strip away from the galaxy
    before = sky(x + ramp, slice(w - 200, w)) - sky(x + ramp, slice(0, 200))
    after = sky(corrected, slice(w - 200, w)) - sky(corrected, slice(0, 200))
    assert abs(after) < 0.3 * abs(before)


@pytest.mark.aimodels
@pytest.mark.realfiles
def test_real_gpu_and_cpu_providers_agree():
    path = _real("graxpert-denoise")
    if not any(p in rt.available_providers() for p in rt.GPU_PROVIDERS):
        pytest.skip("no GPU execution provider")
    x = _m31_crop()[:384, :384]
    valid = np.ones(x.shape[:2], bool)
    gpu, _ = ai_denoise(x, valid, 1.0, rt.Runner(path, "auto"))
    cpu, _ = ai_denoise(x, valid, 1.0, rt.Runner(path, "cpu"))
    mad = np.median(np.abs(x - np.median(x)))
    assert np.abs(gpu - cpu).max() < 0.05 * mad
