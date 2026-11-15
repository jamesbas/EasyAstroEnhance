from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..db import new_id, now
from ..models.api import PresetIn, PresetPatch
from ..processing.recipe import (
    BUILTIN_PRESET_NAMES, MIGRATABLE_SCHEMAS, PIPELINE_VERSION, RECIPE_SCHEMA_VERSION, RecipeCompatibilityError, builtin_presets, parse_recipe,
)
from .common import ApiError, cfg_of, coord_of, db_of, serialize_asset

router = APIRouter(prefix="/presets", tags=["presets"])


def seed_builtin_presets(db) -> None:
    t = now()
    current = builtin_presets()
    for old in db.all("SELECT id FROM presets WHERE builtin=1"):
        if old["id"] not in current:  # built-ins retired by an engine update
            db.execute("DELETE FROM presets WHERE id=?", (old["id"],))
    for p in db.all("SELECT * FROM presets WHERE builtin=0 AND schema_version IN (%s)" % ",".join("?" * len(MIGRATABLE_SCHEMAS)), tuple(MIGRATABLE_SCHEMAS)):
        try:  # additive schema change: the saved settings keep their meaning
            recipe = parse_recipe(p["recipe"]).model_dump()
        except RecipeCompatibilityError:
            continue
        db.update("presets", p["id"], {"recipe": recipe, "schema_version": RECIPE_SCHEMA_VERSION, "updated_at": t})
    for pid, recipe in current.items():
        row = {"id": pid, "name": BUILTIN_PRESET_NAMES[pid], "recipe": recipe.model_dump(), "schema_version": RECIPE_SCHEMA_VERSION, "engine_version": PIPELINE_VERSION, "builtin": 1, "updated_at": t}
        if db.one("SELECT id FROM presets WHERE id=?", (pid,)):
            db.update("presets", pid, row)
        else:
            db.insert("presets", {**row, "created_at": t})


def _out(p: dict[str, Any]) -> dict[str, Any]:
    compatible = p["schema_version"] == RECIPE_SCHEMA_VERSION
    return {
        "id": p["id"], "name": p["name"], "builtin": bool(p["builtin"]), "recipe": p["recipe"] if compatible else None, "compatible": compatible,
        "schema_version": p["schema_version"], "engine_version": p["engine_version"], "updated_at": p["updated_at"],
        "migration_note": None if compatible else (
            f"This preset was saved with recipe schema {p['schema_version']} (engine {p['engine_version']}); "
            f"this version needs schema {RECIPE_SCHEMA_VERSION}. Recreate it from the Enhancement panel and save it again."),
    }


def _validate(recipe: dict[str, Any]) -> dict[str, Any]:
    try:
        return parse_recipe(recipe).model_dump()  # extra fields (regions, masks, models, HDUs) are rejected
    except RecipeCompatibilityError as exc:
        raise ApiError(422, "PRESET_INVALID", "This preset is not valid or is incompatible with this version.", str(exc)) from exc


@router.get("")
async def list_presets(request: Request) -> dict[str, Any]:
    rows = db_of(request).all("SELECT * FROM presets ORDER BY builtin DESC, name COLLATE NOCASE")
    return {"presets": [_out(p) for p in rows]}


@router.post("", status_code=201)
async def create_preset(request: Request, body: PresetIn) -> dict[str, Any]:
    db = db_of(request)
    if db.one("SELECT 1 AS x FROM presets WHERE lower(name)=lower(?)", (body.name.strip(),)):
        raise ApiError(409, "PRESET_NAME_TAKEN", "A preset with that name already exists.")
    recipe = _validate(body.recipe)
    pid, t = new_id("pre_"), now()
    db.insert("presets", {"id": pid, "name": body.name.strip(), "recipe": recipe, "schema_version": RECIPE_SCHEMA_VERSION, "engine_version": PIPELINE_VERSION, "builtin": 0, "created_at": t, "updated_at": t})
    return _out(db.one("SELECT * FROM presets WHERE id=?", (pid,)))  # type: ignore[arg-type]


@router.patch("/{preset_id}")
async def patch_preset(request: Request, preset_id: str, body: PresetPatch) -> dict[str, Any]:
    db = db_of(request)
    p = db.one("SELECT * FROM presets WHERE id=?", (preset_id,))
    if not p:
        raise ApiError(404, "PRESET_NOT_FOUND", "That preset no longer exists.")
    if p["builtin"]:
        raise ApiError(400, "PRESET_BUILTIN", "Built-in presets cannot be changed. Duplicate it to make your own.")
    values: dict[str, Any] = {"updated_at": now()}
    if body.name is not None:
        if db.one("SELECT 1 AS x FROM presets WHERE lower(name)=lower(?) AND id<>?", (body.name.strip(), preset_id)):
            raise ApiError(409, "PRESET_NAME_TAKEN", "A preset with that name already exists.")
        values["name"] = body.name.strip()
    if body.recipe is not None:
        values.update(recipe=_validate(body.recipe), schema_version=RECIPE_SCHEMA_VERSION, engine_version=PIPELINE_VERSION)
    db.update("presets", preset_id, values)
    return _out(db.one("SELECT * FROM presets WHERE id=?", (preset_id,)))  # type: ignore[arg-type]


@router.post("/{preset_id}/duplicate", status_code=201)
async def duplicate_preset(request: Request, preset_id: str) -> dict[str, Any]:
    db = db_of(request)
    p = db.one("SELECT * FROM presets WHERE id=?", (preset_id,))
    if not p:
        raise ApiError(404, "PRESET_NOT_FOUND", "That preset no longer exists.")
    base = f"{p['name']} copy"
    name, n = base, 2
    while db.one("SELECT 1 AS x FROM presets WHERE lower(name)=lower(?)", (name,)):
        name, n = f"{base} {n}", n + 1
    new, t = new_id("pre_"), now()
    db.insert("presets", {"id": new, "name": name, "recipe": p["recipe"], "schema_version": p["schema_version"], "engine_version": p["engine_version"], "builtin": 0, "created_at": t, "updated_at": t})
    return _out(db.one("SELECT * FROM presets WHERE id=?", (new,)))  # type: ignore[arg-type]


@router.delete("/{preset_id}")
async def delete_preset(request: Request, preset_id: str) -> dict[str, Any]:
    db = db_of(request)
    p = db.one("SELECT * FROM presets WHERE id=?", (preset_id,))
    if not p:
        raise ApiError(404, "PRESET_NOT_FOUND", "That preset no longer exists.")
    if p["builtin"]:
        raise ApiError(400, "PRESET_BUILTIN", "Built-in presets cannot be deleted.")
    db.execute("DELETE FROM presets WHERE id=?", (preset_id,))
    return {"deleted": preset_id}
