from hashlib import sha256

import pytest
import numpy as np
from astropy.io import fits
from PIL import Image
import io

from color_fixtures import CATALOG_GAINS, color_test_files
from test_jpeg_slice import default_recipe, ready, run_job, upload


def add_linear(client, path):
    a = ready(client, upload(client, path)["id"])
    r = client.patch(f"/api/v1/assets/{a['id']}/interpretation", json={"state": "linear"})
    assert r.is_success, r.text
    a = ready(client, a["id"])
    assert a["status"] == "ready"
    return a


def test_color_workflow_on_solved_fits(client, tmp_path):
    files = color_test_files(tmp_path)
    a = add_linear(client, files["rgb"])
    import_route = "/api/v1/assets/color-catalog"
    assert client.post(import_route, files={"file": ("bad.csv", b"r,g,b\n")}).status_code == 422
    csv = files["csv"].read_bytes()
    imported = client.post(import_route, files={"file": ("ref.csv", csv)})
    assert imported.is_success, imported.text
    digest = imported.json()["sha256"]
    assert digest == sha256(csv).hexdigest()
    preview = client.post(f"/api/v1/assets/{a['id']}/object-color-preview?mask=true", json={"blues": 1})
    assert preview.is_success, preview.text
    mask = Image.open(io.BytesIO(preview.content))
    assert mask.mode == "L" and mask.getextrema()[1] > 40 and mask.getextrema()[0] == 0
    recipe = default_recipe(client)
    recipe["catalog_sha256"] = digest
    recipe["object_color"]["blues"] = 0.7
    recipe["focus_stretch"]["enabled"] = True
    job = run_job(client, [a["id"]], recipe, key="color-fit-001")
    item = job["items"][0]
    assert item["run_id"], job
    applied = client.get(f"/api/v1/runs/{item['run_id']}/exports/report").json()["applied"]
    ops = {op["name"]: op for op in applied["operations"]}
    assert ops["catalog_color"]["status"] == "applied", ops["catalog_color"]
    assert ops["catalog_color"]["gains_rgb"] == pytest.approx(CATALOG_GAINS, rel=0.03)
    assert ops["object_color"]["status"] in ("applied", "reduced")
    assert ops["focus_stretch"]["status"] == "applied"
    assert applied["enhanced_frame"]["d_source"] == "manual-focus"
    assert applied["execution"]["actual_backend"] == "cpu"
    recipe["catalog_sha256"] = "0" * 64
    job = run_job(client, [a["id"]], recipe, key="color-fallback-001")
    run = job["items"][0]["run_id"]
    operations = client.get(f"/api/v1/runs/{run}/exports/report").json()["applied"]["operations"]
    failed = next(o for o in operations if o["name"] == "catalog_color")
    assert failed["status"] == "skipped" and "unavailable" in failed["reason"] and failed["fallback"] == "applied"


def test_mix_publishes_new_linear_asset_without_touching_input(client, tmp_path):
    p = color_test_files(tmp_path)
    sources = [add_linear(client, p[key]) for key in ("ha", "oiii")]
    body = {"asset_ids": [a["id"] for a in sources], "mode": "HOO", "gains": [1, 1]}
    created = client.post("/api/v1/assets/color-mix", json=body)
    assert created.status_code == 201, created.text
    mixed = ready(client, created.json()["id"])
    assert mixed["status"] == "ready" and mixed["channel_layout"] == "rgb" and not mixed["latest_run"]
    for a in sources:
        assert sha256((client.cfg.assets_dir / a["id"] / "original.fits").read_bytes()).hexdigest() == a["sha256"]
    header = fits.getheader(client.cfg.assets_dir / mixed["id"] / "original.fits")
    assert header["EAEMIX"] == "HOO" and "SHA256" in str(header["HISTORY"])
    recipe = default_recipe(client)
    recipe["catalog_sha256"] = "0" * 64
    run = run_job(client, [mixed["id"]], recipe, key="mixed-narrow-001")["items"][0]["run_id"]
    operations = client.get(f"/api/v1/runs/{run}/exports/report").json()["applied"]["operations"]
    ops = {o["name"]: o for o in operations}
    assert "narrowband" in ops["white_balance"]["reason"]
    assert "narrowband" in ops["green_removal"]["reason"]
    assert ops["catalog_color"]["status"] == "skipped"


def test_hubble_palette_applies_only_to_the_display_of_confirmed_dualband(client, tmp_path):
    p = color_test_files(tmp_path)
    rgb = add_linear(client, p["dualband"])
    ircut = add_linear(client, p["broadband"])
    unknown = add_linear(client, p["rgb"])
    assert [a["hubble_input"] for a in (rgb, ircut, unknown)] == ["dualband", "broadband", "unknown"]

    def confirm(asset, enabled):
        return client.patch(f"/api/v1/assets/{asset['id']}/interpretation", json={"dualband_confirmed": enabled})

    assert confirm(ircut, True).status_code == 422
    assert confirm(unknown, True).json()["hubble_input"] == "dualband"
    assert confirm(unknown, False).json()["hubble_input"] == "unknown"

    def preview(asset):
        return client.post(f"/api/v1/assets/{asset['id']}/object-color-preview?hubble_strength=0.65", json={})

    assert preview(ircut).status_code == preview(unknown).status_code == 422
    assert Image.open(io.BytesIO(preview(rgb).content)).mode == "RGB"
    recipe = default_recipe(client)
    normal, normal_ircut = [item["run_id"] for item in run_job(client, [rgb["id"], ircut["id"]], recipe, key="hubble-off-01")["items"]]
    recipe["hubble_strength"] = 0.65
    styled, blocked = [item["run_id"] for item in run_job(client, [rgb["id"], ircut["id"]], recipe, key="hubble-on-01")["items"]]

    def export(run, kind):
        return client.get(f"/api/v1/runs/{run}/exports/{kind}")

    def data(run, kind):
        response = export(run, kind)
        assert response.is_success
        return response.content

    def operation(run):
        return next(o for o in export(run, "report").json()["applied"]["operations"] if o["name"] == "hubble_style")

    assert operation(styled)["status"] == "applied"
    assert operation(blocked)["status"] == "skipped" and "Broadband" in operation(blocked)["reason"]
    assert data(styled, "png") != data(normal, "png")
    assert data(blocked, "png") == data(normal_ircut, "png")
    np.testing.assert_array_equal(fits.getdata(io.BytesIO(data(styled, "fits"))),
                                  fits.getdata(io.BytesIO(data(normal, "fits"))))
