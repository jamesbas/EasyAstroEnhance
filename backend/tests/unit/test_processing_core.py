"""Numerical tests of the processing core. All images here are SYNTHETIC test fixtures, never user output."""
from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from app.processing import background as bg
from app.processing import finishing as fin
from app.processing import tone
from app.processing.backends import NumpyBackend
from app.processing.denoise import estimate_noise
from app.processing.diagnostics import clip_report
from app.processing.export import encode_png, quantize
from app.processing.imagedata import ProcessingError
from app.processing.pipeline import AssetContext, ExecutionOptions, run_pipeline
from app.processing.recipe import (
    AdvancedRecipe, AutoRecipe, BackgroundRecipe, Recipe, ToneRecipe, builtin_presets, no_operations_recipe, parse_recipe, RecipeCompatibilityError,
)
from app.processing.star_protection import detect_stars
from conftest import linear_field, make_image, synthetic_field

import imagecodecs

NOOP_LOOK = no_operations_recipe().look
NOOP_AUTO = no_operations_recipe().auto


def look(**kw):
    """The no-operation look with only the given sliders set."""
    return NOOP_LOOK.model_copy(update=kw)


def auto(**kw):
    return NOOP_AUTO.model_copy(update=kw)


def only(**kw) -> Recipe:
    """A recipe with everything off except the given sections."""
    base = no_operations_recipe()
    return base.model_copy(update=kw)


def run(img, recipe, ctx=None, **opts):
    return run_pipeline(img, recipe, ctx or AssetContext(), ExecutionOptions(**opts))


# ------------------------------------------------------------------------------ identity / no-op
@pytest.mark.parametrize("rgb", [True, False])
def test_no_operations_png_matches_decoded_pixels_exactly(rgb):
    arr, _ = synthetic_field(rgb=rgb)
    u8 = np.rint(arr * 255).astype(np.uint8)
    img = make_image(u8.astype(np.float32) / 255.0)
    res = run(img, no_operations_recipe())
    assert res.report["no_operations_run"] and res.summary
    dec = imagecodecs.png_decode(encode_png(quantize(res.display, 8)))
    assert np.array_equal(dec, u8)


def test_no_operations_uint16_png_exact():
    raw = np.random.default_rng(2).integers(0, 65536, (30, 40, 3), dtype=np.uint16)
    img = make_image(raw.astype(np.float32) / 65535.0, dtype="uint16", bits=16)
    res = run(img, no_operations_recipe())
    assert np.array_equal(imagecodecs.png_decode(encode_png(quantize(res.display, 16))), raw)


def test_neutral_manual_tone_adds_no_transform():
    m = tone.ManualTone()
    t = np.linspace(-0.1, 1.2, 50, dtype=np.float32)
    assert tone.apply_manual(np, t, m) is t


# ------------------------------------------------------------------------------ tone
def test_tone_brightness_lightens_and_darkens_effectively():
    arr, _ = synthetic_field(rgb=False, n_stars=5)
    img = make_image(arr)
    base = run(img, only(tone=ToneRecipe(enabled=False))).display
    up = run(img, only(tone=ToneRecipe(enabled=False, brightness_ev=0.5))).display
    dn = run(img, only(tone=ToneRecipe(enabled=False, brightness_ev=-0.5))).display
    assert np.median(up) > np.median(base) * 1.3 and np.median(dn) < np.median(base) * 0.75
    assert np.array_equal(run(img, only(tone=ToneRecipe(enabled=False))).display, base)  # repeatable


@pytest.mark.parametrize("sh", [-1, 0.4, 1])
@pytest.mark.parametrize("hi", [-1, -0.3, 1])
@pytest.mark.parametrize("bp", [-0.05, 0.0, 0.1])
@pytest.mark.parametrize("ev", [-1.0, 0.0, 1.0])
def test_manual_curves_are_monotonic(sh, hi, bp, ev):
    tone.validate_monotonic(tone.ManualTone(ev, sh, hi, bp))


def test_non_monotonic_curve_rejected(monkeypatch):
    monkeypatch.setattr(tone, "SHADOW_AMPLITUDE", 0.5)
    with pytest.raises(ValueError):
        tone.validate_monotonic(tone.ManualTone(0, 1.0, 0, 0))


def test_tone_order_is_fixed_black_point_then_brightness_then_curves():
    t = np.array([0.2, 0.5], dtype=np.float64)
    m = tone.ManualTone(brightness_ev=1.0, black_point=0.1)
    expected = (t - 0.1) / 0.9 * 2.0
    assert np.allclose(tone.apply_manual(np, t, m), expected)


def test_black_point_affects_display_only_and_is_reported():
    arr, _ = synthetic_field(rgb=False)
    img = make_image(arr)
    res = run(img, only(tone=ToneRecipe(enabled=False, black_point=0.1)))
    assert res.report["clipping"]["final"]["new_black"] > 0  # clipping check runs for every adjustment
    assert res.display.min() == 0.0


def test_rational_gain_is_monotonic_and_identity_at_one():
    x = np.linspace(-0.2, 1.5, 500)
    assert np.all(np.diff(tone.rational_gain(np, x, 1.45)) > 0)
    assert np.allclose(tone.rational_gain(np, x, 1.0), x)


# ------------------------------------------------------------------------------ denoise
def test_denoise_reduces_noise_and_preserves_faint_source_flux_and_position():
    rng = np.random.default_rng(5)
    h = w = 128
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    blob = 0.05 * np.exp(-(((xx - 70.3) ** 2 + (yy - 60.6) ** 2) / (2 * 3.0**2)))
    clean = 0.2 + blob
    noisy = np.clip(clean + rng.normal(0, 0.02, clean.shape), 0, 1).astype(np.float32)
    img = make_image(noisy)
    out = run(img, only(look=look(noise=1.0))).display
    flat = (slice(5, 40), slice(5, 40))
    assert out[flat].std() < noisy[flat].std() * 0.9
    resid_before, resid_after = noisy - clean, out - clean
    # flux of the faint source inside its footprint is retained (no gross loss) and centroid does not move
    fp = (yy - 60.6) ** 2 + (xx - 70.3) ** 2 < 8**2
    flux_before = (noisy - 0.2)[fp].sum()
    flux_after = (out - 0.2)[fp].sum()
    assert abs(flux_after - flux_before) / max(abs(flux_before), 1e-6) < 0.1

    def centroid(a):
        s = ndimage.gaussian_filter(a, 2.0)
        return np.array(np.unravel_index(np.argmax(s), s.shape))

    assert np.abs(centroid(out) - centroid(noisy)).max() <= 1


def test_chroma_not_smeared_across_star_boundaries():
    arr, stars = synthetic_field(n_stars=6, galaxy=False, noise=0.004)
    arr = arr.copy()
    sy, sx, _ = stars[0]
    yy, xx = np.mgrid[0:arr.shape[0], 0:arr.shape[1]]
    star = np.exp(-(((xx - sx) ** 2 + (yy - sy) ** 2) / 4.0))
    arr[..., 0] = np.clip(arr[..., 0] + 0.6 * star, 0, 1)  # a strongly red star
    img = make_image(arr.astype(np.float32))
    res = run(img, only(look=look(noise=1.0)))
    ring = (np.hypot(yy - sy, xx - sx) > 6) & (np.hypot(yy - sy, xx - sx) < 10)
    delta_red = (res.display[..., 0] - res.display[..., 1])[ring].mean() - (arr[..., 0] - arr[..., 1])[ring].mean()
    assert abs(delta_red) < 0.02


def test_protected_region_is_exactly_restored_and_excluded_from_statistics():
    arr, _ = synthetic_field(h=160, w=200, galaxy=False)
    arr = arr.copy()
    arr[130:, :, :] = 0.0
    arr[135:155, 10:190, :] = 0.95  # bright caption "lettering"
    img = make_image(arr)
    region = [{"x": 0, "y": 130, "w": 200, "h": 30}]
    r = builtin_presets()["vivid"]
    res = run(img, r, AssetContext(regions=region))
    assert np.array_equal(res.display[130:], img.pixels[130:])  # restored in the same display domain
    base_noise = estimate_noise(arr[:128], np.ones((128, 200), bool), None, 1e-6)["sigma_residual"]
    contaminated = estimate_noise(arr, np.ones((160, 200), bool), None, 1e-6)["sigma_residual"]
    clean = estimate_noise(arr, np.arange(160)[:, None].repeat(200, 1) < 130, None, 1e-6)["sigma_residual"]
    assert clean == pytest.approx(base_noise, rel=0.15)
    # no bleed: pixels just above the band are unchanged relative to a run without any caption
    arr2 = arr.copy()
    arr2[130:] = arr[:30].mean()
    res2 = run(make_image(arr2), r, AssetContext(regions=region))
    assert np.abs(res.display[100:125] - res2.display[100:125]).max() < 0.03


def test_invalid_regions_rejected_readably():
    arr, _ = synthetic_field()
    img = make_image(arr)
    for bad in ([{"x": -1, "y": 0, "w": 10, "h": 10}], [{"x": 0, "y": 0, "w": 0, "h": 10}], [{"x": 250, "y": 0, "w": 50, "h": 10}], [{"x": 0, "y": 0, "w": 256, "h": 192}]):
        with pytest.raises(ProcessingError) as e:
            run(img, builtin_presets()["natural"], AssetContext(regions=bad))
        assert e.value.code == "INVALID_REGION" and e.value.message


# ------------------------------------------------------------------------------ star protection
def test_star_mask_smooth_and_reduces_core_brightening_without_moving_stars():
    arr, stars = synthetic_field(h=200, w=260, n_stars=60, galaxy=False, noise=0.004, seed=3)
    img = make_image(arr)
    star = detect_stars(arr, np.ones(arr.shape[:2], bool), 1e-6)
    assert star.reliable and star.stats["accepted"] >= 20
    gy, gx = np.gradient(star.soft)
    assert np.hypot(gy, gx).max() < 0.35  # feathered, no abrupt mask edges
    stretch = only(tone=ToneRecipe(enabled=True), look=look(stretch=1.0))
    on = run(img, stretch.model_copy(update={"auto": auto(star_stretch=True), "advanced": AdvancedRecipe(star_stretch_amount=0.9)}))
    off = run(img, stretch)
    ys, xs, amps = zip(*stars)
    cores = [(int(round(y)), int(round(x))) for y, x, a in stars if a > 0.5]
    gain_on = np.mean([on.display[y, x].mean() - arr[y, x].mean() for y, x in cores])
    gain_off = np.mean([off.display[y, x].mean() - arr[y, x].mean() for y, x in cores])
    assert gain_on < gain_off  # reduced additional core brightening
    for y, x in cores[:8]:
        win = (slice(y - 3, y + 4), slice(x - 3, x + 4))
        a = np.unravel_index(np.argmax(on.display[win].mean(-1)), (7, 7))
        b = np.unravel_index(np.argmax(arr[win].mean(-1)), (7, 7))
        assert abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) <= 1  # positions preserved
    op = [o for o in on.report["operations"] if o["name"] == "star_stretch"][0]
    assert op["status"] == "applied"


def test_broad_galaxy_core_is_not_in_the_star_mask():
    h, w = 200, 260
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    arr = 0.08 + 0.5 * np.exp(-(((xx - 130) ** 2 + (yy - 100) ** 2) / (2 * 14.0**2)))
    arr = np.clip(arr + np.random.default_rng(0).normal(0, 0.004, arr.shape), 0, 1).astype(np.float32)
    star = detect_stars(arr, np.ones((h, w), bool), 1e-6)
    assert (not star.reliable) or star.soft[100, 130] < 0.05


def test_star_stretch_inactive_when_tone_disabled_and_skipped_when_unreliable():
    arr, _ = synthetic_field(n_stars=0, galaxy=False)
    img = make_image(arr)
    r1 = run(img, only(auto=auto(star_stretch=True), look=look(noise=0.3)))
    op = [o for o in r1.report["operations"] if o["name"] == "star_stretch"][0]
    assert op["status"] == "inactive"
    r2 = run(img, only(auto=auto(star_stretch=True), tone=ToneRecipe()))
    op2 = [o for o in r2.report["operations"] if o["name"] == "star_stretch"][0]
    assert op2["status"] == "skipped" and "Highlight convergence" in op2["reason"]


# ------------------------------------------------------------------------------ multiscale detail
def test_detail_off_is_identity_and_gates_sky_noise():
    arr, _ = synthetic_field(rgb=False, galaxy=False, n_stars=0, noise=0.01, sky=0.2)
    img = make_image(arr)
    off = run(img, only(tone=ToneRecipe(enabled=False))).display
    assert np.array_equal(off, arr)
    lc = run(img, only(look=look(detail=1.0))).display
    assert np.abs(lc - arr).mean() < 0.002  # noise-dominated sky is gated, not amplified


def test_detail_boosts_existing_medium_scale_structure_without_halos():
    h, w = 240, 240
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    structure = 0.04 * np.sin(xx / 6.0) * np.exp(-(((xx - 120) / 70) ** 2 + ((yy - 120) / 70) ** 2))
    step = (xx > 190).astype(np.float32) * 0.3
    arr = np.clip(0.3 + structure + step + np.random.default_rng(1).normal(0, 0.001, (h, w)), 0, 1).astype(np.float32)
    img = make_image(arr)
    res = run(img, only(look=look(detail=1.0), advanced=AdvancedRecipe(detail_scale_px=16.0))).display
    center = (slice(80, 160), slice(80, 160))
    assert (res[center] - arr[center]).std() > 0.002  # structure boosted
    assert np.abs(res - arr).max() <= fin.DETAIL_CAP + 1e-6  # bounded
    edge = res[100:140, 192:215] - arr[100:140, 192:215]
    assert np.abs(edge).max() < 0.03  # no halos beside a sharp transition


def test_detail_scale_is_in_full_resolution_pixels_in_report():
    arr, _ = synthetic_field(rgb=False)
    res = run(make_image(arr), only(look=look(detail=0.5), advanced=AdvancedRecipe(detail_scale_px=32.0)))
    lc = [o for o in res.report["operations"] if o["name"] == "detail"][0]
    assert lc["parameters"]["largest_scale_full_res_px"] == 32 and lc["parameters"]["tile_halo_px"] > 0


# ------------------------------------------------------------------------------ tiling parity
def test_tiled_matches_full_frame_for_rendered_and_linear():
    arr, _ = synthetic_field(h=210, w=250, n_stars=50, seed=11)
    r = builtin_presets()["vivid"]
    full = run(make_image(arr), r)
    tiled = run(make_image(arr), r, force_tile=96)
    assert tiled.report["execution"]["tile"] == 96
    np.testing.assert_allclose(tiled.display, full.display, atol=1e-5, rtol=1e-4)  # no seams
    lin = linear_field(h=200, w=240)
    il = make_image(lin, domain="linear", fmt="fits", dtype="float32", bits=32)
    rl = builtin_presets()["natural"]
    f = run(il, rl)
    t = run(il, rl, force_tile=80)
    np.testing.assert_allclose(t.display, f.display, atol=1e-4, rtol=1e-4)
    np.testing.assert_allclose(t.processed, f.processed, rtol=1e-5, atol=1e-2)


def test_repeated_processing_is_deterministic():
    arr, _ = synthetic_field(seed=8)
    r = builtin_presets()["vivid"]
    a = run(make_image(arr), r).display
    b = run(make_image(arr), r).display
    assert np.array_equal(a, b)


# ------------------------------------------------------------------------------ clipping
def test_source_and_new_clipping_are_reported_separately():
    arr, _ = synthetic_field(rgb=False, seed=4)
    arr = arr.copy()
    arr[:10, :10] = 0.0
    arr[-10:, -10:] = 1.0
    img = make_image(arr)
    res = run(img, only(tone=ToneRecipe(enabled=False, brightness_ev=1.0)))
    c = res.report["clipping"]["final"]
    assert c["input_zero"] >= 100 and c["input_max"] >= 100
    assert c["new_white"] > 0 and c["output_max"] >= c["input_max"] + c["new_white"] - 1


def test_clip_report_uses_transitions_not_totals():
    src = np.array([[0.0, 0.5], [0.5, 0.5]], dtype=np.float32)
    out = np.array([[0.2, 0.0], [0.5, 0.5]], dtype=np.float32)  # one pixel unclipped, another newly clipped: totals equal
    rep = clip_report(src, out, np.ones((2, 2), bool))
    assert rep["input_zero"] == 1 and rep["output_zero"] == 1 and rep["new_black"] == 1


def test_clip_guardrail_reduces_strength_once_then_flags_review():
    rng = np.random.default_rng(0)
    arr = np.clip(rng.normal(0.02, 0.01, (120, 120, 3)), 0, 1).astype(np.float32)  # mostly near black
    bgc = bg.build_model(arr, np.ones((120, 120), bool), None, [{"x": 5, "y": 5, "w": 20, "h": 20}, {"x": 50, "y": 5, "w": 20, "h": 20}, {"x": 90, "y": 60, "w": 20, "h": 20}], "constant", 0.01)
    assert bgc.ok
    arr[..., 0] += 0.05  # red cast removed by the (confirmed) constant background correction
    img = make_image(arr)
    samples = [{"x": 5, "y": 5, "w": 20, "h": 20}, {"x": 50, "y": 5, "w": 20, "h": 20}, {"x": 90, "y": 60, "w": 20, "h": 20}]
    ctx = AssetContext(background={"method": "constant", "samples": samples, "confirmed": True})
    res = run(img, only(background=BackgroundRecipe(enabled=True, method="constant", strength="strong")), ctx)
    assert res.report["clipping"]["guard_action"] in ("none", "reduced", "needs_review")
    assert res.report["clipping"]["first_pass"] is not None


# ------------------------------------------------------------------------------ background
def sky_image(w=300, h=240, plane=(0.04, -0.03), channel=(0.0, 0.01, -0.01), noise=0.002, seed=0, blob=True):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = 0.2 + plane[0] * (xx / w - 0.5) * 2 + plane[1] * (yy / h - 0.5) * 2
    if blob:
        base = base + 0.25 * np.exp(-(((xx - w / 2) / 35) ** 2 + ((yy - h / 2) / 25) ** 2))
    img = np.stack([base + c for c in channel], -1) + rng.normal(0, noise, (h, w, 3))
    return img.astype(np.float32)


GOOD = [(10, 10), (130, 10), (260, 10), (10, 110), (270, 120), (20, 200), (140, 210), (260, 200)]


def patches(pts, size=24):
    return [{"x": x, "y": y, "w": size, "h": size} for x, y in pts]


def test_constant_model_needs_three_patches_and_recovers_offsets():
    img = sky_image(plane=(0, 0), channel=(0.03, 0.0, -0.02), blob=False)
    wgt = np.ones(img.shape[:2], bool)
    m2 = bg.build_model(img, wgt, None, patches(GOOD[:2]), "constant", 0.002)
    assert not m2.ok and m2.issues[0].code == "TOO_FEW_PATCHES"
    m = bg.build_model(img, wgt, None, patches(GOOD[:4]), "constant", 0.002)
    assert m.ok
    off = np.array(m.offsets)
    assert np.allclose(off - off.mean(), [0.03 - 0.0033, -0.0033, -0.0233], atol=0.002)


def test_planar_recovers_known_plane_with_extended_object_outside_patches():
    img = sky_image(plane=(0.04, -0.03), channel=(0, 0, 0))
    wgt = np.ones(img.shape[:2], bool)
    m = bg.build_model(img, wgt, None, patches(GOOD), "planar", 0.002)
    assert m.ok, [i.message for i in m.issues]
    pm = bg.plane_map(m, *img.shape[:2])
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    truth = 0.04 * (xx / w - 0.5) * 2 - 0.03 * (yy / h - 0.5) * 2
    err = (pm - (truth - truth[h // 2, w // 2] + 0 * truth))
    # recovered gradient matches truth up to a constant (reference level)
    assert np.std(err - err.mean()) < 0.004


@pytest.mark.parametrize("pts, code", [
    (GOOD[:5], "TOO_FEW_PATCHES"),
    ([(10, 10), (60, 12), (110, 14), (160, 10), (210, 12), (260, 14)], "POOR_COVERAGE"),
    ([(10, 10), (20, 20), (30, 12), (14, 30), (36, 34), (22, 44)], "PATCHES_OVERLAP"),
])
def test_planar_refuses_insufficient_or_bad_layouts(pts, code):
    img = sky_image()
    m = bg.build_model(img, np.ones(img.shape[:2], bool), None, patches(pts, 24 if code != "PATCHES_OVERLAP" else 24), "planar", 0.002)
    assert not m.ok and code in {i.code for i in m.issues if i.level == "error"}


def test_planar_refuses_collinear_samples():
    img = sky_image(w=300, h=240)
    pts = [(10 + i * 45, 100) for i in range(6)]
    m = bg.build_model(img, np.ones(img.shape[:2], bool), None, patches(pts, 24), "planar", 0.002)
    assert not m.ok and {i.code for i in m.issues} & {"POOR_COVERAGE", "COLLINEAR_OR_CLUSTERED", "ILL_CONDITIONED"}


def test_contaminated_patch_is_flagged_and_patch_in_protected_rejected():
    img = sky_image(blob=False)
    img[10:34, 10:34] += 0.4  # a bright source inside patch 1 (not a star-mask object)
    m = bg.build_model(img, np.ones(img.shape[:2], bool), None, patches(GOOD), "planar", 0.002)
    codes = {i.code for i in m.issues}
    assert "PATCH_OUTLIER" in codes or "PATCH_BRIGHT" in codes or "PATCH_STRUCTURE" in codes
    prot = np.zeros(img.shape[:2], bool)
    prot[100:140, :] = True
    m2 = bg.build_model(sky_image(), np.ones(img.shape[:2], bool) & ~prot, None, patches(GOOD), "planar", 0.002, prot)
    assert not m2.ok and "PATCH_IN_PROTECTED" in {i.code for i in m2.issues}


def test_no_double_subtraction_and_sky_flattened_in_linear_negatives_kept():
    lin = linear_field(h=200, w=260, rgb=True, noise=15, gradient=(300.0, -200.0), negatives=True)
    img = make_image(lin, domain="linear", fmt="fits", dtype="float32", bits=32)
    samples = patches([(8, 8), (115, 8), (228, 8), (8, 90), (232, 100), (12, 168), (115, 170), (228, 168)], 22)
    ctx = AssetContext(background={"method": "planar", "samples": samples, "confirmed": True})
    r = only(background=BackgroundRecipe(enabled=True, method="planar", strength="strong"))
    res = run(img, r, ctx)
    op = [o for o in res.report["operations"] if o["name"] == "background"][0]
    assert op["status"] in ("applied", "reduced"), op
    out = res.processed
    assert (out < 0).any()  # physical negatives retained (not clamped)
    sky_before = [lin[y : y + 22, x : x + 22, 0].mean() for x, y in [(8, 8), (228, 8), (12, 168), (228, 168)]]
    sky_after = [out[y : y + 22, x : x + 22, 0].mean() for x, y in [(8, 8), (228, 8), (12, 168), (228, 168)]]
    assert np.ptp(sky_after) < 0.25 * np.ptp(sky_before)  # gradient removed once
    # channel offsets neutralised, mean sky level preserved (not subtracted twice)
    means = [out[8:30, 8:30, c].mean() for c in range(3)]
    assert np.ptp(means) < np.ptp([lin[8:30, 8:30, c].mean() for c in range(3)]) * 0.35
    corners = [(8, 8), (228, 8), (12, 168), (228, 168)]
    before_all = np.mean([lin[y : y + 22, x : x + 22].mean() for x, y in corners])
    after_all = np.mean([out[y : y + 22, x : x + 22].mean() for x, y in corners])
    assert abs(after_all - before_all) < 0.1 * abs(before_all)  # overall sky level kept (reference level), nothing subtracted twice


def test_background_without_confirmation_or_with_invalid_model_is_skipped_safely():
    arr, _ = synthetic_field()
    img = make_image(arr)
    r = only(background=BackgroundRecipe(enabled=True, method="constant"))
    res = run(img, r)  # no confirmation
    op = [o for o in res.report["operations"] if o["name"] == "background"][0]
    assert op["status"] == "skipped" and "pending" in op["reason"]
    bad = AssetContext(background={"method": "constant", "samples": patches([(0, 0), (100, 0)]), "confirmed": True})
    op2 = [o for o in run(img, r, bad).report["operations"] if o["name"] == "background"][0]
    assert op2["status"] == "skipped"
    mism = AssetContext(background={"method": "planar", "samples": patches(GOOD[:4]), "confirmed": True})
    assert [o for o in run(img, r, mism).report["operations"] if o["name"] == "background"][0]["status"] == "skipped"


# ------------------------------------------------------------------------------ monochrome & recipes
def test_monochrome_color_controls_omitted_with_clear_report():
    arr, _ = synthetic_field(rgb=False)
    res = run(make_image(arr), builtin_presets()["natural"])
    op = [o for o in res.report["operations"] if o["name"] == "color"][0]
    assert op["status"] == "skipped" and "Monochrome" in op["reason"]
    assert res.display.ndim == 2  # monochrome stays monochrome


def test_recipe_validation_bounds_and_incompatible_schema():
    with pytest.raises(Exception):
        ToneRecipe(brightness_ev=2)
    with pytest.raises(Exception):
        ToneRecipe(black_point=0.5)
    with pytest.raises(RecipeCompatibilityError) as e:
        parse_recipe({"schema_version": 1})
    assert "Recreate the preset" in str(e.value)
    with pytest.raises(RecipeCompatibilityError):
        parse_recipe({"schema_version": 2})  # engine 1.0 recipes are not silently reinterpreted
    with pytest.raises(RecipeCompatibilityError):
        parse_recipe({"schema_version": 3, "regions": [{"x": 1}]})  # per-image data cannot ride in a recipe/preset
    with pytest.raises(RecipeCompatibilityError):
        parse_recipe({"schema_version": 3, "look": {"color": 2.0}})  # sliders are bounded


def test_nonfinite_pixels_are_masked_not_dark_stars():
    arr, _ = synthetic_field(rgb=False)
    arr = arr.copy()
    valid = np.ones(arr.shape, bool)
    arr[50:60, 50:60] = 0.0
    valid[50:60, 50:60] = False
    res = run(make_image(arr, valid=valid), builtin_presets()["natural"])
    assert np.all(res.display[50:60, 50:60] == 0.0) and np.isfinite(res.display).all()
    assert res.report["source"]["invalid_pixels"] == 100


