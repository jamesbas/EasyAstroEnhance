"""Versioned recipe schema, strength tables and engine identity.

Recipes describe *intent*. They never contain per-image data (regions, masks, fitted
models, HDU choices); those belong to each asset and are resolved by the pipeline.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PIPELINE_VERSION = "1.0.0"
RECIPE_SCHEMA_VERSION = 2

Strength = Literal["gentle", "balanced", "strong"]

# Proposed tuning values from the specification (not universal truths).
STRENGTH_TABLES: dict[str, dict[str, float]] = {
    "denoise": {"gentle": 0.30, "balanced": 0.40, "strong": 0.55},
    "gain": {"gentle": 1.25, "balanced": 1.45, "strong": 1.75},
    "asinh_k": {"gentle": 20.0, "balanced": 45.0, "strong": 90.0},
    "saturation": {"gentle": 1.08, "balanced": 1.12, "strong": 1.20},
    "star_protection": {"gentle": 0.50, "balanced": 0.75, "strong": 0.90},
    "local_contrast": {"gentle": 0.35, "balanced": 0.60, "strong": 0.90},
    "background": {"gentle": 0.50, "balanced": 0.75, "strong": 1.00},
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Switch(_Strict):
    enabled: bool = True
    strength: Strength = "gentle"


class ToneRecipe(Switch):
    brightness_ev: float = Field(0.0, ge=-1.0, le=1.0)
    shadows: float = Field(0.0, ge=-1.0, le=1.0)
    highlights: float = Field(0.0, ge=-1.0, le=1.0)
    black_point: float = Field(0.0, ge=-0.05, le=0.10)


class BackgroundRecipe(_Strict):
    enabled: bool = False
    method: Literal["constant", "planar"] = "constant"
    strength: Strength = "gentle"


class AdvancedRecipe(_Strict):
    """Exact values that override the strength buttons. All bounded."""

    denoise_amount: float | None = Field(None, ge=0.0, le=0.8)
    tone_gain: float | None = Field(None, ge=1.0, le=2.5)
    asinh_k: float | None = Field(None, ge=2.0, le=200.0)
    saturation: float | None = Field(None, ge=1.0, le=1.4)
    star_protection_amount: float | None = Field(None, ge=0.0, le=1.0)
    local_contrast_amount: float | None = Field(None, ge=0.0, le=1.2)
    local_contrast_scale_px: float | None = Field(None, ge=8.0, le=64.0)
    background_strength: float | None = Field(None, ge=0.0, le=1.0)


class Recipe(_Strict):
    schema_version: int = RECIPE_SCHEMA_VERSION
    preset: str = "natural"
    denoise: Switch = Switch()
    tone: ToneRecipe = ToneRecipe()
    star_protection: Switch = Switch()
    local_contrast: Switch = Switch(enabled=False)
    color: Switch = Switch()
    background: BackgroundRecipe = BackgroundRecipe()
    protect_regions: bool = True
    advanced: AdvancedRecipe = AdvancedRecipe()


class RecipeCompatibilityError(ValueError):
    """Raised for recipes this engine cannot run, with migration guidance."""


def parse_recipe(data: dict) -> Recipe:
    version = data.get("schema_version", RECIPE_SCHEMA_VERSION)
    if version != RECIPE_SCHEMA_VERSION:
        raise RecipeCompatibilityError(
            f"Recipe schema version {version} is not supported by engine {PIPELINE_VERSION} "
            f"(requires {RECIPE_SCHEMA_VERSION}). Recreate the preset from the current Enhancement panel "
            "and save it again; settings from older versions are not migrated automatically because "
            "their meaning may differ."
        )
    try:
        return Recipe.model_validate(data)
    except ValidationError as exc:  # re-raised with a readable message
        raise RecipeCompatibilityError(str(exc)) from exc


def builtin_presets() -> dict[str, Recipe]:
    natural = Recipe(preset="natural")
    brighter = Recipe(
        preset="brighter-detail",
        denoise=Switch(strength="balanced"),
        tone=ToneRecipe(strength="balanced"),
        color=Switch(strength="balanced"),
        star_protection=Switch(strength="balanced"),
    )
    return {"natural": natural, "brighter-detail": brighter}


def no_operations_recipe() -> Recipe:
    """An explicit no-operations recipe (supported; reproduces decoded display pixels)."""
    return Recipe(
        preset="custom",
        denoise=Switch(enabled=False),
        tone=ToneRecipe(enabled=False),
        star_protection=Switch(enabled=False),
        local_contrast=Switch(enabled=False),
        color=Switch(enabled=False),
        background=BackgroundRecipe(enabled=False),
        protect_regions=False,
    )
