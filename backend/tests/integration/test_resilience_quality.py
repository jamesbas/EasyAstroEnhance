"""Milestones 4-5 integration: durable jobs, cancel, restart recovery, limits, presets, supervised background,
protected regions, history. Synthetic images are test fixtures only."""
from __future__ import annotations

import hashlib
import io
import time

import imagecodecs
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import load_config
from app.main import create_app
from conftest import synthetic_field, wait_for, write_jpeg
from integration.test_jpeg_slice import default_recipe, ready, run_job, upload


def big_jpeg(tmp_path, name, h=1400, w=2000, seed=0):
    arr, _ = synthetic_field(h=h, w=w, seed=seed, n_stars=400)
    return write_jpeg(tmp_path / name, arr)


def heavy_recipe(client, device="cpu"):
    r = default_recipe(client, "brighter-detail")
    r["local_contrast"] = {"enabled": True, "strength": "balanced"}
    return r


def job_state(client, jid):
    return client.get(f"/api/v1/jobs/{jid}").json()


def test_cancel_stops_running_and_queued_items_preserving_originals_and_completed_outputs(client, tmp_path):
    ids, hashes = [], {}
    for i in range(3):
        p = big_jpeg(tmp_path, f"b{i}.jpg", seed=i)
        a = ready(client, upload(client, p)["id"])
        ids.append(a["id"])
        hashes[a["id"]] = hashlib.sha256(p.read_bytes()).hexdigest()
    client.patch("/api/v1/settings/compute", json={"device": "cpu"})
    jid = client.post("/api/v1/jobs", json={"request_key": "cancel-test-1", "asset_ids": ids, "recipe": heavy_recipe(client)}).json()["id"]
    wait_for(lambda: any(i["state"] == "running" for i in job_state(client, jid)["items"]), timeout=60)
    assert client.post(f"/api/v1/jobs/{jid}/cancel").status_code == 200
    final = wait_for(lambda: (lambda j: j if j["state"] not in ("queued", "running") else None)(job_state(client, jid)), timeout=120)
    states = [i["state"] for i in final["items"]]
    assert final["state"] in ("cancelled", "succeeded_with_notes") and "cancelled" in states
    assert not any(client.cfg.runs_dir.glob("*.partial"))  # never expose partial files
    for aid, h in hashes.items():
        assert hashlib.sha256((client.cfg.assets_dir / aid / "original.jpg").read_bytes()).hexdigest() == h
    done = [i for i in final["items"] if i["state"].startswith("succeeded")]
    for i in done:
        assert client.get(f"/api/v1/runs/{i['run_id']}/exports/png").status_code == 200  # completed outputs preserved


def test_restart_marks_interrupted_preserves_everything_and_retry_completes(data_dir, tmp_path):
    cfg = load_config(data_dir=data_dir, port=8765)
    ids = []
    with TestClient(create_app(cfg), base_url="http://127.0.0.1:8765") as c:
        c.headers.update({"X-EAE-Token": c.get("/api/v1/session").json()["token"]})
        c.patch("/api/v1/settings/compute", json={"device": "cpu"})
        for i in range(3):
            p = big_jpeg(tmp_path, f"r{i}.jpg", seed=10 + i)
            ids.append(ready(c, upload(c, p)["id"])["id"])
        small = ready(c, upload(c, write_jpeg(tmp_path / "s.jpg", synthetic_field()[0]))["id"])
        first = run_job(c, [small["id"]], default_recipe(c), key="restart-done-1")
        done_run = first["items"][0]["run_id"]
        c.post("/api/v1/presets", json={"name": "Mine", "recipe": default_recipe(c)})
        jid = c.post("/api/v1/jobs", json={"request_key": "restart-test-1", "asset_ids": ids, "recipe": heavy_recipe(c)}).json()["id"]
        wait_for(lambda: any(i["state"] == "running" for i in job_state(c, jid)["items"]), timeout=60)
    # --- server restarted on the same data dir
    with TestClient(create_app(cfg), base_url="http://127.0.0.1:8765") as c2:
        c2.headers.update({"X-EAE-Token": c2.get("/api/v1/session").json()["token"]})
        j = job_state(c2, jid)
        assert j["state"] == "interrupted" and all(i["state"] in ("interrupted", "succeeded", "succeeded_with_notes") for i in j["items"])
        assert not any(cfg.runs_dir.glob("*.partial"))
        assert c2.get(f"/api/v1/runs/{done_run}/exports/png").status_code == 200  # completed outputs survive
        assert any(p["name"] == "Mine" for p in c2.get("/api/v1/presets").json()["presets"])  # presets survive restart
        assert all(a["status"] == "ready" for a in c2.get("/api/v1/assets").json()["assets"])
        c2.patch("/api/v1/settings/compute", json={"device": "cpu"})
        assert c2.post(f"/api/v1/jobs/{jid}/retry").status_code == 200  # manual retry only
        fin = wait_for(lambda: (lambda x: x if x["state"] not in ("queued", "running") else None)(job_state(c2, jid)), timeout=300)
        assert fin["state"] in ("succeeded", "succeeded_with_notes") and all(i["run_id"] for i in fin["items"])


def test_duplicate_clicks_do_not_duplicate_jobs_and_rerun_creates_new_immutable_run(client, tmp_path):
    a = ready(client, upload(client, write_jpeg(tmp_path / "d.jpg", synthetic_field()[0]))["id"])
    body = {"request_key": "dup-click-0001", "asset_ids": [a["id"]], "recipe": default_recipe(client)}
    r1 = client.post("/api/v1/jobs", json=body)
    r2 = client.post("/api/v1/jobs", json=body)
    assert r1.json()["id"] == r2.json()["id"] and r2.json()["idempotent_replay"] is True
    assert len(client.get("/api/v1/jobs").json()["jobs"]) == 1
    fin = wait_for(lambda: (lambda j: j if j["state"] not in ("queued", "running") else None)(job_state(client, r1.json()["id"])))
    run1 = fin["items"][0]["run_id"]
    h1 = hashlib.sha256((client.cfg.runs_dir / run1 / "enhanced.png").read_bytes()).hexdigest()
    same = run_job(client, [a["id"]], default_recipe(client), key="identical-0001")  # identical settings reuse the cached run
    assert same["items"][0]["run_id"] == run1 and same["items"][0]["notes"][0]["kind"] == "cache"
    changed = default_recipe(client)
    changed["tone"]["brightness_ev"] = 0.5
    new = run_job(client, [a["id"]], changed, key="changed-0001")
    assert new["items"][0]["run_id"] != run1
    forced = run_job(client, [a["id"]], default_recipe(client), key="forced-0001", force=True)
    assert forced["items"][0]["run_id"] not in (run1, new["items"][0]["run_id"])  # explicit Reprocess = a new run
    assert hashlib.sha256((client.cfg.runs_dir / run1 / "enhanced.png").read_bytes()).hexdigest() == h1  # earlier run untouched
    runs = client.get("/api/v1/runs", params={"asset_id": a["id"]}).json()["runs"]
    assert len(runs) == 3 and len({r["run_name"] for r in runs}) == 3


def test_presets_validate_exclude_per_image_data_and_snapshots_are_immutable(client, tmp_path):
    base = default_recipe(client)
    bad = {**base, "regions": [{"x": 0, "y": 0, "w": 5, "h": 5}]}
    r = client.post("/api/v1/presets", json={"name": "bad", "recipe": bad})
    assert r.status_code == 422 and r.json()["error"]["code"] == "PRESET_INVALID"  # no per-image regions/masks/models
    assert client.post("/api/v1/presets", json={"name": "bad2", "recipe": {**base, "schema_version": 1}}).status_code == 422
    assert client.post("/api/v1/presets", json={"name": "bad3", "recipe": {**base, "tone": {**base["tone"], "brightness_ev": 5}}}).status_code == 422
    p = client.post("/api/v1/presets", json={"name": "Warm", "recipe": base}).json()
    assert client.post("/api/v1/presets", json={"name": "warm", "recipe": base}).status_code == 409
    dup = client.post(f"/api/v1/presets/{p['id']}/duplicate").json()
    assert dup["name"] == "Warm copy"
    assert client.patch(f"/api/v1/presets/{dup['id']}", json={"name": "Cool"}).json()["name"] == "Cool"
    assert client.patch("/api/v1/presets/natural", json={"name": "x"}).status_code == 400  # built-ins are protected
    a = ready(client, upload(client, write_jpeg(tmp_path / "p.jpg", synthetic_field()[0]))["id"])
    job = client.post("/api/v1/jobs", json={"request_key": "preset-snap-1", "asset_ids": [a["id"]], "recipe": p["recipe"], "preset_id": p["id"]}).json()
    fin = wait_for(lambda: (lambda j: j if j["state"] not in ("queued", "running") else None)(job_state(client, job["id"])))
    run_id = fin["items"][0]["run_id"]
    before = client.get(f"/api/v1/runs/{run_id}/exports/report").json()
    edited = {**base, "tone": {**base["tone"], "brightness_ev": -0.5}}
    client.patch(f"/api/v1/presets/{p['id']}", json={"recipe": edited})
    after = client.get(f"/api/v1/runs/{run_id}/exports/report").json()
    assert before["preset_snapshot"] == after["preset_snapshot"] and after["preset_snapshot"]["recipe"]["tone"]["brightness_ev"] == 0.0
    assert client.delete(f"/api/v1/presets/{p['id']}").status_code == 200


def test_limits_oversized_too_many_disk_full_and_readable_errors(data_dir, tmp_path):
    cfg = load_config(data_dir=data_dir, port=8765, max_file_bytes=2000, max_files=2)
    with TestClient(create_app(cfg), base_url="http://127.0.0.1:8765") as c:
        c.headers.update({"X-EAE-Token": c.get("/api/v1/session").json()["token"]})
        p = write_jpeg(tmp_path / "big.jpg", synthetic_field()[0])
        a = c.post("/api/v1/assets", files=[("files", ("big.jpg", p.read_bytes(), "image/jpeg"))]).json()["assets"][0]
        assert a["status"] == "failed" and a["error"]["code"] == "FILE_TOO_LARGE" and "limit" in a["error"]["message"]
        assert not list(cfg.assets_dir.glob(f"{a['id']}/upload.part"))
        r = c.post("/api/v1/assets", files=[("files", (f"{i}.jpg", b"x", "image/jpeg")) for i in range(3)])
        assert r.status_code == 413 and r.json()["error"]["code"] == "TOO_MANY_FILES"
    cfg2 = load_config(data_dir=data_dir / "two", port=8765, min_free_bytes=10**15)
    with TestClient(create_app(cfg2), base_url="http://127.0.0.1:8765") as c:
        c.headers.update({"X-EAE-Token": c.get("/api/v1/session").json()["token"]})
        a = c.post("/api/v1/assets", files=[("files", ("x.jpg", p.read_bytes(), "image/jpeg"))]).json()["assets"][0]
        assert a["status"] == "failed" and a["error"]["code"] == "DISK_FULL"


def test_disk_space_is_checked_before_processing(data_dir, tmp_path):
    cfg = load_config(data_dir=data_dir, port=8765)
    with TestClient(create_app(cfg), base_url="http://127.0.0.1:8765") as c:
        c.headers.update({"X-EAE-Token": c.get("/api/v1/session").json()["token"]})
        a = ready(c, upload(c, write_jpeg(tmp_path / "x.jpg", synthetic_field()[0]))["id"])
    from dataclasses import replace

    cfg2 = replace(cfg, min_free_bytes=10**15)
    with TestClient(create_app(cfg2), base_url="http://127.0.0.1:8765") as c:
        c.headers.update({"X-EAE-Token": c.get("/api/v1/session").json()["token"]})
        job = run_job(c, [a["id"]], default_recipe(c), key="disk-full-0001")
        err = job["items"][0]["error"]
        assert job["items"][0]["state"] == "failed" and err["code"] == "DISK_FULL" and "disk space" in err["message"]
        assert not list(cfg.runs_dir.iterdir())


def test_protected_regions_end_to_end_and_invalid_region_errors(client, tmp_path):
    arr, _ = synthetic_field(h=240, w=300)
    arr[200:, :] = 0.9  # a caption band
    p = write_jpeg(tmp_path / "cap.jpg", arr)
    a = ready(client, upload(client, p)["id"])
    for bad in ([{"x": 0, "y": 230, "w": 300, "h": 30}], [{"x": 5, "y": 5, "w": 0, "h": 5}]):
        r = client.put(f"/api/v1/assets/{a['id']}/regions", json={"regions": bad})
        assert r.status_code == 422 and r.json()["error"]["message"]
    ok = client.put(f"/api/v1/assets/{a['id']}/regions", json={"regions": [{"x": 0, "y": 200, "w": 300, "h": 40}]})
    assert ok.status_code == 200 and ok.json()["regions"]
    job = run_job(client, [a["id"]], default_recipe(client), key="regions-0001")
    run = job["items"][0]["run_id"]
    out = imagecodecs.png_decode(client.get(f"/api/v1/runs/{run}/exports/png").content)
    src = np.asarray(__import__("PIL.Image", fromlist=["Image"]).open(p))
    assert np.array_equal(out[200:], src[200:])  # lettering restored exactly (lossless export)
    rep = client.get(f"/api/v1/runs/{run}/exports/report").json()
    assert rep["applied"]["protected_regions"]["count"] == 1


def test_supervised_background_flow_and_never_copied_between_images(client, tmp_path):
    rng = np.random.default_rng(1)
    h, w = 360, 480
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    sky = 0.15 + 0.06 * (xx / w - 0.5) - 0.04 * (yy / h - 0.5)
    img = np.stack([sky + 0.01, sky, sky - 0.01], -1) + rng.normal(0, 0.003, (h, w, 3)).astype(np.float32)
    img[150:210, 200:280] += 0.2  # frame has an extended object away from the patches
    a1 = ready(client, upload(client, write_jpeg(tmp_path / "g1.jpg", np.clip(img, 0, 1)))["id"])
    a2 = ready(client, upload(client, write_jpeg(tmp_path / "g2.jpg", np.clip(img, 0, 1)))["id"])
    sug = client.get(f"/api/v1/assets/{a1['id']}/background/suggest").json()
    assert "note" in sug, sug
    assert "heuristic" in sug["note"].lower() and isinstance(sug["patches"], list)
    patches = [{"x": x, "y": y, "w": 30, "h": 30} for x, y in [(10, 10), (230, 10), (440, 10), (10, 170), (440, 170), (20, 320), (230, 320), (440, 320)]]
    few = client.post(f"/api/v1/assets/{a1['id']}/background/preview", json={"method": "planar", "samples": patches[:4]}).json()
    assert not few["model"]["ok"] and few["model"]["issues"][0]["code"] == "TOO_FEW_PATCHES"
    rej = client.put(f"/api/v1/assets/{a1['id']}/background", json={"method": "planar", "samples": patches[:4], "confirmed": True})
    assert rej.status_code == 422 and rej.json()["error"]["code"] == "BACKGROUND_INVALID"  # server-side validation
    pv = client.post(f"/api/v1/assets/{a1['id']}/background/preview", json={"method": "planar", "samples": patches, "strength": 0.5}).json()
    assert pv["model"]["ok"] and pv["preview_url"] and len(pv["plane_grid"]) == 24 and pv["model"]["residuals"]["rms"] < 0.01
    assert client.get(pv["preview_url"]).status_code == 200
    conf = client.put(f"/api/v1/assets/{a1['id']}/background", json={"method": "planar", "samples": patches, "strength": 0.5, "confirmed": True})
    assert conf.status_code == 200 and conf.json()["background"]["confirmed"]
    recipe = default_recipe(client)
    recipe["background"] = {"enabled": True, "method": "planar", "strength": "gentle"}
    job = run_job(client, [a1["id"], a2["id"]], recipe, key="bg-flow-0001")
    ops = {}
    for it in job["items"]:
        rep = client.get(f"/api/v1/runs/{it['run_id']}/exports/report").json()
        ops[it["asset_id"]] = [o for o in rep["applied"]["operations"] if o["name"] == "background"][0]
    assert ops[a1["id"]]["status"] == "applied" and ops[a1["id"]]["parameters"]["plane"]
    assert ops[a2["id"]]["status"] == "skipped" and "pending" in ops[a2["id"]]["reason"]  # nothing copied to the other image
    assert client.put(f"/api/v1/assets/{a1['id']}/background", json={"method": "planar", "samples": [], "confirmed": False}).json()["background"] is None


def test_star_mask_overlay_and_history_clear(client, tmp_path):
    a = ready(client, upload(client, write_jpeg(tmp_path / "s.jpg", synthetic_field(h=200, w=260, n_stars=60, galaxy=False, noise=0.004)[0]))["id"])
    sm = client.get(f"/api/v1/assets/{a['id']}/star-mask").json()
    assert sm["reliable"] and sm["overlay_url"] and client.get(sm["overlay_url"]).status_code == 200
    run_job(client, [a["id"]], default_recipe(client), key="hist-0001")
    summ = client.get("/api/v1/history/summary").json()
    assert summ["assets"] == 1 and summ["runs"] == 1 and "never touched" in summ["will_remove"]
    assert client.request("DELETE", "/api/v1/history", json={"confirm": False}).status_code == 400
    assert client.request("DELETE", "/api/v1/history", json={"confirm": True}).json()["cleared"]
    assert client.get("/api/v1/assets").json()["assets"] == [] and any(p["id"] == "natural" for p in client.get("/api/v1/presets").json()["presets"])


def test_compute_endpoints_report_truthful_status(client):
    c0 = client.get("/api/v1/compute").json()
    assert c0["preference"] == "auto" and c0["probe"] is None and "not checked" in c0["note"]
    probed = client.post("/api/v1/compute/probe").json()
    assert probed["probe"]["status"] in ("ready", "unavailable", "failed")
    if not probed["gpu_usable"]:
        assert probed["resolved_label"] == "Processing: CPU" and probed["note"]
    assert client.patch("/api/v1/settings/compute", json={"device": "gpu"}).json()["preference"] == "gpu"
    assert client.patch("/api/v1/settings/compute", json={"device": "bogus"}).status_code == 422
    assert client.patch("/api/v1/settings/compute", json={"gpu_memory_fraction": 0.95}).status_code == 422  # bounded VRAM budget
    assert client.patch("/api/v1/settings", json={"strip_location": False}).json()["strip_location"] is False

