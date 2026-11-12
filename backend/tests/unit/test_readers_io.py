"""I/O tests. Synthetic TIFF/FITS here are labelled TEST FIXTURES for unit tests only."""
from __future__ import annotations

import numpy as np
import pytest
import tifffile
from astropy.io import fits
from PIL import Image, ImageOps

from app.processing.export import write_fits
from app.processing.imagedata import ProcessingError
from app.processing.readers import evaluate_intake, inspect_file, read_image
from app.processing.readers.common import apply_orientation, detect_format, sha256_file
from app.processing.readers.jpeg import read_jpeg
from app.processing.readers.tiff import read_tiff
from app.processing.readers.fits import read_fits

LIMIT = 100_000_000


def load(path, interp=None, preview_state="rendered"):
    insp = inspect_file(path, LIMIT)
    return read_image(path, sha256_file(path), LIMIT, interp or {}, insp, preview_only_state=preview_state), insp


# ----------------------------------------------------------------------------------- orientation / JPEG
@pytest.mark.parametrize("orientation", range(1, 9))
def test_numpy_orientation_matches_pillow(orientation, tmp_path):
    rng = np.random.default_rng(orientation)
    arr = rng.integers(0, 255, (13, 21, 3), dtype=np.uint8)
    im = Image.fromarray(arr)
    exif = Image.Exif()
    exif[0x0112] = orientation
    p = tmp_path / "o.jpg"
    im.save(p, "PNG" if False else "JPEG", quality=100, subsampling=0, exif=exif)
    expected = np.asarray(ImageOps.exif_transpose(Image.open(p)))
    raw = np.asarray(Image.open(p))
    assert np.array_equal(apply_orientation(raw, orientation), expected)
    img = read_jpeg(p, sha256_file(p), LIMIT)  # applied exactly once, documented
    assert np.array_equal(np.rint(img.pixels * 255).astype(np.uint8), expected)
    assert "applied once" in img.orientation_transform
    insp = inspect_file(p, LIMIT)
    assert (insp["width"], insp["height"]) == (expected.shape[1], expected.shape[0])


def test_cmyk_jpeg_is_rejected_not_cast(tmp_path):
    p = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (16, 16), (10, 20, 30, 40)).save(p, "JPEG")
    with pytest.raises(ProcessingError) as e:
        inspect_file(p, LIMIT)
    assert e.value.code == "UNSUPPORTED_COLOR_MODE"


def test_signature_not_extension(tmp_path):
    p = tmp_path / "fake.jpg"
    p.write_bytes(b"not an image at all")
    with pytest.raises(ProcessingError) as e:
        detect_format(p)
    assert e.value.code == "UNSUPPORTED_FORMAT"


def test_pixel_limit_enforced_from_headers(tmp_path):
    p = tmp_path / "big.jpg"
    Image.new("RGB", (400, 300)).save(p, "JPEG")
    with pytest.raises(ProcessingError) as e:
        inspect_file(p, 100_000)
    assert e.value.code == "IMAGE_TOO_LARGE"


# ----------------------------------------------------------------------------------- TIFF
def test_uint16_tiff_round_trip_preserves_values_linear_and_rendered(tmp_path):
    rng = np.random.default_rng(3)
    raw = rng.integers(0, 65536, (40, 60, 3), dtype=np.uint16)
    p = tmp_path / "t16.tif"
    tifffile.imwrite(p, raw, photometric="rgb")
    insp = inspect_file(p, LIMIT)
    assert insp["bit_depth"] == 16 and insp["dtype"] == "uint16" and insp["channel_layout"] == "rgb"
    assert insp["questions"][0]["id"] == "state"  # state is never inferred
    lin = read_tiff(p, "h", LIMIT, "linear")
    assert lin.domain == "linear" and lin.pixels.dtype == np.float32
    assert np.array_equal(lin.pixels.astype(np.uint16), raw)  # exact integers, no 8-bit conversion
    rend = read_tiff(p, "h", LIMIT, "rendered")
    assert rend.domain == "display" and np.array_equal(np.rint(rend.pixels.astype(np.float64) * 65535).astype(np.uint16), raw)
    assert rend.normalization.scale == 65535.0


def test_float32_tiff_and_planar_layout(tmp_path):
    rng = np.random.default_rng(4)
    arr = rng.normal(100, 10, (3, 30, 40)).astype(np.float32)
    arr[0, 0, 0] = np.nan
    p = tmp_path / "f32.tif"
    tifffile.imwrite(p, arr, photometric="rgb", planarconfig="separate")
    img = read_tiff(p, "h", LIMIT, "linear")
    assert img.pixels.shape == (30, 40, 3) and not img.valid_mask[0, 0] and img.valid_mask.sum() == 30 * 40 - 1
    assert np.array_equal(img.pixels[1:, :, :], np.moveaxis(arr, 0, -1)[1:, :, :])
    assert img.pixels[0, 0, 0] == 0  # masked, never a dark star surrogate in the mask


@pytest.mark.parametrize("make, code", [
    (lambda p: tifffile.imwrite(p, np.zeros((8, 8, 4), np.uint8), photometric="rgb", extrasamples=["unassalpha"]), "ALPHA_NOT_SUPPORTED"),
    (lambda p: tifffile.imwrite(p, np.zeros((8, 8), np.int16)), "UNSUPPORTED_SAMPLE_TYPE"),
    (lambda p: tifffile.imwrite(p, np.zeros((8, 8), np.float64)), "UNSUPPORTED_SAMPLE_TYPE"),
])
def test_unsupported_tiff_explained(tmp_path, make, code):
    p = tmp_path / "x.tif"
    make(p)
    with pytest.raises(ProcessingError) as e:
        inspect_file(p, LIMIT)
    assert e.value.code == code and e.value.message


def test_multipage_tiff_is_intake_only(tmp_path):
    p = tmp_path / "multi.tif"
    with tifffile.TiffWriter(p) as tw:
        tw.write(np.zeros((8, 8), np.uint16))
        tw.write(np.ones((8, 8), np.uint16))
    with pytest.raises(ProcessingError) as e:
        inspect_file(p, LIMIT)
    assert e.value.code == "MULTIPAGE_TIFF"


# ----------------------------------------------------------------------------------- FITS
def write_scaled_int16(path):
    data = np.arange(12 * 10, dtype=np.int16).reshape(12, 10) - 40
    hdu = fits.PrimaryHDU(data=data)
    hdu.header["BSCALE"] = 0.5
    hdu.header["BZERO"] = 100.0
    hdu.header["BLANK"] = -40
    hdu.header["BUNIT"] = "adu"
    hdu.writeto(path, overwrite=True)
    return data


def test_bscale_bzero_applied_exactly_once_and_blank_masked(tmp_path):
    p = tmp_path / "scaled.fits"
    raw = write_scaled_int16(p)
    img = read_fits(p, "h", LIMIT, "linear")
    # flipped once for display; undo for comparison
    phys = img.pixels[::-1].astype(np.float64)
    expected = raw * 0.5 + 100.0
    ok = img.valid_mask[::-1]
    assert np.allclose(phys[ok], expected[ok])  # scaled once (not 0.25x or 2x)
    assert not ok[0, 0] and (~ok).sum() == 1  # the BLANK pixel is masked
    sc = img.metadata["fits"]["scaling"]
    assert sc["bscale"] == 0.5 and sc["bzero"] == 100.0 and sc["blank"] == -40  # original scaling recorded


def test_float_fits_nan_and_negative_retained(tmp_path):
    data = np.random.default_rng(5).normal(0, 5, (20, 30)).astype(np.float32)
    data[3, 4] = np.nan
    p = tmp_path / "neg.fits"
    fits.PrimaryHDU(data=data).writeto(p)
    img = read_fits(p, "h", LIMIT, "linear")
    assert (img.pixels < 0).any() and not img.valid_mask[::-1][3, 4] and img.pixels.dtype == np.float32


def test_fits_layout_decisions(tmp_path):
    def save(name, data, **hdr):
        h = fits.PrimaryHDU(data=data)
        for k, v in hdr.items():
            h.header[k] = v
        p = tmp_path / name
        h.writeto(p)
        return p

    z = np.zeros
    rgb_doc = save("rgb_doc.fits", z((3, 16, 20), np.float32), CTYPE3="RGB")
    ins = inspect_file(rgb_doc, LIMIT)
    assert ins["channel_layout"] == "rgb" and not any(q["id"] == "layout" for q in evaluate_intake(ins, {"state": "linear"})["questions"])
    assert read_fits(rgb_doc, "h", LIMIT, "linear").pixels.shape == (16, 20, 3)

    rgb_undoc = save("rgb_undoc.fits", z((3, 16, 20), np.float32))
    ins = inspect_file(rgb_undoc, LIMIT)
    ev = evaluate_intake(ins, {"state": "linear"})
    assert [q["id"] for q in ev["questions"]] == ["layout"] and ev["status"] == "needs_input"  # never assume 3 = RGB
    with pytest.raises(ProcessingError) as e:
        read_fits(rgb_undoc, "h", LIMIT, "linear")
    assert e.value.code == "AMBIGUOUS_LAYOUT"
    assert evaluate_intake(ins, {"state": "linear", "layout": "not_rgb"})["status"] == "unsupported"
    assert read_fits(rgb_undoc, "h", LIMIT, "linear", layout="rgb_planes").pixels.shape == (16, 20, 3)

    cube = save("cube.fits", z((4, 16, 20), np.float32))
    with pytest.raises(ProcessingError) as e:
        inspect_file(cube, LIMIT)
    assert e.value.code == "UNSUPPORTED_CUBE"
    spectral = save("spectral.fits", z((3, 16, 20), np.float32), CTYPE3="VRAD")
    with pytest.raises(ProcessingError) as e:
        inspect_file(spectral, LIMIT)
    assert e.value.code == "UNSUPPORTED_CUBE"

    cfa = save("cfa.fits", z((16, 20), np.uint16), BAYERPAT="GRBG")
    with pytest.raises(ProcessingError) as e:
        inspect_file(cfa, LIMIT)
    assert e.value.code == "UNSUPPORTED_CFA" and "debayering or stacking" in e.value.message

    degenerate = save("degenerate.fits", z((1, 1, 16, 20), np.float32))
    assert inspect_file(degenerate, LIMIT)["channel_layout"] == "mono"
    assert read_fits(degenerate, "h", LIMIT, "linear").pixels.shape == (16, 20)


def test_multi_hdu_intake_and_selection(tmp_path):
    p = tmp_path / "multi.fits"
    fits.HDUList([
        fits.PrimaryHDU(),
        fits.ImageHDU(np.ones((10, 12), np.float32), name="SCI"),
        fits.ImageHDU(np.ones((8, 9), np.float32), name="ERR"),
    ]).writeto(p)
    ins = inspect_file(p, LIMIT)
    ev = evaluate_intake(ins, {"state": "linear"})
    assert [q["id"] for q in ev["questions"]] == ["hdu"] and not ev["can_preview"]
    ev2 = evaluate_intake(ins, {"state": "linear", "hdu": 2})
    assert ev2["status"] == "ready"
    img = read_image(p, "h", LIMIT, {"state": "linear", "hdu": 2}, ins)
    assert img.pixels.shape == (8, 9)


def test_unknown_state_blocks_processing_but_allows_labeled_preview(tmp_path):
    p = tmp_path / "m.fits"
    fits.PrimaryHDU(np.ones((10, 12), np.float32)).writeto(p)
    ins = inspect_file(p, LIMIT)
    assert evaluate_intake(ins, {})["can_process"] is False
    unsure = evaluate_intake(ins, {"state": "unsure"})
    assert unsure["status"] == "needs_input" and unsure["can_preview"] and not unsure["can_process"] and "Preview only" in unsure["message"]


def test_fits_float_export_round_trip_and_header_hygiene(tmp_path):
    rng = np.random.default_rng(9)
    data = rng.normal(50, 5, (3, 24, 30)).astype(np.float32)
    data[1, 2, 3] = np.nan
    h = fits.PrimaryHDU(data=data)
    h.header["CTYPE3"] = "RGB"
    h.header["CRVAL1"] = 12.5
    h.header["CTYPE1"] = "RA---TAN"
    h.header["BUNIT"] = "adu"
    h.header["DATAMIN"] = -1.0
    h.header["DATAMAX"] = 1.0
    h.header["OBSERVER"] = "Jane Doe"
    h.header["SITELAT"] = 12.34
    h.header["OBJECT"] = "synthetic"
    src = tmp_path / "src.fits"
    h.writeto(src)
    img, _ = load(src, {"state": "linear"})
    out = tmp_path / "out.fits"
    info = write_fits(out, img, img.pixels, "processed-linear", "natural", strip_sensitive=True)
    with fits.open(out) as hd:
        assert hd[0].data.shape == (3, 24, 30) and hd[0].data.dtype == np.dtype(">f4")
        rt = hd[0].data
        keep = np.ones((24, 30), bool); keep[2, 3] = False  # validity is per pixel (all channels masked together)
        np.testing.assert_allclose(rt[0][keep], data[0][keep], rtol=1e-6)
        assert np.isnan(rt[1, 2, 3])  # invalid mask preserved on output
        hdr = hd[0].header
        for stale in ("BSCALE", "BZERO", "BLANK", "DATAMIN", "DATAMAX", "BUNIT"):
            assert stale not in hdr
        assert "OBSERVER" not in hdr and "SITELAT" not in hdr  # stripped by default
        assert hdr["CTYPE1"] == "RA---TAN" and hdr["CRVAL1"] == 12.5 and hdr["OBJECT"] == "synthetic"  # WCS/observing metadata kept
        assert hdr["EAEKIND"] == "processed-linear" and hdr["EAESHA"] == img.source_hash
        assert "CHECKSUM" in hdr and "DATASUM" in hdr
    out2 = tmp_path / "out_full.fits"
    write_fits(out2, img, img.pixels, "processed-linear", "natural", strip_sensitive=False)
    with fits.open(out2) as hd:
        assert hd[0].header["OBSERVER"] == "Jane Doe"  # explicit full-metadata export


def test_fits_row_flip_round_trips_array_order(tmp_path):
    data = np.arange(20 * 30, dtype=np.float32).reshape(20, 30)
    src = tmp_path / "s.fits"
    fits.PrimaryHDU(data).writeto(src)
    img, _ = load(src, {"state": "linear"})
    assert np.array_equal(img.pixels, data[::-1]) and img.flip_rows_on_export
    out = tmp_path / "o.fits"
    write_fits(out, img, img.pixels, "processed-linear", "x")
    with fits.open(out) as hd:
        assert np.array_equal(hd[0].data, data)  # file array order restored; WCS stays consistent
    src2 = tmp_path / "td.fits"
    h = fits.PrimaryHDU(data)
    h.header["ROWORDER"] = "TOP-DOWN"
    h.writeto(src2)
    assert np.array_equal(load(src2, {"state": "linear"})[0].pixels, data)


