"""Engine 1.1 (one-button Enhance) behavior. All images here are SYNTHETIC test fixtures, never user output."""
from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits
from scipy import ndimage

from app.processing import finishing as fin
from app.processing import linear_prep as lp
from app.processing import wavelets
from app.processing.pipeline import AssetContext, ExecutionOptions, run_pipeline
from app.processing.recipe import (
    BUILTIN_PRESET_NAMES, AdvancedRecipe, LookRecipe, ToneRecipe, builtin_presets, no_operations_recipe,
)
from app.processing.stretch import apply_stretch, hyperbolic, mtf, solve_stretch
from conftest import make_image, synthetic_field

NOOP = no_operations_recipe()


def op(res, name):
    return next(o for o in res.report["operations"] if o["name"] == name)


def run(img, recipe, ctx=None, **kw):
    return run_pipeline(img, recipe, ctx or AssetContext(), ExecutionOptions(**kw))


def seestar_like(h=240, w=300, seed=0, cast=(10.0, 25.0, 0.0), gradient=0.0, star_colors=None, n_stars=70, galaxy=400.0, sat_stars=3):
    """SYNTHETIC Seestar-like linear stack: 1536 ADU pedestal, sky ~1600, per-channel cast, noise, a galaxy and stars
    (a few saturated at 65535)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    sky = 1600.0 + gradient * ((xx / w - 0.5) + 0.6 * (yy / h - 0.5) ** 2)
    gal = galaxy * np.exp(-(((xx - w * 0.5) / 40) ** 2 + ((yy - h * 0.5) / 22) ** 2))
    planes = []
    star_list = [(rng.uniform(10, h - 10), rng.uniform(10, w - 10), rng.uniform(400, 9000), rng.uniform(1.1, 1.6)) for _ in range(n_stars)]
    for i in range(sat_stars):
        star_list[i] = (star_list[i][0], star_list[i][1], 200000.0, 1.5)
    colors = star_colors or (1.0, 1.0, 1.0)
    for c in range(3):
        p = sky + cast[c] + gal * (1.05, 1.0, 0.9)[c]
        for sy, sx, amp, sg in star_list:
            p = p + amp * colors[c] * np.exp(-(((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * sg**2)))
        planes.append(p)
    arr = np.stack(planes, -1) + rng.normal(0, 12.0, (h, w, 3))
    return np.clip(arr, 1536, 65535).astype(np.float32), star_list


def lin(arr):
    return make_image(arr, domain="linear", fmt="fits", dtype="uint16", bits=16)


# ------------------------------------------------------------------------------ orientation
def test_seestar_fits_rows_are_kept_as_stored_and_exported_symmetrically(tmp_path):
    from app.processing.export import write_fits
    from app.processing.readers import inspect_file, read_image, sha256_file

    data = np.arange(3 * 20 * 30, dtype=np.uint16).reshape(3, 20, 30)
    p = tmp_path / "Stacked_1_M 31.fit"
    hdu = fits.PrimaryHDU(data)
    hdu.header["CREATOR"] = "ZWO Seestar S30"
    hdu.header["CTYPE3"] = "RGB"
    hdu.writeto(p)
    img = read_image(p, sha256_file(p), 10**9, {"state": "linear"}, inspect_file(p, 10**9))
    assert np.array_equal(img.pixels[..., 0], data[0].astype(np.float32)) and not img.flip_rows_on_export
    assert "Seestar" in img.orientation_transform
    out = tmp_path / "o.fits"
    write_fits(out, img, img.pixels, "processed-linear", "x")
    with fits.open(out) as hd:
        assert np.array_equal(hd[0].data, data.astype(np.float32))
    other = tmp_path / "generic.fits"
    fits.PrimaryHDU(data[0]).writeto(other)
    g = read_image(other, sha256_file(other), 10**9, {"state": "linear"}, inspect_file(other, 10**9))
    assert np.array_equal(g.pixels, data[0][::-1].astype(np.float32))  # FITS convention still applies to other files


# ------------------------------------------------------------------------------ linear preparation
def test_one_button_neutralizes_sky_and_lands_on_target_without_guardrail():
    arr, _ = seestar_like(cast=(10.0, 30.0, -5.0))
    res = run(lin(arr), builtin_presets()["natural"])
    assert op(res, "neutralize")["status"] == "applied"
    sky = res.display[:40, :40].reshape(-1, 3)
    med = np.median(sky, axis=0)
    assert np.ptp(med) < 0.01  # neutral display sky
    assert np.mean(med) == pytest.approx(0.12, abs=0.02)
    proc_sky = np.median(res.processed[:40, :40].reshape(-1, 3), axis=0)
    assert np.ptp(proc_sky) < 3.0  # processed-linear sky equalized (source units)
    assert res.report["clipping"]["guard_action"] == "none"
    assert res.report["clipping"]["final"]["new_black_fraction"] < 0.001
    base_sky = np.median(res.baseline[:40, :40].reshape(-1, 3), axis=0)
    assert np.ptp(base_sky) > 0.02  # the original keeps the cast so the comparison is honest


def test_white_balance_is_bounded_and_skips_without_star_reference():
    arr, _ = seestar_like(star_colors=(1.6, 1.0, 0.7), n_stars=90, seed=3)
    res = run(lin(arr), builtin_presets()["natural"])
    wb = res.report["linear_preparation"]["white_balance"]
    assert wb["ok"] and wb["stars_used"] >= 15
    r, g, b = wb["factors_rgb"]
    assert g == 1.0 and 0.8 - 1e-6 <= r < 0.95 and 1.05 < b <= 1.25 + 1e-6  # corrects toward neutral stars, within the limit
    assert wb["clamped"]
    few, _ = seestar_like(n_stars=6, seed=4, sat_stars=0)
    res2 = run(lin(few), builtin_presets()["natural"])
    w2 = op(res2, "white_balance")
    assert w2["status"] == "skipped" and w2["reason"]


def test_gradient_is_removed_and_skipped_when_the_target_fills_the_frame():
    arr, _ = seestar_like(gradient=120.0, galaxy=150.0, seed=5)
    res = run(lin(arr), builtin_presets()["natural"])
    g = op(res, "gradient")
    assert g["status"] == "applied"
    before = arr[..., 1]
    after = res.processed[..., 1]
    corners = [(slice(5, 35), slice(5, 35)), (slice(5, 35), slice(-35, -5)), (slice(-35, -5), slice(5, 35)), (slice(-35, -5), slice(-35, -5))]
    assert np.ptp([np.median(after[c]) for c in corners]) < 0.35 * np.ptp([np.median(before[c]) for c in corners])
    flat, _ = seestar_like(galaxy=0.0, seed=6)
    assert op(run(lin(flat), builtin_presets()["natural"]), "gradient")["status"] == "skipped"  # nothing significant to remove
    h, w = 200, 260
    yy, xx = np.mgrid[0:h, 0:w]
    filling = np.stack([1600 + 600 * np.exp(-(((xx - 130) / 160) ** 2 + ((yy - 100) / 120) ** 2)) * k for k in (1.0, 0.9, 0.8)], -1)
    filling = (filling + np.random.default_rng(0).normal(0, 12, filling.shape)).astype(np.float32)
    model = lp.fit_gradient(filling / 65535.0, np.ones((h, w), bool), None, 2, 12 / 65535.0)
    assert not model.ok or model.relative_amplitude < 50  # never fits the target itself as a huge "gradient"


def test_edge_mask_finds_constant_fill_from_field_rotation():
    arr, _ = seestar_like(seed=7)
    arr[:, :25] = 1536.0  # low-coverage wedge filled with the pedestal
    mask, info = lp.edge_mask(arr / 65535.0, np.ones(arr.shape[:2], bool))
    assert mask[:, :20].mean() > 0.9 and mask[:, 60:].mean() < 0.01 and info["fraction"] > 0.05


# ------------------------------------------------------------------------------ stretch
def test_stretch_is_monotonic_lands_sky_on_target_and_slider_shifts_d():
    L = np.linspace(0, 1, 2001)
    assert np.all(np.diff(hyperbolic(np, L, 300.0, 6.0)) > 0)
    sp = solve_stretch(0.03, 0.0005, 0.2, 1.0, 0.12, protect_cores=True, amount=0.0)
    ys = apply_stretch(np, np.array([[0.03]], np.float32), sp)
    assert float(ys[0, 0]) == pytest.approx(0.12, abs=0.003)
    assert sp.hi_display == pytest.approx(0.88, abs=0.01)
    deeper = solve_stretch(0.03, 0.0005, 0.2, 1.0, 0.12, protect_cores=True, amount=1.0)
    assert deeper.D == pytest.approx(sp.D * 10**0.75, rel=1e-6)
    m = 0.2
    assert float(mtf(np, m, np.float64(m))) == pytest.approx(0.5)


def test_saturated_cores_converge_to_white_and_stars_have_no_dark_rings():
    arr, stars = seestar_like(seed=8)
    res = run(lin(arr), builtin_presets()["natural"])
    y = res.display
    sy, sx = int(round(stars[0][0])), int(round(stars[0][1]))  # saturated star
    core = y[sy, sx]
    assert core.min() > 0.9 and np.ptp(core) < 0.05  # white, not a colored blob or a grey disc
    L = y.mean(-1)
    yy, xx = np.mgrid[0:L.shape[0], 0:L.shape[1]]
    for sy_f, sx_f, amp, _ in stars[:12]:
        r = np.hypot(yy - sy_f, xx - sx_f)
        prof = [L[(r >= a) & (r < a + 1)].mean() for a in range(0, 6)]
        assert prof[0] >= max(prof[1:]) - 0.02  # the core is never darker than its surrounding ring


def test_guardrail_does_not_fire_on_a_seestar_like_stack_for_any_preset():
    arr, _ = seestar_like(seed=9)
    img = lin(arr)
    for pid, recipe in builtin_presets().items():
        res = run(img, recipe)
        assert res.report["clipping"]["guard_action"] == "none", (pid, res.report["clipping"]["first_pass"])


# ------------------------------------------------------------------------------ finishing
def test_green_removal_runs_only_when_green_remains():
    arr, _ = synthetic_field(seed=2)
    green = arr.copy()
    green[..., 1] = np.clip(green[..., 1] + 0.06, 0, 1)
    r = NOOP.model_copy(update={"auto": NOOP.auto.model_copy(update={"green_removal": True})})
    res = run(make_image(green), r)
    assert op(res, "green_removal")["status"] == "applied"
    g_excess = lambda a: np.median(a[..., 1] - 0.5 * (a[..., 0] + a[..., 2]))  # noqa: E731
    assert g_excess(res.display) < 0.25 * g_excess(green)
    neutral = np.repeat(arr.mean(-1, keepdims=True), 3, -1)
    assert op(run(make_image(neutral), r), "green_removal")["status"] == "skipped"


def test_pop_curve_is_monotonic_and_anchored():
    L = np.linspace(-0.1, 1.2, 4001)
    for a in (0.2, 0.5, 0.8):
        out = fin.pop_curve(np, L, 0.12, a)
        assert np.all(np.diff(out) >= -1e-12)
        assert np.allclose(out[L <= 0.12], L[L <= 0.12]) and np.allclose(out[L >= 1.0], L[L >= 1.0])
        mid = (L > 0.2) & (L < 0.5)
        assert np.all(out[mid] <= L[mid] + 1e-12)  # darker below the midpoint, brighter above (an S)


def test_hdr_compresses_a_bright_extended_core_and_keeps_its_structure():
    h, w = 260, 300
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    core = 0.95 * np.exp(-(((xx - 150) / 45) ** 2 + ((yy - 130) / 35) ** 2))
    texture = 0.03 * np.sin(xx / 3.0) * (core > 0.5)
    arr = np.clip(0.1 + core + texture + np.random.default_rng(0).normal(0, 0.003, (h, w)), 0, 1).astype(np.float32)
    rgb = np.stack([arr, arr * 0.97, arr * 0.93], -1)
    r = NOOP.model_copy(update={"tone": ToneRecipe(enabled=True), "look": LookRecipe(contrast=0, color=0, detail=0, noise=0, protect_cores=True)})
    on = run(make_image(rgb), r)
    off = run(make_image(rgb), r.model_copy(update={"look": r.look.model_copy(update={"protect_cores": False})}))
    assert op(on, "hdr")["status"] == "applied"
    c = (slice(120, 140), slice(140, 160))
    assert on.display[c].mean() < off.display[c].mean() - 0.02  # bright core compressed
    band = (slice(110, 150), slice(110, 190))
    assert (on.display[band].mean(-1) - ndimage.uniform_filter(on.display.mean(-1), 9)[band]).std() > 0.5 * (
        off.display[band].mean(-1) - ndimage.uniform_filter(off.display.mean(-1), 9)[band]).std()  # fine structure kept
    plain, _ = synthetic_field(seed=1, galaxy=False)
    assert op(run(make_image(plain), r), "hdr")["status"] == "skipped"


def test_deconvolution_is_opt_in_and_tightens_stars():
    rng = np.random.default_rng(0)
    h, w = 220, 260
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    img = np.full((h, w), 1600.0)
    pos = [(rng.uniform(15, h - 15), rng.uniform(15, w - 15)) for _ in range(60)]
    for sy, sx in pos:
        img += 3000 * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * 2.0**2))
    arr = np.stack([img] * 3, -1) + rng.normal(0, 5, (h, w, 3))
    arr = arr.astype(np.float32)
    base = NOOP.model_copy(update={"auto": NOOP.auto.model_copy(update={"neutralize": True})})
    off = run(lin(arr), base)
    on = run(lin(arr), base.model_copy(update={"advanced": AdvancedRecipe(deconvolution=True, deconvolution_iterations=15)}))
    d = op(on, "deconvolution")
    assert d["status"] == "applied" and 3.8 < d["parameters"]["psf"]["fwhm_px"] < 5.8  # Gaussian sigma 2 px = FWHM 4.7 px
    assert d["parameters"]["psf"]["model"] == "Moffat" and len(d["parameters"]["psf_zones"]) == 9
    assert op(off, "deconvolution")["status"] == "off"

    def peak_ratio(a):
        return np.mean([a[int(round(y)), int(round(x))].mean() for y, x in pos])

    assert peak_ratio(on.processed) > peak_ratio(off.processed) * 1.05  # sharper star peaks in the linear data


def test_denoise_preserves_isolated_dark_defects_without_spreading():
    arr, _ = seestar_like(seed=10, n_stars=30)
    arr[100:102, 120:122] = 1536.0  # cold pixels / stacking hole
    r = NOOP.model_copy(update={"look": NOOP.look.model_copy(update={"noise": 1.0})})
    res = run(lin(arr), r)
    ring = res.processed[96:106, 116:126].copy()
    ring[4:6, 4:6] = np.nan
    assert np.nanmin(ring) > 1600 - 6 * 12  # neighbors not dragged toward the defect


def test_wavelet_planes_reconstruct_exactly():
    a = np.random.default_rng(1).random((64, 80, 3)).astype(np.float64)
    planes, resid = wavelets.decompose(np, a, 5)
    np.testing.assert_allclose(sum(planes) + resid, a, atol=1e-12)


def test_builtin_presets_are_intent_only_and_named():
    presets = builtin_presets()
    assert set(presets) == set(BUILTIN_PRESET_NAMES) and "natural" in presets
    for pid, r in presets.items():
        d = r.model_dump()
        assert r.preset == pid and not any(k in d for k in ("regions", "samples", "frame", "factors"))
        assert r.advanced.deconvolution is False  # experimental sharpening is never on by default


# ------------------------------------------------------------------------------ real Seestar stacks (user files, read-only)
SEESTAR_DIR = __import__("pathlib").Path(__import__("os").environ.get("EAE_SEESTAR_DIR", r"D:\Seestar\MyWorks"))
SEESTAR_CASES = [
    ("M 31", "DSO_Stacked_416_M 31_20.0s_20261108_214740"),
    ("M 45", "Stacked_458_M 45_20.0s_IRCUT_20251213-005308"),
    ("M 42", "Stacked_77_M 42_30.0s_LP_20260309-222857"),
]


@pytest.mark.realfiles
@pytest.mark.parametrize("folder, stem", SEESTAR_CASES)
def test_real_seestar_stack_one_button_acceptance(folder, stem):
    from PIL import Image

    from app.processing.linear_prep import clipped_stats
    from app.processing.pipeline import prepare_linear_frame
    from app.processing.readers import inspect_file, read_image, sha256_file

    fit = SEESTAR_DIR / folder / f"{stem}.fit"
    jpg = SEESTAR_DIR / folder / f"{stem}.jpg"
    if not fit.exists():
        pytest.skip(f"real Seestar stack not present: {fit}")
    before = sha256_file(fit)
    img = read_image(fit, before, 10**9, {"state": "linear", "layout": "rgb_planes"}, inspect_file(fit, 10**9))
    res = run(img, builtin_presets()["natural"], AssetContext(frame=prepare_linear_frame(img).to_dict()), device="auto", gpu_available=False)
    y = res.display
    if jpg.exists():  # orientation matches the telescope's own JPG
        ref = np.asarray(Image.open(jpg).convert("L").resize((108, 192)), np.float32)
        ours = np.asarray(Image.fromarray((y.mean(-1) * 255).astype(np.uint8)).resize((108, 192)), np.float32)
        z = lambda a: (np.log1p(np.maximum(a - np.median(a), 0)) - np.log1p(np.maximum(a - np.median(a), 0)).mean())  # noqa: E731
        corr = float((z(ref) * z(ours)).mean() / (z(ref).std() * z(ours).std()))
        assert corr > 0.9, corr
    sky = [clipped_stats(y[..., c].ravel()[::7])[0] for c in range(3)]
    assert np.ptp(sky) < 0.01, sky  # neutral sky
    assert np.mean(sky) == pytest.approx(0.12, abs=0.02)  # Natural target
    clip = res.report["clipping"]
    assert clip["guard_action"] == "none" and clip["final"]["new_black_fraction"] < 0.001 and clip["final"]["new_white_fraction"] < 0.001
    assert sha256_file(fit) == before  # originals are never modified
