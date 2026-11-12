"""Milestone 3/4 integration: TIFF + FITS through precision-preserving readers and the separate linear pipeline.

Synthetic FITS/TIFF below are labelled TEST FIXTURES (unit-level). Tests marked ``realfiles`` use the user's real
files in samplepics/ and are skipped when absent. A real *Seestar stacked RGB* FITS is still required for the
release gate; the real FITS here are a radio HI map (mono, scaled int32 with BLANK) and an HST WFPC2 cube.
"""
from __future__ import annotations

import hashlib
import io
import zipfile

import imagecodecs
import numpy as np
import pytest
import tifffile
from astropy.io import fits
from PIL import Image

from app.processing.pipeline import AssetContext, ExecutionOptions, run_pipeline
from app.processing.recipe import (
    BackgroundRecipe, Recipe, Switch, ToneRecipe, builtin_presets, no_operations_recipe,
)
from conftest import linear_field, make_image, real_file, synthetic_field, write_jpeg
from integration.test_jpeg_slice import default_recipe, ready, run_job, upload


def run(img, recipe, ctx=None, **kw):
    return run_pipeline(img, recipe, ctx or AssetContext(), ExecutionOptions(**kw))


def lin_img(arr):
    return make_image(arr, domain="linear", fmt="fits", dtype="float32", bits=32)


def all_display_ops():
    return Recipe(
        preset="custom", denoise=Switch(strength="balanced"),
        tone=ToneRecipe(enabled=True, strength="strong", brightness_ev=0.4, shadows=0.5, highlights=-0.3, black_point=0.01),
        star_protection=Switch(strength="strong"), local_contrast=Switch(strength="balanced"), color=Switch(strength="strong"),
    )


# ------------------------------------------------------------------------------ separate linear pipeline
def test_processed_linear_excludes_all_display_only_operations():
    lin = linear_field(h=150, w=190, seed=3)
    img = lin_img(lin)
    denoise_only = Recipe(preset="custom", denoise=Switch(strength="balanced"), tone=ToneRecipe(enabled=False), star_protection=Switch(enabled=False), local_contrast=Switch(enabled=False), color=Switch(enabled=False))
    a = run(img, denoise_only)
    b = run(img, all_display_ops())
    assert np.array_equal(a.processed, b.processed)  # tone/contrast/saturation/star-protection never touch the linear array
    assert not np.array_equal(a.display, b.display)
    assert not np.array_equal(a.processed, lin) and np.abs(a.processed - lin).max() > 0  # denoise did change it
    assert b.report["mode"] == "linear"


def test_linear_no_operations_returns_source_array_and_baseline_display():
    lin = linear_field(h=100, w=120, seed=4, negatives=True)
    res = run(lin_img(lin), no_operations_recipe())
    assert np.array_equal(res.processed, lin) and (res.processed < 0).any()
    assert np.array_equal(res.display, res.baseline) and np.array_equal(res.display_fixed, res.baseline)
    assert res.display.dtype == np.float32 and res.display.max() <= 1.0


def test_linear_display_is_frozen_baseline_when_tone_disabled_and_stretch_differs_when_enabled():
    lin = linear_field(h=120, w=150, seed=5)
    img = lin_img(lin)
    off = run(img, Recipe(preset="c", denoise=Switch(enabled=False), tone=ToneRecipe(enabled=False), star_protection=Switch(enabled=False), color=Switch(enabled=False)))
    on = run(img, Recipe(preset="c", denoise=Switch(enabled=False), tone=ToneRecipe(enabled=True, strength="strong"), star_protection=Switch(enabled=False), color=Switch(enabled=False)))
    assert np.array_equal(off.display, off.baseline)
    assert np.median(on.display) > np.median(off.display)  # faint detail brightened by the separate linear stretch
    assert on.report["enhanced_frame"] is not None and on.report["baseline_frame"]["k"] == 8.0
    assert np.array_equal(on.display_fixed, on.baseline)  # fixed-mapping diagnostic == frozen baseline when processed==source


def test_linear_scale_aware_noise_estimate_in_any_units():
    base = linear_field(h=140, w=160, seed=6)
    for unit in (1e-6, 1.0, 1e6):
        res = run(lin_img(base * np.float32(unit)), Recipe(preset="c", denoise=Switch(strength="strong"), tone=ToneRecipe(enabled=False), star_protection=Switch(enabled=False), color=Switch(enabled=False)))
        out = res.processed / unit
        from scipy import ndimage

        def hp_sigma(a):  # robust high-pass noise of channel 0 (removes channel offsets and smooth structure)
            r = a[..., 0] - ndimage.gaussian_filter(a[..., 0], 1.0)
            return 1.4826 * np.median(np.abs(r - np.median(r)))

        assert hp_sigma(out) < hp_sigma(base) * 0.9, unit  # no fixed 1/1024 floor: works from 1e-6 to 1e6


def test_linear_denoise_keeps_faint_flux_and_position():
    rng = np.random.default_rng(7)
    h = w = 128
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    clean = 500 + 40 * np.exp(-(((xx - 64.4) ** 2 + (yy - 70.2) ** 2) / (2 * 3.0**2)))
    noisy = (clean + rng.normal(0, 15, clean.shape)).astype(np.float32)
    res = run(lin_img(noisy), Recipe(preset="c", denoise=Switch(strength="balanced"), tone=ToneRecipe(enabled=False), star_protection=Switch(enabled=False), color=Switch(enabled=False)))
    fp = np.hypot(yy - 70.2, xx - 64.4) < 9
    before, after = (noisy - 500)[fp].sum(), (res.processed - 500)[fp].sum()
    assert abs(after - before) / before < 0.1
    from scipy import ndimage

    c = lambda a: np.array(ndimage.center_of_mass(np.clip(ndimage.gaussian_filter(a, 1.5) - 520, 0, None)))  # noqa: E731
    assert np.abs(c(res.processed) - c(noisy)).max() < 0.7


def test_linear_protected_pixels_untouched_and_use_baseline_display():
    lin = linear_field(h=140, w=180, seed=8)
    img = lin_img(lin)
    region = [{"x": 0, "y": 120, "w": 180, "h": 20}]
    res = run(img, builtin_presets()["brighter-detail"], AssetContext(regions=region))
    assert np.array_equal(res.processed[120:], lin[120:])  # untouched in the linear output
    assert np.array_equal(res.display[120:], res.baseline[120:])  # source's baseline rendering in output


def test_linear_nonfinite_pixels_masked():
    lin = linear_field(h=100, w=120, rgb=False, seed=9)
    lin[10:14, 10:14] = np.nan
    valid = np.isfinite(lin)
    pix = np.where(valid, lin, 0)
    res = run(make_image(pix, domain="linear", valid=valid, fmt="fits", dtype="float32", bits=32), builtin_presets()["natural"])
    assert np.all(res.display[10:14, 10:14] == 0) and np.isfinite(res.display).all() and res.report["source"]["invalid_pixels"] == 16


# ------------------------------------------------------------------------------ API: synthetic TIFF/FITS
def synthetic_fits_rgb(path, h=96, w=128):
    data = np.moveaxis(linear_field(h=h, w=w, seed=21), -1, 0).astype(np.float32)
    hd = fits.PrimaryHDU(data)
    hd.header["CTYPE3"] = "RGB"
    hd.header["CTYPE1"], hd.header["CTYPE2"] = "RA---TAN", "DEC--TAN"
    hd.header["CRVAL1"], hd.header["CRVAL2"], hd.header["CRPIX1"], hd.header["CRPIX2"] = 10.0, 20.0, 64.0, 48.0
    hd.header["CD1_1"], hd.header["CD2_2"] = -0.001, 0.001
    hd.header["OBJECT"] = "SYNTHETIC TEST"
    hd.header["OBSERVER"] = "Someone"
    hd.header["SITELAT"] = 40.0
    hd.writeto(path, overwrite=True)
    return data


def confirm(client, asset, state):
    r = client.patch(f"/api/v1/assets/{asset['id']}/interpretation", json={"state": state})
    assert r.status_code == 200, r.text
    return ready(client, asset["id"])


def test_unknown_state_blocks_enhancement_until_confirmed_but_previews(client, tmp_path):
    p = tmp_path / "stack.fits"
    synthetic_fits_rgb(p)
    a = ready(client, upload(client, p)["id"])
    assert a["status"] == "needs_input" and a["questions"][0]["id"] == "state"
    assert [o["value"] for o in a["questions"][0]["options"]] == ["linear", "rendered", "unsure"]
    assert a["thumb_url"] and a["baseline"]["label"].startswith("Preview only")  # labeled preview exists
    r = client.post("/api/v1/jobs", json={"request_key": "unknown-state-1", "asset_ids": [a["id"]], "recipe": default_recipe(client)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOTHING_TO_PROCESS"
    unsure = confirm(client, a, "unsure")
    assert unsure["status"] == "needs_input" and not unsure["can_process"]
    assert client.post("/api/v1/jobs", json={"request_key": "unknown-state-2", "asset_ids": [a["id"]], "recipe": default_recipe(client)}).status_code == 422


def test_synthetic_fits_rgb_stack_end_to_end_unit_level(client, tmp_path):
    p = tmp_path / "SYNTHETIC_stack.fits"
    src = synthetic_fits_rgb(p)
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    a = confirm(client, ready(client, upload(client, p)["id"]), "linear")
    assert a["status"] == "ready" and a["channel_layout"] == "rgb" and (a["width"], a["height"]) == (128, 96)
    assert a["baseline"]["label"] == "Original shown with a display stretch"
    job = run_job(client, [a["id"]], default_recipe(client), key="fits-syn-0001")
    it = job["items"][0]
    assert it["state"] in ("succeeded", "succeeded_with_notes"), it.get("error")
    run = client.get(f"/api/v1/runs/{it['run_id']}").json()
    kinds = {e["kind"] for e in run["exports"]}
    assert {"png", "tiff", "fits", "report", "summary", "comparison", "jpeg"} <= kinds
    png = imagecodecs.png_decode(client.get(f"/api/v1/runs/{run['id']}/exports/png").content)
    assert png.shape == (96, 128, 3) and png.dtype == np.uint16  # 16-bit, full resolution, never via 8-bit
    out = client.get(f"/api/v1/runs/{run['id']}/exports/fits").content
    with fits.open(io.BytesIO(out)) as hd:
        assert hd[0].data.shape == (3, 96, 128) and hd[0].header["EAEKIND"] == "processed-linear"
        assert "SITELAT" not in hd[0].header and "OBSERVER" not in hd[0].header and hd[0].header["CTYPE1"] == "RA---TAN"
    full = client.get(f"/api/v1/runs/{run['id']}/exports/fits-full").content
    with fits.open(io.BytesIO(full)) as hd:
        assert hd[0].header["SITELAT"] == 40.0  # explicit full-metadata export
    rep = client.get(f"/api/v1/runs/{run['id']}/exports/report").json()
    assert rep["applied"]["mode"] == "linear" and rep["applied"]["source"]["format"] == "fits"
    assert hashlib.sha256((client.cfg.assets_dir / a["id"] / "original.fits").read_bytes()).hexdigest() == before
    assert client.get(f"/api/v1/runs/{run['id']}/preview", params={"variant": "fixed"}).status_code == 200
    # a no-op run reproduces the source linear data (within float32) in the FITS export
    noop = Recipe(**no_operations_recipe().model_dump())
    j2 = run_job(client, [a["id"]], noop.model_dump(), key="fits-syn-noop1")
    r2 = client.get(f"/api/v1/runs/{j2['items'][0]['run_id']}/exports/fits").content
    with fits.open(io.BytesIO(r2)) as hd:
        np.testing.assert_allclose(hd[0].data, src, rtol=1e-6, atol=1e-3)


def test_synthetic_uint16_tiff_linear_keeps_precision_and_exports_float_tiff(client, tmp_path):
    rng = np.random.default_rng(12)
    raw = np.clip(linear_field(h=90, w=110, seed=12, sky=3000, noise=30), 0, 65535).astype(np.uint16)
    p = tmp_path / "SYNTHETIC_stack16.tif"
    tifffile.imwrite(p, raw, photometric="rgb")
    a = confirm(client, ready(client, upload(client, p)["id"]), "linear")
    assert a["status"] == "ready" and a["bit_depth"] == 16
    noop = no_operations_recipe().model_dump()
    j = run_job(client, [a["id"]], noop, key="tiff-noop-0001")
    run = client.get(f"/api/v1/runs/{j['items'][0]['run_id']}").json()
    lin = tifffile.imread(io.BytesIO(client.get(f"/api/v1/runs/{run['id']}/exports/linear-tiff").content))
    assert lin.dtype == np.float32 and np.array_equal(lin.astype(np.uint16), raw)  # values preserved exactly
    rendered = confirm(client, a, "rendered")
    j2 = run_job(client, [a["id"]], noop, key="tiff-noop-0002")
    run2 = client.get(f"/api/v1/runs/{j2['items'][0]['run_id']}").json()
    png = imagecodecs.png_decode(client.get(f"/api/v1/runs/{run2['id']}/exports/png").content)
    assert png.dtype == np.uint16 and np.array_equal(png, raw)  # rendered no-op PNG matches decoded 16-bit pixels exactly


def test_mixed_batch_corrupt_duplicates_and_zip(client, tmp_path):
    jpg_arr, _ = synthetic_field()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    j1 = write_jpeg(tmp_path / "a" / "same.jpg", jpg_arr)
    j2 = write_jpeg(tmp_path / "b" / "same.jpg", jpg_arr[::-1].copy())  # identical filename, different content
    tif = tmp_path / "t16.tif"
    tifffile.imwrite(tif, (np.clip(linear_field(h=80, w=100, seed=14, sky=2000, noise=25), 0, 65535)).astype(np.uint16), photometric="rgb")
    fts = tmp_path / "stack.fits"
    synthetic_fits_rgb(fts)
    bad = tmp_path / "broken.fits"
    bad.write_bytes(b"SIMPLE  =                    T" + b"x" * 200)
    files = [("files", (n, p.read_bytes(), "application/octet-stream")) for n, p in [("same.jpg", j1), ("same.jpg", j2), ("t16.tif", tif), ("stack.fits", fts), ("broken.fits", bad)]]
    assets = client.post("/api/v1/assets", files=files).json()["assets"]
    done = [ready(client, a["id"]) for a in assets]
    by = {i: a for i, a in enumerate(done)}
    assert by[4]["status"] == "failed"  # corrupt file fails individually
    confirm(client, by[2], "linear")
    confirm(client, by[3], "linear")
    ids = [a["id"] for a in done if a["status"] != "failed"]
    job = run_job(client, ids, default_recipe(client), key="mixed-batch-1")
    assert all(i["state"] in ("succeeded", "succeeded_with_notes") for i in job["items"]), [i.get("error") for i in job["items"]]
    runs = [i["run_id"] for i in job["items"]]
    assert len(set(runs)) == 4  # identical filenames never overwrite each other
    z = client.post("/api/v1/exports/batch", json={"run_ids": runs, "include": ["tiff", "fits"]})
    assert z.status_code == 202
    zid = z.json()["id"]
    from conftest import wait_for

    st = wait_for(lambda: (lambda s: s if s["state"] in ("ready", "failed") else None)(client.get(f"/api/v1/exports/{zid}").json()))
    assert st["state"] == "ready"
    zf = zipfile.ZipFile(io.BytesIO(client.get(st["download_url"]).content))
    names = zf.namelist()
    assert "batch-summary.txt" in names and len({n.split("/")[0] for n in names if "/" in n}) == 4
    assert sum(n.endswith("/enhanced.png") for n in names) == 4 and any(n.endswith("processed-linear.fits") for n in names)
    assert zf.testzip() is None


# ------------------------------------------------------------------------------ real files
@pytest.mark.realfiles
def test_real_scaled_fits_end_to_end(client):
    p = real_file("M33_HI_25sec-peak.fits")
    if p is None:
        pytest.skip("real FITS not present in samplepics/")
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    a = ready(client, upload(client, p)["id"])
    assert a["status"] == "needs_input" and a["channel_layout"] == "mono" and (a["width"], a["height"]) == (435, 619)
    a = confirm(client, a, "linear")
    assert a["status"] == "ready"
    job = run_job(client, [a["id"]], default_recipe(client), key="real-fits-0001")
    it = job["items"][0]
    assert it["state"] in ("succeeded", "succeeded_with_notes"), it.get("error")
    run = client.get(f"/api/v1/runs/{it['run_id']}").json()
    png = imagecodecs.png_decode(client.get(f"/api/v1/runs/{run['id']}/exports/png").content)
    assert png.shape == (619, 435) and png.dtype == np.uint16  # full-resolution mono 16-bit export
    with fits.open(p) as orig, fits.open(io.BytesIO(client.get(f"/api/v1/runs/{run['id']}/exports/fits").content)) as out:
        src = orig[0].data.astype(np.float64).reshape(619, 435)  # Astropy applied BSCALE/BZERO once
        assert out[0].data.shape == (1, 1, 619, 435)  # original degenerate axes restored so WCS stays valid
        h = out[0].header
        assert all(k not in h for k in ("BSCALE", "BZERO", "BLANK", "DATAMIN", "DATAMAX", "BUNIT"))
        assert h["CTYPE1"] == "RA---SIN" and h["CRVAL1"] == orig[0].header["CRVAL1"] and h["CDELT2"] == orig[0].header["CDELT2"]
        assert np.array_equal(np.isnan(out[0].data.reshape(619, 435)), np.isnan(src)) and np.isnan(src).sum() == 82307  # BLANK mask preserved exactly
        assert 1.0 < np.nanmean(out[0].data) < 110.0  # physical Kelvin-scale values, not 0..1 display values
        assert abs(np.nanmean(out[0].data) - np.nanmean(src)) < 0.05 * abs(np.nanmean(src))
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    # a no-operations run reproduces the physical values to float32 precision
    j2 = run_job(client, [a["id"]], no_operations_recipe().model_dump(), key="real-fits-noop")
    r2 = j2["items"][0]["run_id"]
    with fits.open(p) as orig, fits.open(io.BytesIO(client.get(f"/api/v1/runs/{r2}/exports/fits").content)) as out:
        np.testing.assert_allclose(out[0].data.reshape(619, 435), orig[0].data.reshape(619, 435), rtol=1e-6, atol=1e-6)  # NaNs compare equal
        assert out[0].data.dtype == np.dtype(">f8")  # float64 source precision is not reduced
    # the same file as "already processed" takes the display pipeline and labels its FITS display-processed
    a = confirm(client, a, "rendered")
    j3 = run_job(client, [a["id"]], default_recipe(client), key="real-fits-rend")
    run3 = client.get(f"/api/v1/runs/{j3['items'][0]['run_id']}").json()
    assert next(e for e in run3["exports"] if e["kind"] == "fits")["filename"] == "display-processed.fits"


@pytest.mark.realfiles
def test_real_hst_multiplane_cube_gets_explanation_not_a_guess(client):
    p = real_file("hst-wfpc*.fits")
    if p is None:
        pytest.skip("real HST file not present")
    a = ready(client, upload(client, p)["id"])
    assert a["status"] == "failed" and a["error"]["code"] == "UNSUPPORTED_CUBE" and "cube" in a["error"]["message"].lower()



