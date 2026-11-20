"""Engine 1.7 (Phase 3): star catalog, sky solution, catalog colour, banding, star size, Moon & planets surface mode,
video lucky imaging, mosaics and the Seestar folder scan. All images here are SYNTHETIC test fixtures."""
from __future__ import annotations

import struct

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from scipy import ndimage

from app.processing import banding
from app.processing import pipeline as pl
from app.processing.backends.numpy_backend import NumpyBackend
from app.processing.catalogs import colour
from app.processing.catalogs.stars import StarCatalog, write_catalog
from app.processing.pipeline import AssetContext, ExecutionOptions, run_pipeline
from app.processing.recipe import builtin_presets
from app.processing.sky_solution import sky_solution
from app.processing.stacking.frames import detect_mosaic, scan_folder
from app.processing.stacking.stack import StackRequest, plan, run_stack
from app.processing.stacking.video import open_avi, stack_video
from app.services import seestar
from conftest import make_image
from stack_fixtures import _mosaic, _render_rgb, _write

CPU = ExecutionOptions(device="cpu")


def op(res, name):
    return next(o for o in res.report["operations"] if o["name"] == name)


# ------------------------------------------------------------------------------ star catalog
def test_star_catalog_round_trip_cone_across_ra_zero_and_pole(tmp_path):
    rng = np.random.default_rng(0)
    ra = np.concatenate([rng.uniform(359.0, 360.0, 50), rng.uniform(0.0, 1.0, 50), rng.uniform(0, 360, 50)])
    dec = np.concatenate([rng.uniform(-1, 1, 100), rng.uniform(88.5, 90.0, 50)])
    g = rng.uniform(5, 13.4, 150)
    bp = np.where(np.arange(150) % 10 == 0, np.nan, rng.uniform(0, 3, 150))
    path = tmp_path / "c.bin"
    hdr = write_catalog(path, np.append(ra, 10.0), np.append(dec, 0.0), np.append(g, 14.0), np.append(bp, 1.0))
    assert hdr["n_stars"] == 150  # fainter than the limit is dropped
    cat = StarCatalog(path)
    near0 = cat.cone(0.0, 0.0, 1.5)
    assert len(near0["ra"]) == 100 and np.all(np.diff(near0["g"]) >= 0)  # both sides of RA 0, brightest first
    pole = cat.cone(123.0, 89.5, 2.05)
    assert len(pole["ra"]) == 50  # every star above dec 88.5, whatever its RA (some lie across the pole)
    k = np.argmin(np.hypot(near0["ra"] - ra[0], near0["dec"] - dec[0]))
    assert abs(near0["ra"][k] - ra[0]) < 1e-6 and abs(near0["dec"][k] - dec[0]) < 1e-6
    assert np.isnan(cat.cone(ra[0], dec[0], 0.0001)["bp_rp"]).all()  # star 0 had no colour


# ------------------------------------------------------------------------------ sky solution
SOLVE_W, SOLVE_H, SCALE = 640, 420, 3.7 / 3600


def _field(tmp_path, mirrored=False):
    """A synthetic catalog and an image of it through a known TAN WCS (rotated 25 deg; optionally mirrored)."""
    rng = np.random.default_rng(5)
    ra0, dec0 = 150.0, 30.0
    n = 700
    ra = ra0 + rng.uniform(-1.4, 1.4, n) / np.cos(np.radians(dec0))
    dec = dec0 + rng.uniform(-1.4, 1.4, n)
    g = rng.uniform(7.5, 13.4, n)
    path = tmp_path / f"field-{int(mirrored)}.bin"
    write_catalog(path, ra, dec, g, rng.uniform(0.3, 2.0, n))
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra0, dec0]
    w.wcs.crpix = [SOLVE_W / 2 + 0.5, SOLVE_H / 2 + 0.5]
    a = np.radians(25.0)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    w.wcs.cd = SCALE * (np.diag([1.0 if mirrored else -1.0, 1.0]) @ rot)
    x, y = w.world_to_pixel_values(ra, dec)
    yy, xx = np.mgrid[0:SOLVE_H, 0:SOLVE_W]
    img = np.full((SOLVE_H, SOLVE_W), 0.05) + rng.normal(0, 0.001, (SOLVE_H, SOLVE_W))
    for xi, yi, gi in zip(x, y, g):
        if -5 < xi < SOLVE_W + 5 and -5 < yi < SOLVE_H + 5:
            f = 0.6 * 10 ** (-0.4 * (gi - 8.0))
            y0, y1, x0, x1 = max(0, int(yi) - 8), min(SOLVE_H, int(yi) + 9), max(0, int(xi) - 8), min(SOLVE_W, int(xi) + 9)
            img[y0:y1, x0:x1] += f * np.exp(-((xx[y0:y1, x0:x1] - xi) ** 2 + (yy[y0:y1, x0:x1] - yi) ** 2) / (2 * 1.6**2))
    rgb = np.repeat(img[..., None], 3, -1).astype(np.float32)
    return StarCatalog(path), w, rgb


def _hint_header(dra=0.15, ddec=-0.1):
    h = fits.Header()
    h["RA"], h["DEC"] = 150.0 + dra, 30.0 + ddec  # pointing a little off, as a mount reports it
    h["XPIXSZ"], h["FOCALLEN"] = 2.9, 2.9 / (SCALE * 3600) * 206.265
    return h


def test_sky_solution_solves_from_pointing_hints_in_both_parities(tmp_path):
    for mirrored in (False, True):
        cat, truth, rgb = _field(tmp_path, mirrored)
        image = make_image(rgb, domain="linear", fmt="fits", dtype="float32", bits=32, header=_hint_header())
        sol = sky_solution(image, cat)
        assert sol["status"] == "solved", sol.get("reason")
        assert sol["mirrored"] == mirrored
        c = truth.pixel_to_world_values(SOLVE_W / 2 - 0.5, SOLVE_H / 2 - 0.5)
        assert abs(sol["center_ra"] - c[0]) * np.cos(np.radians(30)) * 3600 < 5 and abs(sol["center_dec"] - c[1]) * 3600 < 5
        assert abs(sol["scale_arcsec"] / (SCALE * 3600) - 1) < 0.01 and sol["rms_px"] < 0.5 and sol["matches"] >= 12


def test_sky_solution_verifies_a_correct_header_wcs_and_rejects_a_wrong_one(tmp_path):
    cat, truth, rgb = _field(tmp_path)
    good = truth.to_header()
    sol = sky_solution(make_image(rgb, domain="linear", fmt="fits", dtype="float32", bits=32, header=good), cat)
    assert sol["status"] == "verified" and sol["source"] == "header"
    bad = truth.deepcopy()
    bad.wcs.crval = [150.3, 30.2]  # off by ~0.3 deg: matches nothing, so it is not trusted
    sol = sky_solution(make_image(rgb, domain="linear", fmt="fits", dtype="float32", bits=32, header=bad.to_header()), cat)
    assert sol["status"] != "verified"


# ------------------------------------------------------------------------------ catalog colour
def test_catalog_star_colour_reddens_monotonically_and_g2v_is_white():
    bp = np.linspace(0.0, 2.5, 26)
    rg, bg = colour.rgb_ratios(bp)
    assert np.all(np.diff(rg) > 0) and np.all(np.diff(bg) < 0)
    r0, b0 = colour.rgb_ratios(np.array([colour.WHITE_BPRP]))
    assert abs(r0[0] - 1) < 1e-6 and abs(b0[0] - 1) < 1e-6
    assert not colour.usable(np.array([np.nan, -0.5, 3.5])).any()


def test_fits_history_describes_both_catalog_sources():
    """Accurate star colours (no CSV hash) once failed every run at the FITS export with a KeyError."""
    from app.services.worker import _linear_history

    builtin = {"operations": [{"name": "catalog_color", "status": "applied", "source": "built-in catalog", "gains_rgb": [0.74, 1.0, 1.11],
                               "used": 79, "sky_solution": "verified"}]}
    lines = _linear_history(builtin)
    assert "Catalog gains R,G,B: 0.7400, 1.0000, 1.1100" in lines
    assert any("built-in Gaia DR3, 79 stars, verified sky solution" in s and len(s) <= 72 for s in lines)
    csv = {"operations": [{"name": "catalog_color", "status": "applied", "gains_rgb": [0.9, 1.0, 1.1], "sha256": "ab" * 32}]}
    assert any(s.startswith("Offline reference CSV SHA-256: abab") for s in _linear_history(csv))


# ------------------------------------------------------------------------------ banding
def test_banding_removes_row_offsets_and_leaves_clean_noise_alone():
    rng = np.random.default_rng(2)
    u = (0.05 + rng.normal(0, 0.002, (300, 260, 3))).astype(np.float32)
    weight = np.ones(u.shape[:2], bool)
    clean, info = banding.reduce_banding(u, weight)
    assert not info["applied"] and np.array_equal(clean, u)
    bands = rng.normal(0, 0.0008, 300).astype(np.float32)  # every row read out with its own offset (40% of the pixel noise)
    banded = u + bands[:, None, None]
    out, info = banding.reduce_banding(banded, weight)
    assert info["applied"] and all(a["corrected"] for a in info["axes"]["rows"])
    rows_before = banded.mean(axis=(1, 2))
    rows_after = out.mean(axis=(1, 2))
    assert np.std(rows_after) < 0.3 * np.std(rows_before)


# ------------------------------------------------------------------------------ star size
def test_star_size_keeps_centroids_and_peaks_shrinks_fwhm_and_never_brightens():
    h, w = 80, 80
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    centres = [(20.3, 22.7), (55.6, 30.2), (40.1, 60.8)]
    S = np.zeros((h, w), np.float32)
    for cy, cx in centres:
        S += (0.6 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 2.6**2))).astype(np.float32)
    out = pl._shrink_stars(NumpyBackend(), S, 2, 1.0)
    assert np.all(out <= S + 1e-7) and out.min() >= 0
    for cy, cx in centres:
        sl = (slice(int(cy) - 9, int(cy) + 10), slice(int(cx) - 9, int(cx) + 10))
        a, b = S[sl], out[sl]
        assert b.max() > 0.95 * a.max()
        c0, c1 = ndimage.center_of_mass(a), ndimage.center_of_mass(b)
        assert np.hypot(c0[0] - c1[0], c0[1] - c1[1]) < 0.1
        assert (b >= b.max() / 2).sum() < 0.7 * (a >= a.max() / 2).sum()


# ------------------------------------------------------------------------------ Moon & planets (surface mode)
def test_moon_surface_mode_neutral_disc_black_sky_no_clipping_no_star_softening():
    rng = np.random.default_rng(4)
    h, w = 300, 300
    yy, xx = np.mgrid[0:h, 0:w]
    disc = np.hypot(yy - 150, xx - 150) < 110
    tex = ndimage.gaussian_filter(rng.normal(0, 1, (h, w)), 3)
    L = np.where(disc, 0.45 + 0.06 * tex, 0.01) + rng.normal(0, 0.0015, (h, w))
    cast = np.array([1.12, 1.0, 0.85])  # a warm cast from the atmosphere
    arr = (L[..., None] * cast).astype(np.float32)
    res = run_pipeline(make_image(arr, domain="linear", fmt="fits", dtype="float32", bits=32), builtin_presets()["moon-planets"],
                       AssetContext(), CPU)
    sw = op(res, "surface_white_balance")
    assert sw["status"] == "applied"
    g = np.array(sw["parameters"]["gains_rgb"])
    assert np.allclose(g * cast, 1.0, atol=0.03)
    assert op(res, "star_stretch")["status"] in ("inactive", "off")
    d = res.display
    assert float(np.median(d[~disc])) < 0.02
    m = d[disc].mean(axis=0)
    assert np.ptp(m) < 0.03 and 0.3 < m.mean() < 0.95
    assert res.report["clipping"]["final"]["new_white_fraction"] < 0.001


# ------------------------------------------------------------------------------ video lucky imaging
def _write_avi(path, frames):
    h, w = frames[0].shape
    strf = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 8, 0, w * h, 0, 0, 0, 0)
    strl = b"LIST" + struct.pack("<I", 4 + 8 + len(strf)) + b"strl" + b"strf" + struct.pack("<I", len(strf)) + strf
    hdrl = b"LIST" + struct.pack("<I", 4 + len(strl)) + b"hdrl" + strl
    movi = b"".join(b"00db" + struct.pack("<I", f.size) + f.tobytes() for f in frames)
    movi = b"LIST" + struct.pack("<I", 4 + len(movi)) + b"movi" + movi
    body = b"AVI " + hdrl + movi
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    path.with_name(path.name + ".txt").write_text("[Seestar S30]\nBayer = GR\nOBJECT = Jupiter\n", encoding="utf-8")


def test_video_reader_and_lucky_stack_pick_the_sharp_frames_and_align_them(tmp_path):
    rng = np.random.default_rng(9)
    h, w = 96, 128
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.where(np.hypot(yy - 48, xx - 64) < 18, 160.0, 8.0) + 40.0 * (np.abs((yy - 48) % 8 - 4) < 1) * (np.hypot(yy - 48, xx - 64) < 18)
    frames, shifts = [], []
    for k in range(40):
        dy, dx = rng.uniform(-3, 3, 2)
        blur = 0.6 if k % 2 == 0 else 3.0  # every other frame is badly blurred by seeing
        f = ndimage.gaussian_filter(ndimage.shift(base, (dy, dx), order=1), blur) + rng.normal(0, 2, (h, w))
        frames.append(np.clip(np.rint(f), 0, 255).astype(np.uint8))
        shifts.append((dy, dx))
    path = tmp_path / "2025-04-09-202539-Jupiter-RAW.avi"
    _write_avi(path, frames)
    v = open_avi(path)
    assert (v.width, v.height, v.bits, v.bottom_up, v.bayer, len(v.offsets)) == (w, h, 8, False, "GRBG", 40)
    assert np.array_equal(v.read(3), frames[3])
    data, cov, rep = stack_video(v)
    assert rep["frames_used"] == 20 and rep["saturation"]["warning"] is None
    lum = data.mean(axis=2)
    sharp = ndimage.laplace(ndimage.gaussian_filter(lum, 0.7)).var()
    naive = np.mean([f.astype(np.float32) / 255 for f in frames], axis=0)
    assert sharp > 2.0 * ndimage.laplace(ndimage.gaussian_filter(naive, 0.7)).var()
    assert plan(StackRequest(folder=str(path)))["mode"] == "video"


# ------------------------------------------------------------------------------ mosaics
MH, MW = 240, 320


def test_mosaic_stack_covers_every_panel_and_chains_panels_that_miss_the_reference(tmp_path):
    rng = np.random.default_rng(11)
    n = 200  # the stacking fixture's star density
    x, y = rng.uniform(-20, 800, n), rng.uniform(-20, 260, n)
    flux, col = 10 ** rng.uniform(3.4, 5.0, n), rng.uniform(0.7, 1.3, (n, 3))
    folder = tmp_path / "M 99_mosaic_sub"
    folder.mkdir()
    k = 0
    for ox in (0, 150, 300, 450):  # panel 450 overlaps panel 150 by only 20 px
        for rep in range(2):
            raw = _mosaic(_render_rgb(x - ox - rep * 0.4, y - rep * 0.3, flux, col)) + 500 + rng.normal(0, 15, (MH, MW))
            _write(folder / f"Light_mosaic_M 99_20.0s_IRCUT_20250101-2100{k:02d}.fit", raw,
                   extra={"RA": 100.0 + ox * 3.7 / 3600, "DEC": 0.0})
            k += 1
    frames = [f for f in scan_folder(folder).frames if f.kind == "light"]
    assert detect_mosaic(frames)[0]
    p = plan(StackRequest(folder=str(folder)))
    assert p["mosaic"]["enabled"] and p["output"]["native"] is None
    rep = run_stack(StackRequest(folder=str(folder)), tmp_path / "out.fits", lambda: None, lambda m, f: None, device="cpu")
    assert rep["frames_used"] == 8 and rep["mosaic"]["chained_frames"] >= 1
    cw, ch = rep["mosaic"]["canvas"]
    assert 760 <= cw <= 775 and 238 <= ch <= 246
    data = fits.getdata(tmp_path / "out.fits")
    assert fits.getheader(tmp_path / "out.fits")["EAESTACK"] == "subs-mosaic"
    assert np.isfinite(data).mean() > 0.95
    off = run_stack(StackRequest(folder=str(folder), mosaic=False), tmp_path / "ref.fits", lambda: None, lambda m, f: None, device="cpu")
    assert off["output"]["width"] == MW and "mosaic" not in off  # turned off: the reference frame's grid as before


# ------------------------------------------------------------------------------ Seestar import
def test_seestar_scan_groups_targets_and_reads_only_names(tmp_path):
    root = tmp_path / "MyWorks"
    (root / "M 31").mkdir(parents=True)
    (root / "M 31" / "Stacked_120_M 31_10.0s_IRCUT_20251020-221500.fit").write_bytes(b"x" * 10)
    (root / "M 31" / "Stacked_30_M 31_10.0s_IRCUT_20251001-210000.fit").write_bytes(b"x")
    (root / "M 31_sub").mkdir()
    for i in range(3):
        (root / "M 31_sub" / f"Light_M 31_10.0s_IRCUT_20251020-2215{i:02d}.fit").write_bytes(b"x")
    (root / "NGC 7000_mosaic").mkdir()
    (root / "NGC 7000_mosaic" / "DSO_Stacked_6_mosaic_NGC 7000_20.0s_LP_20250827_211918.fit").write_bytes(b"x")
    (root / "Lunar").mkdir()
    (root / "Lunar" / "2025-10-01-200000-Lunar-RAW.avi").write_bytes(b"x")
    (root / "Empty").mkdir()
    out = seestar.scan(str(root))
    by = {t["name"]: t for t in out["targets"]}
    assert set(by) == {"M 31", "NGC 7000 (mosaic)", "Moon"}
    m31 = by["M 31"]
    assert m31["stacks"] == 2 and m31["newest_stack"]["frames"] == 120 and m31["newest_stack"]["filter"] == "IRCUT"
    assert m31["subs"]["frames"] == 3 and m31["kind"] == "deep-sky"
    assert by["NGC 7000 (mosaic)"]["kind"] == "mosaic" and by["NGC 7000 (mosaic)"]["newest_stack"]["frames"] == 6
    assert by["Moon"]["kind"] == "moon" and len(by["Moon"]["videos"]) == 1
    assert seestar.scan(str(root / "missing"))["error"]
