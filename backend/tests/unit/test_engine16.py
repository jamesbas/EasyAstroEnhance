"""Engine 1.6 stages: cosmetic correction, dual-band defaults, star color, star-fringe reduction, Auto preset, clean
frame and the linear-stage cache. All images here are SYNTHETIC test fixtures, never user output."""
from __future__ import annotations

import numpy as np

from app.processing import auto_preset, cosmetic, framing
from app.processing import finishing as fin
from app.processing.pipeline import AssetContext, ExecutionOptions, StageCache, run_pipeline
from app.processing.recipe import builtin_presets
from app.services import folders
from conftest import linear_field, make_image

CPU = ExecutionOptions(device="cpu")


def op(res, name):
    return next(o for o in res.report["operations"] if o["name"] == name)


def lin(arr, header=None):
    return make_image(arr, domain="linear", fmt="fits", dtype="float32", bits=32, header=header)


# ------------------------------------------------------------------------------ cosmetic correction
def _sky(h=64, w=64, seed=0):
    rng = np.random.default_rng(seed)
    return (0.05 + rng.normal(0, 0.002, (h, w, 3))).astype(np.float32)


def test_cosmetic_repairs_colored_hot_and_cold_pixels_but_never_a_white_spike():
    u = _sky()
    u[20, 20, 1] += 0.08  # a green-only hot photosite
    u[40, 12, :] -= 0.04  # a dead pixel in every channel
    u[30, 45, :] += 0.08  # a broadband one-pixel spike: an undersampled star, never touched
    weight = np.ones(u.shape[:2], bool)
    out, info = cosmetic.correct(u, weight)
    assert abs(out[20, 20, 1] - 0.05) < 0.01 and out[20, 20, 0] == u[20, 20, 0]
    assert abs(out[40, 12, 0] - 0.05) < 0.01
    assert np.array_equal(out[30, 45], u[30, 45])
    assert info["hot_colored"] == 1 and info["cold"] == 1
    changed = np.argwhere((out != u).any(axis=2))
    assert {tuple(p) for p in changed} == {(20, 20), (40, 12)}


def test_cosmetic_leaves_bright_structure_protected_pixels_and_mono_hot_pixels_alone():
    u = _sky()
    u[10:30, 10:30] += 0.3  # bright nebula: not faint background
    u[20, 20, 2] += 0.2
    weight = np.ones(u.shape[:2], bool)
    weight[50, 50] = False
    u[50, 50, 0] += 0.08  # protected (label region / invalid)
    out, _ = cosmetic.correct(u, weight)
    assert np.array_equal(out, u)
    mono = _sky()[..., 0].copy()
    mono[20, 20] += 0.08
    out_m, info_m = cosmetic.correct(mono, np.ones(mono.shape, bool))
    assert out_m[20, 20] == mono[20, 20] and info_m["hot_colored"] == 0


# ------------------------------------------------------------------------------ dual-band defaults (F1)
def test_dualband_stacks_skip_star_white_balance_and_green_removal_with_reasons():
    arr = linear_field(seed=3) / 65535.0
    arr[..., 1] *= 1.3  # strong green, as OIII + H-alpha through a color sensor
    rec = builtin_presets()["natural"]
    res = run_pipeline(lin(arr, {"FILTER": "LP", "INSTRUME": "Seestar S50"}), rec, AssetContext(), CPU)
    wb, scnr = op(res, "white_balance"), op(res, "green_removal")
    assert wb["status"] == "skipped" and "dual-band" in wb["reason"].lower()
    assert scnr["status"] == "skipped" and "dual-band" in scnr["reason"].lower()
    broad = run_pipeline(lin(arr, {"FILTER": "IRCUT"}), rec, AssetContext(), CPU)
    assert op(broad, "white_balance")["status"] == "applied"


# ------------------------------------------------------------------------------ star color and fringes
def _star_disc(h=48, w=48):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.exp(-((yy - 24) ** 2 + (xx - 24) ** 2) / 18.0).astype(np.float32)


def test_star_color_boosts_only_inside_the_star_mask_and_stays_in_range():
    disc = _star_disc()
    y = np.stack([0.1 + 0.5 * disc, 0.1 + 0.45 * disc, 0.1 + 0.35 * disc], -1).astype(np.float32)
    y[0, 0] = (0.12, 0.10, 0.08)  # colored sky, outside the mask
    soft = (disc > 0.2).astype(np.float32)
    out = fin.star_color(np, y, soft, 1.0)
    spread = lambda a: a.max(-1) - a.min(-1)  # noqa: E731
    assert spread(out)[24, 24] > spread(y)[24, 24] * 1.5
    assert np.allclose(out[0, 0], y[0, 0])
    assert out.min() >= 0 and out.max() <= 1
    lum = lambda a: fin.luminance(np, a)  # noqa: E731
    assert abs(float(lum(out)[24, 24]) - float(lum(y)[24, 24])) < 1e-4  # luminance kept


def _field_with_rings(ring_color, n=16, size=160):
    rng = np.random.default_rng(5)
    y = np.full((size, size, 3), 0.1, np.float32)
    hard = np.zeros((size, size), bool)
    yy, xx = np.mgrid[0:size, 0:size]
    for _ in range(n):
        cy, cx = rng.integers(14, size - 14, 2)
        d = np.maximum(abs(yy - cy), abs(xx - cx))
        hard |= d <= 1
        y[d <= 1] = 0.95
        y[(d > 1) & (d <= 4)] += np.array(ring_color, np.float32)
    return y, hard


def test_fringe_is_found_for_blue_rings_and_reduced_without_changing_luminance():
    y, hard = _field_with_rings((-0.02, -0.01, 0.12))
    ring, info = fin.detect_fringe(y, hard, np.ones(hard.shape, bool))
    assert ring is not None and info["reason"] is None and info["bright_stars"] >= 10
    out = fin.fringe_reduce(np, y, ring, 1.0)
    chroma = lambda a: a.max(-1) - a.min(-1)  # noqa: E731
    sel = (ring > 0.9) & (chroma(y) > 0.05)
    assert sel.sum() > 50
    assert chroma(out)[sel].mean() < 0.5 * chroma(y)[sel].mean()
    assert np.abs(fin.luminance(np, out)[sel] - fin.luminance(np, y)[sel]).max() < 1e-4
    assert np.array_equal(out[ring == 0], y[ring == 0])


def test_fringe_is_not_reported_when_the_surroundings_have_the_same_color():
    y, hard = _field_with_rings((0.0, 0.0, 0.0))
    y[~hard] += np.array((-0.02, -0.01, 0.12), np.float32)  # a blue nebula everywhere, not a ring
    ring, info = fin.detect_fringe(y, hard, np.ones(hard.shape, bool))
    assert ring is None and "No blue/violet fringe" in info["reason"]


# ------------------------------------------------------------------------------ Auto preset (H1)
def _m(core=0.0, ext=0.0, level=0.0, stars=0.0, video=False):
    return {"core_fraction": core, "extended_fraction": ext, "extended_median_above_sky": level, "stars_per_mp": stars, "video_stack": video}


def test_auto_choice_follows_measurements_never_the_object_name():
    assert auto_preset.choose(_m(core=0.01, stars=200))[0] == "bright-core"
    assert auto_preset.choose(_m(core=0.4, ext=0.5, level=0.9))[0] == "moon-planets"  # a bright disc and no stars
    assert auto_preset.choose(_m(stars=1600, video=True))[0] == "moon-planets"  # a planet video: moons and noise read as stars
    assert auto_preset.choose(_m(ext=0.3, level=0.05))[0] == "faint-detail"
    assert auto_preset.choose(_m(ext=0.3, level=0.3))[0] == "natural"  # bright extended signal: not "faint"
    assert auto_preset.choose(_m(ext=0.001, stars=500))[0] == "star-field"
    assert auto_preset.choose(_m(ext=0.02, stars=50))[0] == "natural"


def test_auto_resolves_to_a_builtin_look_and_keeps_the_users_other_settings():
    arr = linear_field(seed=7) / 65535.0
    auto = builtin_presets()["auto"].model_copy(deep=True)
    auto.tone.brightness_ev = 0.3
    resolved, info = auto_preset.resolve(lin(arr), auto)
    chosen = builtin_presets()[info["chosen"]]
    assert resolved.look == chosen.look and not resolved.auto_preset and resolved.preset == info["chosen"]
    assert resolved.tone.brightness_ev == 0.3 and info["reasons"]
    res = run_pipeline(lin(arr), auto, AssetContext(), CPU)
    assert res.report["auto_preset"]["chosen"] == info["chosen"] and res.summary.startswith("Auto: ")
    plain = builtin_presets()["natural"]
    assert auto_preset.resolve(lin(arr), plain) == (plain, None)


# ------------------------------------------------------------------------------ clean frame (U10)
def test_clean_frame_finds_the_largest_rectangle_without_stacking_edges():
    valid = np.ones((120, 160), bool)
    valid[:, :16] = False  # a dithering edge on the left
    valid[100:, :] = False  # and at the bottom
    c = framing.clean_frame(valid, None)
    assert c["needed"] and c["x"] >= 16 and c["y"] == 0 and c["y"] + c["h"] <= 100 and c["x"] + c["w"] <= 160
    assert c["w"] * c["h"] >= 0.9 * (160 - 16) * 100 and (c["width"], c["height"]) == (160, 120)
    assert not framing.clean_frame(np.ones((120, 160), bool), None)["needed"]


# ------------------------------------------------------------------------------ linear-stage cache (E5)
def test_stage_cache_reuses_the_linear_stage_and_matches_a_fresh_run_exactly():
    img = lin(linear_field(seed=9) / 65535.0)
    natural, vivid = builtin_presets()["natural"], builtin_presets()["vivid"]
    cache = StageCache(max_entries=2)
    first = run_pipeline(img, natural, AssetContext(), CPU, cache)
    second = run_pipeline(img, vivid, AssetContext(), CPU, cache)
    assert first.report["linear_stage_cache"]["reused"] is False and second.report["linear_stage_cache"]["reused"] is True
    fresh = run_pipeline(img, vivid, AssetContext(), CPU)
    assert np.array_equal(second.display, fresh.display)
    changed = natural.model_copy(update={"auto": natural.auto.model_copy(update={"gradient": False})})
    assert run_pipeline(img, changed, AssetContext(), CPU, cache).report["linear_stage_cache"]["reused"] is False


# ------------------------------------------------------------------------------ folder browsing (U7)
def test_recent_stack_folders_are_most_recent_first_without_duplicates():
    recent = folders.remember([], r"D:\a_sub")
    recent = folders.remember(recent, r"D:\b_sub")
    recent = folders.remember(recent, '"D:\\a_sub"')
    assert recent[:2] == [r"D:\a_sub", r"D:\b_sub"] and len(recent) == 2
    for i in range(20):
        recent = folders.remember(recent, f"D:\\t{i}")
    assert len(recent) == folders.MAX_RECENT
