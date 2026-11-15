"""Stacking through the API: scan, queue, progress, new linear image, optional automatic enhancement, cancel."""
from __future__ import annotations

import numpy as np
from astropy.io import fits

from conftest import wait_for
from stack_fixtures import _make_subs


def _recipe(client, preset="natural"):
    return next(p["recipe"] for p in client.get("/api/v1/presets").json()["presets"] if p["id"] == preset)


def _finished(client, sid):
    def done():
        s = client.get(f"/api/v1/stacks/{sid}").json()
        return s if s["state"] not in ("queued", "running") else None

    return wait_for(done, timeout=240)


def test_scan_validates_and_summarizes(client, tmp_path):
    r = client.post("/api/v1/stacks/scan", json={"folder": "relative\\folder"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "FOLDER_NOT_ABSOLUTE"
    r = client.post("/api/v1/stacks/scan", json={"folder": str(tmp_path / "missing")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "FOLDER_NOT_FOUND"
    _make_subs(tmp_path / "M 99_sub", n=4, trail_frame=None)
    r = client.post("/api/v1/stacks/scan", json={"folder": f'"{tmp_path / "M 99_sub"}"'})  # pasted with quotes
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["mode"] == "subs" and p["lights"]["count"] == 4 and p["name"] == "M 99" and p["drizzle_available"]
    r = client.post("/api/v1/stacks", json={"request_key": "stack-key-empty", "folder": str(tmp_path)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOTHING_TO_STACK"


def test_stack_creates_linear_image_without_enhancing(client, tmp_path):
    folder = tmp_path / "M 99_sub"
    _make_subs(folder, n=6)
    before = sorted(f.name for f in folder.iterdir())
    r = client.post("/api/v1/stacks", json={"request_key": "stack-key-0001", "folder": str(folder)})
    assert r.status_code == 202, r.text
    s = r.json()
    assert s["state"] in ("queued", "running") and s["auto_enhance"] is False
    again = client.post("/api/v1/stacks", json={"request_key": "stack-key-0001", "folder": str(folder)}).json()
    assert again["idempotent_replay"] and again["id"] == s["id"]
    s = _finished(client, s["id"])
    assert s["state"] == "succeeded", s
    assert s["report"]["frames_used"] == 6 and s["report"]["rejected_frames"] == [] and s["job_id"] is None
    a = wait_for(lambda: (x := client.get(f"/api/v1/assets/{s['asset_id']}").json())["status"] in ("ready", "failed") and x)
    assert a["status"] == "ready" and a["can_process"] and a["interpretation"] == {"state": "linear"}
    assert a["filename"] == "M 99 - stacked 6 frames.fits" and a["width"] == 320 and a["height"] == 240
    assert a["latest_item"] is None  # nothing was enhanced: the user adjusts first
    assert a["stack"]["frames_used"] == 6 and a["stack"]["frames_total"] == 6 and a["stack"]["defective_pixels"] >= 4
    assert client.get("/api/v1/jobs").json()["jobs"] == []
    assert sorted(f.name for f in folder.iterdir()) == before  # source folder untouched
    path = client.cfg.assets_dir / a["id"] / "original.fits"
    with fits.open(path) as hdul:
        assert hdul[0].data.shape == (3, 240, 320) and hdul[0].header["STACKCNT"] == 6
        assert np.isfinite(hdul[0].data).mean() > 0.9
    assert list(client.cfg.tmp_dir.glob("stack_*")) == []
    full = client.get(f"/api/v1/stacks/{s['id']}").json()["full_report"]
    assert full["calibration"]["defective_pixels"]["count"] >= 4


def test_stack_with_automatic_enhancement(client, tmp_path):
    _make_subs(tmp_path / "subs", n=5, trail_frame=None)
    r = client.post("/api/v1/stacks", json={"request_key": "stack-key-auto", "folder": str(tmp_path / "subs"), "auto_enhance": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "RECIPE_REQUIRED"
    r = client.post("/api/v1/stacks", json={"request_key": "stack-key-auto", "folder": str(tmp_path / "subs"), "auto_enhance": True,
                                            "recipe": _recipe(client), "preset_id": "natural"})
    assert r.status_code == 202, r.text
    s = _finished(client, r.json()["id"])
    assert s["state"] == "succeeded"
    job_id = wait_for(lambda: client.get(f"/api/v1/stacks/{s['id']}").json()["job_id"])
    job = wait_for(lambda: (j := client.get(f"/api/v1/jobs/{job_id}").json())["state"] not in ("queued", "running") and j, timeout=240)
    assert job["state"] in ("succeeded", "succeeded_with_notes") and job["items"][0]["asset_id"] == s["asset_id"]


def test_cancel_queued_stack_and_clear_history(client, tmp_path):
    _make_subs(tmp_path / "a", n=6)
    _make_subs(tmp_path / "b", n=4, trail_frame=None)
    first = client.post("/api/v1/stacks", json={"request_key": "stack-key-first", "folder": str(tmp_path / "a")}).json()
    second = client.post("/api/v1/stacks", json={"request_key": "stack-key-second", "folder": str(tmp_path / "b")}).json()
    c = client.post(f"/api/v1/stacks/{second['id']}/cancel").json()
    assert c["state"] == "cancelled" or c["state"] == "running"
    _finished(client, first["id"])
    second = _finished(client, second["id"])
    if second["state"] == "cancelled":
        r = client.post(f"/api/v1/stacks/{second['id']}/retry").json()
        assert r["state"] in ("queued", "running")
        assert _finished(client, second["id"])["state"] == "succeeded"
    wait_for(lambda: all(a["status"] != "inspecting" for a in client.get("/api/v1/assets").json()["assets"]))
    assert client.request("DELETE", "/api/v1/history", json={"confirm": True}).status_code == 200
    assert client.get("/api/v1/stacks").json()["stacks"] == []
