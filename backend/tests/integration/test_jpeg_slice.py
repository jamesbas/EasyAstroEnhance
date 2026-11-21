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
    from app.processing.recipe import PIPELINE_VERSION, RECIPE_SCHEMA_VERSION

    s = client.get("/api/v1/session").json()
    assert s["version"] == PIPELINE_VERSION and s["recipe_schema"] == RECIPE_SCHEMA_VERSION and s["stack_version"]  # shown in the UI header and Settings
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


def test_display_tiff_is_rendered_on_request_with_the_stored_values(client, tmp_path):
    import hashlib

    import tifffile

    arr, _ = synthetic_field(seed=21)
    a = ready(client, upload(client, write_jpeg(tmp_path / "lazy.jpg", arr))["id"])
    run_id = run_job(client, [a["id"]], default_recipe(client), key="lazy-tiff-01")["items"][0]["run_id"]
    entry = next(e for e in client.get(f"/api/v1/runs/{run_id}").json()["exports"] if e["kind"] == "tiff")
    run_dir = client.cfg.runs_dir / run_id
    assert entry["deferred"] and entry["bytes"] is None and not (run_dir / entry["filename"]).exists()
    r = client.get(f"/api/v1/runs/{run_id}/exports/tiff")
    assert r.status_code == 200
    assert np.array_equal(tifffile.imread(io.BytesIO(r.content)), np.load(run_dir / "display.npy"))  # = quantize(display, 16)
    entry = next(e for e in client.get(f"/api/v1/runs/{run_id}").json()["exports"] if e["kind"] == "tiff")
    assert entry["sha256"] == hashlib.sha256(r.content).hexdigest() and entry["bytes"] == len(r.content)
    assert client.get(f"/api/v1/runs/{run_id}/exports/tiff").content == r.content  # rendered once, then served


def test_retention_keeps_the_newest_results_per_image(client, tmp_path):
    arr, _ = synthetic_field(seed=22)
    a = ready(client, upload(client, write_jpeg(tmp_path / "keep.jpg", arr))["id"])
    assert client.get("/api/v1/settings").json()["keep_runs_per_image"] == 0  # default: keep everything
    first = run_job(client, [a["id"]], default_recipe(client), key="keep-run-01")["items"][0]["run_id"]
    assert client.patch("/api/v1/settings", json={"keep_runs_per_image": 1}).json()["keep_runs_per_image"] == 1
    second = run_job(client, [a["id"]], default_recipe(client), key="keep-run-02", force=True)["items"][0]["run_id"]
    runs = [r["id"] for r in client.get("/api/v1/runs", params={"asset_id": a["id"]}).json()["runs"]]
    assert runs == [second] and not (client.cfg.runs_dir / first).exists()
    assert client.get(f"/api/v1/runs/{first}").status_code == 404
    assert client.get(f"/api/v1/assets/{a['id']}").json()["latest_run"]["id"] == second


def test_going_back_to_an_earlier_result_and_deleting_results(client, tmp_path):
    arr, _ = synthetic_field(seed=23)
    a = ready(client, upload(client, write_jpeg(tmp_path / "back.jpg", arr))["id"])
    asset = lambda: client.get(f"/api/v1/assets/{a['id']}").json()  # noqa: E731
    natural = run_job(client, [a["id"]], default_recipe(client, "natural"), key="back-run-01")["items"][0]["run_id"]
    vivid = run_job(client, [a["id"]], default_recipe(client, "vivid"), key="back-run-02")["items"][0]["run_id"]
    assert asset()["latest_run"]["id"] == vivid  # the newest result is current

    # Go back: the earlier result becomes the one shown and downloaded; nothing is reprocessed or deleted.
    r = client.put(f"/api/v1/assets/{a['id']}/current-run", json={"run_id": natural})
    assert r.status_code == 200 and r.json()["latest_run"]["id"] == natural and r.json()["run_count"] == 2
    assert client.put(f"/api/v1/assets/{a['id']}/current-run", json={"run_id": "run_nope"}).status_code == 404

    # Enhancing again with identical settings reuses a result: the reused one becomes current.
    item = run_job(client, [a["id"]], default_recipe(client, "vivid"), key="back-run-03")["items"][0]
    assert item["run_id"] == vivid and asset()["latest_run"]["id"] == vivid

    # Deleting the current result: the newest remaining one takes over; run numbers keep counting.
    r = client.request("DELETE", f"/api/v1/runs/{vivid}")
    assert r.status_code == 200 and r.json()["current_run_id"] == natural
    assert not (client.cfg.runs_dir / vivid).exists() and client.get(f"/api/v1/runs/{vivid}").status_code == 404
    assert asset()["latest_run"]["id"] == natural and asset()["run_count"] == 1
    third = run_job(client, [a["id"]], default_recipe(client, "faint-detail"), key="back-run-04")["items"][0]["run_id"]
    serials = sorted(x["serial"] for x in client.get("/api/v1/runs", params={"asset_id": a["id"]}).json()["runs"])
    assert serials == [1, 3] and asset()["latest_run"]["id"] == third
    assert client.request("DELETE", "/api/v1/runs/run_nope").status_code == 404


def test_live_preview_is_exactly_what_enhance_publishes(client, tmp_path):
    arr, _ = synthetic_field(seed=24)
    a = ready(client, upload(client, write_jpeg(tmp_path / "live.jpg", arr))["id"])
    run_job(client, [a["id"]], default_recipe(client, "natural"), key="live-base-01")
    vivid = default_recipe(client, "vivid")

    def finished():
        s = client.get(f"/api/v1/assets/{a['id']}/live-preview").json()
        return s if s["state"] in ("ready", "failed", "cancelled") else None

    started = client.post(f"/api/v1/assets/{a['id']}/live-preview", json={"recipe": vivid})
    assert started.status_code == 202 and started.json()["state"] in ("queued", "running")
    st = wait_for(finished)
    assert st["state"] == "ready" and st["recipe"]["preset"] == "vivid" and st["summary"]
    assert st["reused"] is True  # natural and vivid share the linear stage, so only the display stage ran
    img = client.get(st["preview_url"])
    assert img.status_code == 200 and img.headers["X-Source-Width"] == "256"
    live = np.load(client.cfg.tmp_dir / "live" / a["id"] / f"{st['id']}.npy")
    run_id = run_job(client, [a["id"]], vivid, key="live-save-01")["items"][0]["run_id"]
    assert np.array_equal(np.load(client.cfg.runs_dir / run_id / "display.npy"), live)
    report = client.get(f"/api/v1/runs/{run_id}/exports/report").json()["applied"]
    assert report["linear_stage_cache"]["display_reused"] is True
    # a newer request supersedes an older one; deleting the image removes its previews
    client.post(f"/api/v1/assets/{a['id']}/live-preview", json={"recipe": default_recipe(client, "natural")})
    assert wait_for(finished)["recipe"]["preset"] == "natural"
    client.delete(f"/api/v1/assets/{a['id']}")
    assert not (client.cfg.tmp_dir / "live" / a["id"]).exists()


def test_preset_previews_render_quick_looks_and_auto_reports_its_choice(client, tmp_path):
    arr, _ = synthetic_field(seed=25)
    a = ready(client, upload(client, write_jpeg(tmp_path / "pp.jpg", arr))["id"])
    items = [{"id": p, "recipe": default_recipe(client, p)} for p in ("auto", "natural", "vivid")]
    r = client.post(f"/api/v1/assets/{a['id']}/preset-previews", json={"items": items})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [i["id"] for i in out["items"]] == ["auto", "natural", "vivid"] and out["note"]
    assert out["items"][0]["auto"] and out["items"][1]["auto"] is None  # Auto names the preset it chose
    first = client.get(out["items"][1]["url"])
    assert first.status_code == 200 and first.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(first.content)).size) <= 480
    again = client.post(f"/api/v1/assets/{a['id']}/preset-previews", json={"items": items[1:2]}).json()
    assert again["items"][0]["file"] == out["items"][1]["file"]  # same settings: the cached thumbnail is reused
    assert client.get(f"/api/v1/assets/{a['id']}/files/presetprev-..%2Fx.jpg").status_code == 404


def test_folder_browse_lists_fits_counts_read_only(client, tmp_path):
    root = tmp_path / "MyWorks"
    (root / "M 42_sub").mkdir(parents=True)
    (root / "M 31").mkdir()
    for i in range(3):
        (root / "M 42_sub" / f"Light_{i}.fit").write_bytes(b"")
    before = sorted(p.name for p in root.rglob("*"))
    listing = client.post("/api/v1/stacks/browse", json={"path": str(root)}).json()
    by_name = {f["name"]: f for f in listing["folders"]}
    assert by_name["M 42_sub"]["fits"] == 3 and by_name["M 42_sub"]["is_sub"] and not by_name["M 31"]["is_sub"]
    assert listing["parent"] == str(tmp_path)
    assert client.post("/api/v1/stacks/browse", json={"path": str(root / "missing")}).json()["error"]
    top = client.post("/api/v1/stacks/browse", json={"path": None}).json()
    assert top["path"] is None and top["folders"]
    assert sorted(p.name for p in root.rglob("*")) == before
    assert client.post("/api/v1/stacks/browse", json={"path": str(root)}, headers={"X-EAE-Token": "bad"}).status_code == 403


def test_zip_build_can_be_cancelled(client, tmp_path):
    from app.db import new_id, now
    from app.services import exports

    arr, _ = synthetic_field(seed=23)
    a = ready(client, upload(client, write_jpeg(tmp_path / "zip.jpg", arr))["id"])
    run_id = run_job(client, [a["id"]], default_recipe(client), key="zip-cancel-1")["items"][0]["run_id"]
    db = client.app.state.db
    export_id = new_id("zip_")
    db.insert("exports", {"id": export_id, "state": "building", "created_at": now(), "path": None, "detail": {"done": 0, "total": 1}})
    assert client.post(f"/api/v1/exports/{export_id}/cancel").json()["cancelling"] is True
    exports._build(client.cfg, db, export_id, [run_id], ["tiff"])  # the builder stops before writing anything
    st = client.get(f"/api/v1/exports/{export_id}").json()
    assert st["state"] == "cancelled" and st["download_url"] is None
    assert not list(client.cfg.exports_dir.glob(f"{export_id}*"))
    assert client.post(f"/api/v1/exports/{export_id}/cancel").json()["cancelling"] is False  # nothing left to cancel


@pytest.mark.realfiles
def test_real_jpeg_vertical_slice(client):
    p = real_file("*M 31*.JPG")
    if p is None:
        pytest.skip("real JPEG not present in samplepics/")
    a = ready(client, upload(client, p)["id"])
    assert a["status"] == "ready" and (a["width"], a["height"]) == (1080, 1080)
    job = run_job(client, [a["id"]], default_recipe(client, "vivid"))
    item = job["items"][0]
    assert item["state"] in ("succeeded", "succeeded_with_notes"), item.get("error")
    png = client.get(f"/api/v1/runs/{item['run_id']}/exports/png").content
    assert np.asarray(Image.open(io.BytesIO(png))).shape == (1080, 1080, 3)

