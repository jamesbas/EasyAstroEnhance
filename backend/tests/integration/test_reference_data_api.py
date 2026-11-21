"""Reference data API (star and object catalogs): status, verified download of a group (file:// stand-ins), rejection of
a corrupted file, removal, and what the catalogs are used for once installed."""
from __future__ import annotations

import dataclasses
import hashlib

import pytest

from app.processing.catalogs import registry
from conftest import wait_for


@pytest.fixture()
def fake_reference(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    for key, spec in list(registry.DATA.items()):
        data = f"stand-in {key}".encode() * 40
        p = src / spec.file
        p.write_bytes(data)
        monkeypatch.setitem(registry.DATA, key, dataclasses.replace(spec, url=p.as_uri(), size=len(data), sha256=hashlib.sha256(data).hexdigest()))
    return src


def _group(client, g):
    return client.get("/api/v1/reference-data").json()["groups"][g]


def test_catalog_group_downloads_verified_and_can_be_removed(client, fake_reference):
    o = client.get("/api/v1/reference-data").json()
    assert {i["id"] for i in o["items"]} == set(registry.DATA) and all(i["license"] and i["attribution"] for i in o["items"])
    assert o["groups"]["objects"]["state"] == "missing" and o["groups"]["objects"]["available"]
    assert client.post("/api/v1/reference-data/objects/download").status_code == 202
    wait_for(lambda: _group(client, "objects")["state"] == "installed", timeout=30)
    assert registry.group_ready(client.cfg.reference_data_dir, "objects") and not registry.group_ready(client.cfg.reference_data_dir, "stars")
    assert client.request("DELETE", "/api/v1/reference-data/objects").status_code == 200
    assert _group(client, "objects")["state"] == "missing"
    assert client.post("/api/v1/reference-data/nothing/download").status_code == 404


def test_corrupted_catalog_is_discarded_and_unpublished_catalogs_are_refused(client, fake_reference, monkeypatch):
    bad = dataclasses.replace(registry.DATA["stars-gaia-dr3"], sha256="0" * 64)
    monkeypatch.setitem(registry.DATA, "stars-gaia-dr3", bad)
    client.post("/api/v1/reference-data/stars/download")
    item = wait_for(lambda: next((i for i in client.get("/api/v1/reference-data").json()["items"]
                                  if i["id"] == "stars-gaia-dr3" and i["state"] == "error"), None), timeout=30)
    assert "SHA-256" in item["error"]
    assert not registry.group_ready(client.cfg.reference_data_dir, "stars")
    monkeypatch.setitem(registry.DATA, "stars-gaia-dr3", dataclasses.replace(bad, sha256=""))
    assert client.post("/api/v1/reference-data/stars/download").status_code == 409


def test_edit_export_finds_the_sky_position_itself_once_the_star_catalog_is_installed(client, fake_reference, tmp_path):
    """Annotations ask the dialog to solve (no trip to Advanced) only when it can work; a failed attempt is kept with the
    image, is not retried and says what to do instead."""
    import json
    import sqlite3

    import numpy as np
    from astropy.io import fits

    from conftest import linear_field
    from integration.test_jpeg_slice import default_recipe, ready, run_job, upload

    path = tmp_path / "field.fits"
    fits.PrimaryHDU(linear_field(h=120, w=160, seed=2)[..., 0].astype(np.float32)).writeto(path)
    asset = ready(client, upload(client, path)["id"])
    client.patch(f"/api/v1/assets/{asset['id']}/interpretation", json={"state": "linear"})
    ready(client, asset["id"])
    run_id = run_job(client, [asset["id"]], default_recipe(client))["items"][0]["run_id"]

    def objects():
        return client.post(f"/api/v1/runs/{run_id}/edit-export/objects", json={}).json()

    assert objects()["solve_needed"] is False and "star catalog" in objects()["reason"]
    assert client.post("/api/v1/reference-data/stars/download").status_code == 202
    wait_for(lambda: _group(client, "stars")["state"] == "installed", timeout=30)
    o = objects()
    assert o["solve_needed"] is True and not o["compass_available"]

    db = sqlite3.connect(client.cfg.data_dir / "app.db")
    sha, interp = db.execute("SELECT sha256, interpretation FROM assets WHERE id=?", (asset["id"],)).fetchone()
    db.close()
    failed = {"status": "unavailable", "reason": "Only 4 stars were detected; at least 10 are needed to solve.",
              "hdu": json.loads(interp).get("hdu"), "source_sha256": sha}
    (client.cfg.assets_dir / asset["id"] / "sky-solution.json").write_text(json.dumps(failed), encoding="utf-8")
    o = objects()
    assert o["solve_needed"] is False and "Only 4 stars" in o["reason"] and "Sky position" in o["reason"]
