import io
import json

import imagecodecs
import numpy as np
from astropy.io import fits
from PIL import Image

from conftest import linear_field
from integration.test_jpeg_slice import default_recipe, ready, run_job, upload


def test_edit_export_uses_fits_target_and_does_not_change_master_exports(client, tmp_path):
    p = tmp_path / "test-m31.fits"
    original = fits.PrimaryHDU(linear_field(h=180, w=240, seed=4)[..., 0].astype(np.float32))
    original.header["OBJECT"] = "M 31"
    original.header["OBSERVER"] = "Not for export"
    original.writeto(p)
    asset = ready(client, upload(client, p)["id"])
    interpret = client.patch(f"/api/v1/assets/{asset['id']}/interpretation", json={"state": "linear"})
    assert interpret.status_code == 200 and ready(client, asset["id"])["status"] == "ready"
    job = run_job(client, [asset["id"]], default_recipe(client))
    run_id = job["items"][0]["run_id"]
    path = f"/api/v1/runs/{run_id}/edit-export"
    original_png = f"/api/v1/runs/{run_id}/exports/png"
    original_fits = f"/api/v1/runs/{run_id}/exports/fits"
    png_before = client.get(original_png).content
    fits_before = client.get(original_fits).content
    assert client.get(path + "/target").json() == {"target": "M 31"}

    frame = {"rotation": 90, "zoom": 2, "pan_x": 1, "pan_y": -1}
    plain = client.post(path, json=frame)
    assert plain.status_code == 200
    baseline = imagecodecs.png_decode(png_before)
    bare = imagecodecs.png_decode(plain.content)
    np.testing.assert_array_equal(bare, baseline[::-1].T[:120, -90:])

    opts = {**frame, "target": "M 31", "label": "Galaxy Photos"}
    result = client.post(path, json=opts)
    assert result.status_code == 200 and result.headers["content-type"] == "image/png"
    assert result.headers["content-disposition"].endswith('-edited.png"')
    edited = imagecodecs.png_decode(result.content)
    assert edited.shape == (120, 90) and edited.dtype == np.uint16
    np.testing.assert_array_equal(edited[:60], bare[:60])
    assert np.count_nonzero(edited[60:] != bare[60:]) > 50
    with Image.open(io.BytesIO(result.content)) as im:
        manifest = json.loads(im.info["EasyAstroEnhance"])
        assert manifest["target"] == "M 31" and manifest["label"] == "Galaxy Photos" and manifest["rotation"] == 90
        assert "Not for export" not in repr(im.info)
    jpeg = client.post(path, json={**opts, "format": "jpeg"})
    with Image.open(io.BytesIO(jpeg.content)) as im:
        assert im.format == "JPEG" and im.size == (90, 120)
        assert json.loads(im.info["comment"])["pan_x"] == 1
    assert client.post(path, json={"zoom": 0}).status_code == 422
    styled = client.post(path, json={**opts, "text_style": {"font": "script", "color": "#ffd080", "box": False},
                                     "target_place": {"position": "top-center", "size": 1.5}, "label_place": {"position": "bottom-right", "size": 0.8}})
    assert styled.status_code == 200
    with Image.open(io.BytesIO(styled.content)) as im:
        manifest = json.loads(im.info["EasyAstroEnhance"])
        assert manifest["text_style"]["font"] == "script" and manifest["target_place"]["position"] == "top-center"
    assert not np.array_equal(imagecodecs.png_decode(styled.content)[:60], bare[:60])  # the target name moved to the top
    assert client.post(path, json={**opts, "text_style": {"color": "red"}}).status_code == 422
    assert client.post(path, json={**opts, "label_place": {"position": "middle"}}).status_code == 422
    # No star catalog in the test data folder: annotations explain what to download and don't try to solve.
    objects = client.post(path + "/objects", json={}).json()
    assert objects["solve_needed"] is False and "star catalog" in objects["reason"]
    assert client.get(original_png).content == png_before and client.get(original_fits).content == fits_before
