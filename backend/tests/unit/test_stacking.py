"""Stacking: registration, calibration, rejection, drizzle and merging stacked nights on synthetic sky frames."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from app.processing.imagedata import ProcessingError
from app.processing.stacking.calibrate import debayer
from app.processing.stacking.frames import choose_lights, inspect_frame, scan_folder
from app.processing.stacking.quality import measure
from app.processing.stacking.register import Transform, match
from app.processing.stacking.stack import StackRequest, plan, run_stack
from stack_fixtures import BIAS, H, HOT, PATTERN, SKY, W, _make_subs, _render_rgb, _stars, _transform, _write

def _read_stack(path: Path) -> np.ndarray:
    with fits.open(path) as hdul:
        assert hdul[0].header["ROWORDER"] == "TOP-DOWN"
        return np.moveaxis(hdul[0].data.astype(np.float64), 0, -1)


def test_scan_classifies_and_groups(tmp_path):
    _make_subs(tmp_path / "subs", n=3)
    _write(tmp_path / "subs" / "Dark_20s.fit", np.full((H, W), BIAS), kind="Dark")
    (tmp_path / "subs" / "notes.txt").write_text("not a frame")
    scan = scan_folder(tmp_path / "subs")
    assert [f.kind for f in scan.frames].count("light") == 3 and scan.by_kind("dark")
    info = inspect_frame(next((tmp_path / "subs").glob("Light_*.fit")))
    assert info.layout == "cfa" and info.bayer == PATTERN and info.exposure == 20.0
    mode, group = choose_lights(scan.frames, "auto")
    assert mode == "subs" and len(group.frames) == 3
    with pytest.raises(ProcessingError):
        scan_folder("relative/folder")


def test_bayer_pattern_follows_row_flip(tmp_path):
    raw = np.full((H, W), 1000.0)
    hdu = fits.PrimaryHDU(raw.astype(np.uint16))
    hdu.header["BAYERPAT"] = "RGGB"  # no ROWORDER, not a Seestar: rows are flipped for display
    hdu.writeto(tmp_path / "a.fit")
    assert inspect_frame(tmp_path / "a.fit").bayer == "GBRG"


def test_registration_recovers_rotation_and_shift(tmp_path):
    truth, _ = _make_subs(tmp_path / "subs", n=3, trail_frame=None)
    files = sorted((tmp_path / "subs").glob("Light_*.fit"))
    st = []
    for f in files:
        raw = fits.getdata(f).astype(np.float64)
        st.append(measure(raw, "cfa", PATTERN)[1])
    for k in (1, 2):
        m = match(st[0], st[k])
        assert m.ok and m.inliers >= 20 and m.rms < 0.5
        inv = truth[k].inverse()  # frame k -> reference
        assert abs(m.transform.angle_deg - inv.angle_deg) < 0.05
        px, py = m.transform.apply(np.array([10.0, 300.0]), np.array([20.0, 200.0]))
        ex, ey = inv.apply(np.array([10.0, 300.0]), np.array([20.0, 200.0]))
        assert np.max(np.hypot(px - ex, py - ey)) < 0.3


def test_stack_removes_trail_and_hot_pixels_and_reduces_noise(tmp_path):
    _make_subs(tmp_path / "subs", n=8)
    out = tmp_path / "stack.fits"
    rep = run_stack(StackRequest(folder=str(tmp_path / "subs")), out, lambda: None, lambda *_: None, device="cpu")
    assert rep["mode"] == "subs" and rep["frames_used"] == 8
    assert rep["calibration"]["defective_pixels"]["count"] >= len(HOT)
    img = _read_stack(out)
    assert img.shape == (H, W, 3)
    with fits.open(out) as hdul:
        assert hdul[0].header["STACKCNT"] == 8 and hdul[0].header["LIVETIME"] == 160.0
    core = img[30:-30, 40:-40]
    # background level and colour preserved (bias is not removed without calibration frames)
    sky = np.nanmedian(core.reshape(-1, 3), axis=0)
    assert np.allclose(sky, SKY + BIAS, rtol=0.02)
    # satellite trail rejected: no trace along its path inside the fully covered area
    rr = np.arange(60, 260)
    trail = img[(0.4 * rr + 30).astype(int), rr]
    assert np.nanmax(np.abs(np.nanmedian(trail, axis=0) - sky)) < 15
    # hot pixels gone
    for yy, xx in HOT[:2]:
        assert np.all(np.abs(img[yy, xx] - sky) < 200)
    # noise drops roughly with sqrt(N) versus a single debayered frame
    single = debayer(fits.getdata(sorted((tmp_path / "subs").glob("Light_*.fit"))[0]).astype(np.float32), PATTERN)
    def noise(a):
        d = np.diff(a[60:-60, 60:-60, 1], axis=1)
        return np.median(np.abs(d - np.median(d))) * 1.4826
    assert noise(img) < 0.6 * noise(single)


def test_cloudy_frame_rejected_with_reason(tmp_path):
    _make_subs(tmp_path / "subs", n=8, cloudy_frame=5, trail_frame=None)
    rep = run_stack(StackRequest(folder=str(tmp_path / "subs")), tmp_path / "s.fits", lambda: None, lambda *_: None, device="cpu")
    assert rep["frames_used"] == 7
    assert "clouds" in rep["rejected_frames"][0]["reason"]


def test_darks_and_flats_calibrate(tmp_path):
    rng = np.random.default_rng(9)
    yy, xx = np.mgrid[0:H, 0:W]
    vignette = 1.0 - 0.35 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2
    dark_current = rng.gamma(2.0, 8.0, (H, W))
    _make_subs(tmp_path / "lights", n=6, trail_frame=None, vignette=vignette, dark_current=dark_current)
    (tmp_path / "darks").mkdir()
    (tmp_path / "flats").mkdir()
    for k in range(5):
        dk = BIAS + dark_current + rng.normal(0, 18, (H, W))
        for y0, x0 in HOT:
            dk[y0, x0] += 9000
        _write(tmp_path / "darks" / f"d{k}.fit", dk, kind="Dark")
        _write(tmp_path / "flats" / f"f{k}.fit", 20000 * vignette + BIAS + rng.normal(0, 30, (H, W)), kind="Flat")
    req = StackRequest(folder=str(tmp_path / "lights"), darks=str(tmp_path / "darks"), flats=str(tmp_path / "flats"))
    p = plan(req)
    assert p["calibration"] == {"dark": 5, "flat": 5, "bias": 0, "darkflat": 0}
    rep = run_stack(req, tmp_path / "s.fits", lambda: None, lambda *_: None, device="cpu")
    assert rep["calibration"]["darks"] == 5 and rep["calibration"]["flats"] == 5
    assert rep["calibration"]["defective_pixels"]["source"] == "master dark"
    img = _read_stack(tmp_path / "s.fits")[20:-20, 20:-20, 1]
    sky = np.nanmedian(img)
    assert abs(sky - SKY[1] * np.median(vignette)) < 0.03 * SKY[1]  # dark (with bias) removed; flat is median-normalized
    centre, corner = np.nanmedian(img[90:110, 130:150]), np.nanmedian(img[:30, :30])
    assert abs(centre - corner) < 0.03 * sky  # vignetting corrected (flat lacks dark-flats: small residual allowed)


def test_drizzle_doubles_resolution_and_reports_fill(tmp_path):
    _make_subs(tmp_path / "subs", n=8)
    rep = run_stack(StackRequest(folder=str(tmp_path / "subs"), scale=2), tmp_path / "d.fits", lambda: None, lambda *_: None, device="cpu")
    img = _read_stack(tmp_path / "d.fits")
    assert img.shape == (2 * H, 2 * W, 3)
    assert rep["drizzle"]["scale"] == 2 and 0 <= rep["drizzle"]["filled_from_native_fraction"] < 0.5
    sky = np.nanmedian(img[60:-60, 80:-80].reshape(-1, 3), axis=0)
    assert np.allclose(sky, SKY + BIAS, rtol=0.03)


def test_cancel_stops_stacking(tmp_path):
    _make_subs(tmp_path / "subs", n=4, trail_frame=None)
    calls = {"n": 0}

    class Cancelled(Exception):
        pass

    def check():
        calls["n"] += 1
        if calls["n"] > 3:
            raise Cancelled()
    with pytest.raises(Cancelled):
        run_stack(StackRequest(folder=str(tmp_path / "subs")), tmp_path / "s.fits", check, lambda *_: None, device="cpu")
    assert not (tmp_path / "s.fits").exists()


def test_streaming_integration_matches_in_memory(tmp_path):
    _make_subs(tmp_path / "subs", n=8)
    req = StackRequest(folder=str(tmp_path / "subs"))
    a = run_stack(req, tmp_path / "a.fits", lambda: None, lambda *_: None, device="cpu")
    b = run_stack(req, tmp_path / "b.fits", lambda: None, lambda *_: None, device="cpu", memory_budget_bytes=1)
    assert a["integration"]["algorithm"].startswith("exact") and b["integration"]["algorithm"].startswith("streaming")
    ia, ib = _read_stack(tmp_path / "a.fits"), _read_stack(tmp_path / "b.fits")
    both = np.isfinite(ia) & np.isfinite(ib)
    assert np.median(np.abs(ia - ib)[both]) < 2.0  # sky noise per frame is 18 ADU
    rr = np.arange(60, 260)
    sky = np.nanmedian(ib[30:-30, 40:-40].reshape(-1, 3), axis=0)
    assert np.nanmax(np.abs(np.nanmedian(ib[(0.4 * rr + 30).astype(int), rr], axis=0) - sky)) < 15


@pytest.mark.gpu
def test_gpu_stack_matches_cpu(tmp_path):
    from app.processing.backends import probe_cuda

    if not probe_cuda()["ok"]:
        pytest.skip("No working CUDA device")
    _make_subs(tmp_path / "subs", n=6)
    req = StackRequest(folder=str(tmp_path / "subs"))
    run_stack(req, tmp_path / "c.fits", lambda: None, lambda *_: None, device="cpu")
    rep = run_stack(req, tmp_path / "g.fits", lambda: None, lambda *_: None, device="gpu")
    assert rep["device"] == "gpu"
    c, g = _read_stack(tmp_path / "c.fits"), _read_stack(tmp_path / "g.fits")
    both = np.isfinite(c) & np.isfinite(g)
    assert np.nanmax(np.abs(c - g)[both]) < 0.05


def test_sessions_merge_nights(tmp_path):
    rng = np.random.default_rng(5)
    x, y, flux, colour = _stars(rng)
    folder = tmp_path / "nights"
    folder.mkdir()
    for k, (t, scale) in enumerate(((Transform(1, 0, 0, 0), 1), (_transform(1.0, 4, -3), 1), (_transform(-0.5, -2, 5), 1))):
        fx, fy = t.apply(x, y)
        rgb = _render_rgb(fx, fy, flux, colour) + rng.normal(0, 12, (H, W, 3))
        hdu = fits.PrimaryHDU(np.moveaxis(rgb, -1, 0).astype(np.float32))
        hdu.header.update({"ROWORDER": "TOP-DOWN", "STACKCNT": 50 + 10 * k, "EXPTIME": 10.0, "IMAGETYP": "Light"})
        hdu.writeto(folder / f"night{k}.fit")
    p = plan(StackRequest(folder=str(folder)))
    assert p["mode"] == "sessions" and p["lights"]["count"] == 3 and not p["drizzle_available"]
    rep = run_stack(StackRequest(folder=str(folder)), tmp_path / "m.fits", lambda: None, lambda *_: None, device="cpu")
    assert rep["frames_used"] == 3
    img = _read_stack(tmp_path / "m.fits")
    sky = np.nanmedian(img[30:-30, 30:-30].reshape(-1, 3), axis=0)
    assert np.allclose(sky, SKY, rtol=0.02)
    with fits.open(tmp_path / "m.fits") as hdul:
        assert hdul[0].header["STACKCNT"] == 180


SEESTAR_SUBS = Path(__import__("os").environ.get("EAE_SEESTAR_DIR", r"D:\Seestar\MyWorks")) / "M 42_sub"


@pytest.mark.realfiles
def test_real_seestar_subs_stack(tmp_path):
    """77 real Seestar S30 subs (read-only): cloudy frames at the end are skipped, the rest align across field rotation."""
    if not SEESTAR_SUBS.is_dir():
        pytest.skip(f"{SEESTAR_SUBS} not available")
    rep = run_stack(StackRequest(folder=str(SEESTAR_SUBS)), tmp_path / "m42.fits", lambda: None, lambda *_: None, device="cpu")
    assert rep["frames_total"] == 77 and 55 <= rep["frames_used"] <= 70
    assert all("clouds" in r["reason"] or "bloated" in r["reason"] for r in rep["rejected_frames"])
    assert rep["registration"]["median_rms_px"] < 0.6
    assert rep["registration"]["rotation_range_deg"][1] - rep["registration"]["rotation_range_deg"][0] > 5
    img = _read_stack(tmp_path / "m42.fits")
    assert img.shape == (1920, 1080, 3) and np.isfinite(img).mean() > 0.99
    with fits.open(tmp_path / "m42.fits") as hdul:
        assert hdul[0].header["STACKCNT"] == rep["frames_used"] and "Seestar" in hdul[0].header["INSTRUME"]
