"""AI models API: status, verified download (file:// stand-in), rejection of a corrupted file, removal, preset migration."""
from __future__ import annotations

import dataclasses
import hashlib

import pytest

from app.processing.ai import registry
from conftest import wait_for


@pytest.fixture()
def fake_models(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    patched = {}
    for mid, spec in registry.MODELS.items():
        data = f"stand-in model {mid}".encode() * 50
        p = src / spec.file
        p.write_bytes(data)
        patched[mid] = dataclasses.replace(spec, url=p.as_uri(), size=len(data), sha256=hashlib.sha256(data).hexdigest(), graxpert_dir=None)
    monkeypatch.setattr(registry, "MODELS", patched)
    return src


def _tool(client, tool):
    return client.get("/api/v1/ai/models").json()["tools"][tool]


def test_models_download_verify_and_delete(client, fake_models):
    o = client.get("/api/v1/ai/models").json()
    assert o["runtime_available"] and {m["id"] for m in o["models"]} == set(registry.MODELS)
    assert all(m["state"] == "missing" and m["license"] and m["sha256"] for m in o["models"])
    assert o["tools"]["denoise"]["download_bytes"] == registry.MODELS["graxpert-denoise"].size
    r = client.post("/api/v1/ai/models/stars/download")
    assert r.status_code == 202
    wait_for(lambda: _tool(client, "stars")["state"] == "installed", timeout=30)
    d = client.cfg.ai_models_dir
    assert (d / "darkstar_v2.1c.onnx").exists() and (d / "darkstar_v2.1c.onnx.sha256").read_text() == registry.MODELS["darkstar-color"].sha256
    assert not list(d.glob("*.part"))
    assert client.request("DELETE", "/api/v1/ai/models/stars").status_code == 200
    assert _tool(client, "stars")["state"] == "missing" and not (d / "darkstar_v2.1c.onnx").exists()
    assert client.post("/api/v1/ai/models/unknown/download").status_code == 404


def test_corrupted_download_is_discarded(client, fake_models, monkeypatch):
    bad = dataclasses.replace(registry.MODELS["graxpert-background"], sha256="0" * 64)
    monkeypatch.setitem(registry.MODELS, "graxpert-background", bad)
    client.post("/api/v1/ai/models/background/download")
    m = wait_for(lambda: next(x for x in client.get("/api/v1/ai/models").json()["models"] if x["id"] == "graxpert-background")["state"] == "error"
                 and next(x for x in client.get("/api/v1/ai/models").json()["models"] if x["id"] == "graxpert-background"), timeout=30)
    assert "SHA-256" in m["error"]
    assert not any(client.cfg.ai_models_dir.glob("graxpert-background*"))


def test_recipe_with_ai_flags_is_accepted_and_old_presets_migrate(client):
    from app.processing.recipe import RECIPE_SCHEMA_VERSION

    presets = client.get("/api/v1/presets").json()["presets"]
    recipe = next(p for p in presets if p["id"] == "natural")["recipe"]
    assert recipe["ai"] == {"background": False, "denoise": False, "stars": False}
    r = client.post("/api/v1/presets", json={"name": "Mine with AI", "recipe": {**recipe, "preset": "custom", "ai": {"background": True, "denoise": True, "stars": False}}})
    assert r.status_code == 201, r.text
    # a schema-3 preset saved by engine 1.1 is migrated at start-up (AI off, every other setting kept)
    db = client.app.state.db
    old = {k: v for k, v in recipe.items() if k != "ai"} | {"schema_version": 3, "preset": "custom"}
    db.execute("UPDATE presets SET recipe=?, schema_version=3 WHERE id=?", (old, r.json()["id"]))
    from app.api.presets import seed_builtin_presets

    seed_builtin_presets(db)
    p = next(x for x in client.get("/api/v1/presets").json()["presets"] if x["name"] == "Mine with AI")
    assert p["compatible"] and p["schema_version"] == RECIPE_SCHEMA_VERSION and p["recipe"]["ai"]["denoise"] is False
