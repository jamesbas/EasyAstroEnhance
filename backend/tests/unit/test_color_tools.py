import numpy as np
import pytest
from astropy.io import fits

from app.processing.catalog_color import parse_catalog
from app.processing.color import luminance
from app.processing.color_mix import combine_channels
from app.processing.imagedata import ProcessingError
from app.processing.object_color import hubble_input, hubble_style, selective_color
from app.processing.readers.fits import read_fits
from app.processing.recipe import ObjectColorRecipe, builtin_presets, parse_recipe
from app.processing.stretch import apply_stretch, solve_focus
from color_fixtures import color_test_files


def test_selective_color_protects_sky_stars_highlights_and_other_hues():
    pixels = np.array([[[0.17, 0.35, 0.58], [0.17, 0.35, 0.58], [0.62, 0.3, 0.2],
                        [0.08, 0.10, 0.12], [0.99, 1, 1], [0.17, 0.35, 0.58]]], dtype=np.float32)
    star = np.array([[0, 1, 0, 0, 0, 0]])
    valid = np.array([[1, 1, 1, 1, 1, 0]])
    changed, weight = selective_color(np, pixels, star, valid, 0.12, 0.01, ObjectColorRecipe(blues=1))
    assert changed[0, 0, 2] > pixels[0, 0, 2] + 0.07
    np.testing.assert_array_equal(changed[:, 1:], pixels[:, 1:])
    np.testing.assert_allclose(luminance(np, changed), luminance(np, pixels), atol=1e-6)
    assert weight[0, 0] > 0.5 and np.count_nonzero(weight) == 1
    reduced, _ = selective_color(np, pixels, star, valid, 0.12, 0.01, ObjectColorRecipe(blues=-1))
    assert reduced[0, 0, 2] < pixels[0, 0, 2]


def test_hubble_palette_blends_gold_and_teal_and_leaves_protected_pixels_unchanged():
    display = np.full((1, 6, 3), 0.4, dtype=np.float32)
    display[0, 4] = 0.99
    linear = np.array([[[0.8, 0.13, 0.12], [0.1, 0.63, 0.66], [0.8, 0.13, 0.12],
                        [0.1, 0.104, 0.11], [0.8, 0.13, 0.12], [0.1, 0.63, 0.66]]], dtype=np.float32)
    star = np.array([[0, 0, 1, 0, 0, 0]])
    valid = np.array([[1, 1, 1, 1, 1, 0]])
    high, mask = hubble_style(np, display, linear, star, valid, (0.1, 0.1, 0.1), 0.01, 1)
    half, _ = hubble_style(np, display, linear, star, valid, (0.1, 0.1, 0.1), 0.01, 0.5)
    gold, teal = high[0, :2]
    assert gold[0] > gold[1] > gold[2] and teal[2] > teal[1] > teal[0]
    np.testing.assert_array_equal(high[:, 2:], display[:, 2:])
    np.testing.assert_allclose(half, (display + high) / 2, atol=1e-7)
    np.testing.assert_allclose(luminance(np, high), luminance(np, display), atol=1e-7)
    np.testing.assert_array_equal(mask, [[1, 1, 0, 0, 0, 0]])


def test_palette_input_does_not_assume_generic_lp_is_dualband():
    assert hubble_input({"FILTER": "LP", "INSTRUME": "Seestar S30"}) == "dualband"
    assert hubble_input({"FILTER": "H-alpha / OIII"}) == "dualband"
    assert hubble_input({"FILTER": "LP", "INSTRUME": "Other OSC"}) == "unknown"
    assert hubble_input(None, confirmed=True) == "dualband"
    assert hubble_input({"FILTER": "IR-CUT", "INSTRUME": "Seestar S30"}, confirmed=True) == "broadband"
    assert hubble_input({"FILTER": "H-alpha / OIII", "EAEMIX": "SHO"}, confirmed=True) == "unsupported"


def test_focus_stretch_is_monotonic_anchored_and_moves_the_bend():
    low, high = (solve_focus(0.06, 0.002, 0.6, 1, 0.12, 0.7, k, True, True) for k in (0.15, 0.75))
    samples = np.linspace(0, 1, 800).reshape(1, -1)
    y = apply_stretch(np, samples, low)
    assert np.diff(y).min() >= -1e-10
    assert y[0, -1] == pytest.approx(1)
    assert apply_stretch(np, np.array([[0.06]]), low).item() == pytest.approx(0.12)
    assert abs(apply_stretch(np, np.array([[0.3]]), low).item() - apply_stretch(np, np.array([[0.3]]), high).item()) > 0.1
    legacy = builtin_presets()["natural"].model_dump(exclude={"object_color", "focus_stretch", "catalog_sha256"})
    assert parse_recipe({**legacy, "schema_version": 4}) == builtin_presets()["natural"]
    assert parse_recipe({"schema_version": 5}).hubble_strength == 0


def test_catalog_validation_rejects_non_reference_photometry():
    with pytest.raises(ProcessingError, match="Required columns"):
        parse_catalog(b"ra,dec,phot_bp_mean_mag,phot_rp_mean_mag\n1,1,1,1\n")
    with pytest.raises(ProcessingError, match="duplicated"):
        parse_catalog(b"ra_deg,dec_deg,r_over_g,b_over_g\n" + b"1,1,1,1\n" * 8)


def test_mix_aligns_shifted_wcs_and_refuses_implicit_geometry(tmp_path):
    p = color_test_files(tmp_path)
    ref = read_fits(p["ha"], "a" * 64, 1_000_000, "linear")
    raw = fits.getdata(p["oiii"])
    header = fits.getheader(p["oiii"])
    header["CRPIX1"] += 6
    shifted = np.pad(raw, ((0, 0), (6, 0)), constant_values=np.nan)
    fits.writeto(tmp_path / "shifted.fits", shifted, header)
    src = read_fits(tmp_path / "shifted.fits", "b" * 64, 1_000_000, "linear")
    rgb, out_header = combine_channels([ref, src], "HOO", [1, 2], 0.5, False, lambda: None)
    assert out_header["CRPIX1"] == pytest.approx(ref.header["CRPIX1"])
    np.testing.assert_allclose(rgb[3:-3, 2:-2, 1], raw[3:-3, 2:-2] * 2, atol=1e-4)
    np.testing.assert_array_equal(rgb[..., 1], rgb[..., 2])
    assert "SHA256" in str(out_header["HISTORY"])
    src.header = fits.Header()
    with pytest.raises(ProcessingError, match="already aligned"):
        combine_channels([ref, src], "HOO", [1, 1], 0.5, False, lambda: None)


@pytest.mark.parametrize("mode, roles, expected", [
    ("RGB", ["ha", "oiii", "ha"], lambda a, b, rgb: (a, b, a)),
    ("LRGB", ["ha", "oiii", "ha", "oiii"], lambda a, b, rgb: np.array([a, b, a]) + 0.5 * (b - luminance(np, np.array([a, b, a])))),
    ("SHO", ["ha", "oiii", "ha"], lambda a, b, rgb: (a, b, a)),
    ("DUAL-SHO", ["rgb", "rgb"], lambda a, b, rgb: (2 * rgb[0], rgb[0], 0.75 * (rgb[1] + rgb[2]))),
    ("HA-RGB", ["rgb", "oiii"], lambda a, b, rgb: (rgb[0] + 0.5 * max(b - rgb[0], 0), rgb[1], rgb[2])),
])
def test_mixing_assigns_physical_channels(tmp_path, mode, roles, expected):
    files = color_test_files(tmp_path)
    inputs = [read_fits(files[role], role, 1_000_000, "linear") for role in roles]
    gains = [1, 2] if mode == "DUAL-SHO" else [1] * len(roles)
    arr, header = combine_channels(inputs, mode, gains, 0.5, False, lambda: None)
    coords = 100, 121
    a, b = [fits.getdata(files[k])[coords] for k in ("ha", "oiii")]
    rgb = fits.getdata(files["rgb"])[:, coords[0], coords[1]]
    np.testing.assert_allclose(arr[coords], expected(a, b, rgb), atol=2e-5)
    assert header["EAEMIX"] == mode
