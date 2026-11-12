"""Milestones 1-2 integration: upload a real JPEG, enhance, compare, download."""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pytest
from PIL import Image

from conftest import real_file, synthetic_field, wait_for, write_jpeg


def upload(client, path, name=None):
    with open(path, "rb") as fh:
        r = client.post("/api/v1/assets", files=[("files", (name or path.name, fh, "application/octet-stream"))])
    assert r.status_code == 200, r.text
    return r.json()["assets"][0]


def ready(client, asset_id):
    def check():
        a = client.get(f"/api/v1/assets/{asset_id}").json()
        return a if a["status"] in ("ready", "needs_input", "failed") else None

    return wait_for(check)


def run_job(client, asset_ids, recipe, key="req-key-0001", **kw):
    r = client.post("/api/v1/jobs", json={"request_key": key, "asset_ids": asset_ids, "recipe": recipe, **kw})
    assert r.status_code == 202, r.text
    jid = r.json()["id"]

    def done():
        j = client.get(f"/api/v1/jobs/{jid}").json()
        return j if j["state"] not in ("queued", "running") else None

    return wait_for(done, timeout=240)


def default_recipe(client, preset="natural"):
    for p in client.get("/api/v1/presets").json()["presets"]:
        if p["id"] == preset:
            return p["recipe"]
    raise AssertionError


def test_security_rejects_bad_host_origin_and_token(client):
    assert client.get("/api/v1/health", headers={"Host": "evil.example:8765"}).status_code == 400
    assert client.get("/api/v1/health", headers={"Origin": "http://evil.example"}).status_code == 403
    r = client.post("/api/v1/presets", json={"name": "x", "recipe": {}}, headers={"X-EAE-Token": "wrong"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "TOKEN_INVALID"
    assert client.get("/api/v1/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_upload_shows_real_thumbnail(client, tmp_path):
    arr, _ = synthetic_field()
    p = write_jpeg(tmp_path / "synthetic_test_field.jpg", arr)
    a = upload(client, p)
    assert a["status"] in ("inspecting", "ready")
    a = ready(client, a["id"])
    assert a["status"] == "ready" and a["width"] == 256 and a["height"] == 192 and a["channel_layout"] == "rgb"
    t = client.get(a["thumb_url"])
    assert t.status_code == 200 and t.headers["content-type"] == "image/jpeg"
    im = Image.open(io.BytesIO(t.content))
    assert max(im.size) <= 256 and im.size[0] / im.size[1] == pytest.approx(256 / 192, rel=0.05)


def test_original_bytes_unchanged_and_readonly(client, tmp_path):
    import hashlib

    arr, _ = synthetic_field()
    p = write_jpeg(tmp_path / "orig.jpg", arr)
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    a = ready(client, upload(client, p)["id"])
    stored = client.cfg.assets_dir / a["id"] / "original.jpg"
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == before == a["sha256"]
    run_job(client, [a["id"]], default_recipe(client))
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == before


def test_rejects_unknown_and_corrupt_files_individually(client, tmp_path):
    arr, _ = synthetic_field()
    good = write_jpeg(tmp_path / "good.jpg", arr)
    bad = tmp_path / "corrupt.jpg"
    bad.write_bytes(b"\xff\xd8\xff\xe0" + b"garbage" * 50)
    junk = tmp_path / "notes.txt"
    junk.write_text("hello")
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in (good, bad, junk)]
    r = client.post("/api/v1/assets", files=files)
    assets = r.json()["assets"]
    ids = {a["filename"]: a for a in assets}
    assert ids["notes.txt"]["status"] == "failed" and ids["notes.txt"]["error"]["code"] == "UNSUPPORTED_FORMAT"
    corrupt = ready(client, ids["corrupt.jpg"]["id"])
    assert corrupt["status"] == "failed"
    assert ready(client, ids["good.jpg"]["id"])["status"] == "ready"


def test_enhance_end_to_end_and_exports(client, tmp_path):
    arr, _ = synthetic_field()
    p = write_jpeg(tmp_path / "field.jpg", arr)
    a = ready(client, upload(client, p)["id"])
    job = run_job(client, [a["id"]], default_recipe(client))
    item = job["items"][0]
    assert item["state"] in ("succeeded", "succeeded_with_notes"), item.get("error")
    run = client.get(f"/api/v1/runs/{item['run_id']}").json()
    assert run["summary"] and run["applied"]["clipping"]["guard_action"] in ("none", "reduced", "needs_review")
    png = client.get(f"/api/v1/runs/{run['id']}/exports/png")
    assert png.status_code == 200
    dec = np.asarray(Image.open(io.BytesIO(png.content)))
    assert dec.shape == (192, 256, 3)  # full-resolution master, not a preview
    base = np.asarray(Image.open(p))
    assert not np.array_equal(dec, base)
    rep = client.get(f"/api/v1/runs/{run['id']}/exports/report").json()
    assert rep["applied"]["source"]["sha256"] == a["sha256"] and rep["applied"]["engine_version"]
    # identical settings: duplicate request is idempotent and reuses work
    r2 = client.post("/api/v1/jobs", json={"request_key": "req-key-0001", "asset_ids": [a["id"]], "recipe": default_recipe(client)})
    assert r2.json()["idempotent_replay"] is True
    # previews & ROI at identical geometry
    pa = client.get(a["preview_url"])
    pr = client.get(run["preview_url"])
    assert Image.open(io.BytesIO(pa.content)).size == Image.open(io.BytesIO(pr.content)).size
    roi = client.get(run["preview_url"], params={"x": 10, "y": 20, "w": 64, "h": 48})
    assert Image.open(io.BytesIO(roi.content)).size == (64, 48) and roi.headers["X-Preview-Downsampled"] == "0"


@pytest.mark.realfiles
def test_real_jpeg_vertical_slice(client):
    p = real_file("*M 31*.JPG")
    if p is None:
        pytest.skip("real JPEG not present in samplepics/")
    a = ready(client, upload(client, p)["id"])
    assert a["status"] == "ready" and (a["width"], a["height"]) == (1080, 1080)
    job = run_job(client, [a["id"]], default_recipe(client, "brighter-detail"))
    item = job["items"][0]
    assert item["state"] in ("succeeded", "succeeded_with_notes"), item.get("error")
    png = client.get(f"/api/v1/runs/{item['run_id']}/exports/png").content
    assert np.asarray(Image.open(io.BytesIO(png))).shape == (1080, 1080, 3)

