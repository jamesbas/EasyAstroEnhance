"""Versioned recipe schema, presets and engine identity.

Recipes describe *intent*. They never contain per-image data (regions, masks, fitted models, white-balance
factors, HDU choices); those belong to each asset or are measured per run by the pipeline and recorded in
the processing report.

Schema 3 (engine 1.1): one-button Enhance. Six "look" sliders plus switches for the automatic stages; every
other parameter is chosen from image statistics unless an exact value is given under ``advanced``.

Schema 4 (engine 1.2): adds the optional AI tools (``ai``), all off by default. Schema 3 recipes are migrated by adding
``ai`` switched off; every schema 3 field keeps its meaning.

Schema 7 (engine 1.4): adds opt-in AI star dimming. Older recipes retain the full star blend.
Schema 8 (engine 1.5): allows an explicit zero star blend for display output.
Schema 9 (engine 1.6): Auto preset (``auto_preset``), automatic cosmetic correction and star-fringe reduction
(``auto.cosmetic``, ``auto.halo_reduction``) and a star color slider (``look.star_color``). Older recipes migrate with the
two automatic stages on (like the other automatic stages, each measures the image and is skipped with a reason) and star
color 0, so their look is unchanged except where those stages find defects or fringes.
Schema 10 (engine 1.7): Accurate star colours from the built-in catalog (``catalog_builtin``), AI sharpening
(``ai.sharpen``, ``ai.sharpen_amount``, ``ai.sharpen_stars``), Star size (``ai.star_size``), automatic banding reduction
(``auto.banding``) and the gradient model choice (``advanced.gradient_model``). Older recipes migrate with the opt-in
tools off and banding reduction on (measured; skipped when no banding is found).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PIPELINE_VERSION = "1.7.0"
RECIPE_SCHEMA_VERSION = 10
MIGRATABLE_SCHEMAS = {3, 4, 5, 6, 7, 8, 9}

Strength = Literal["gentle", "balanced", "strong"]

# Supervised background correction strength behind the Gentle/Balanced/Strong buttons.
BACKGROUND_STRENGTH = {"gentle": 0.50, "balanced": 0.75, "strong": 1.00}

# Mapping of the 0..1 look sliders to algorithm parameters (documented in the processing report).
SATURATION_PER_COLOR = 0.6  # saturation = 1 + 0.6 * color  (1.0 .. 1.6)
POP_PER_CONTRAST = 0.8  # S-curve amplitude a = 0.8 * contrast (monotonic for a <= 1)
STRETCH_DECADES_PER_UNIT = 0.75  # stretch slider shifts the auto-solved D by 10**(0.75 * stretch)
RENDERED_BASE_GAIN = 1.25  # rendered images: rational midtone gain at stretch 0


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LookRecipe(_Strict):
    """The main sliders. 0 switches a finishing stage off."""

    background: float = Field(0.12, ge=0.04, le=0.25, description="Target sky brightness on display")
    stretch: float = Field(0.0, ge=-1.0, le=1.0, description="Gentle (-) to deep (+), relative to the auto-solved stretch")
    contrast: float = Field(0.2, ge=0.0, le=1.0, description="Finishing S-curve ('pop')")
    color: float = Field(0.25, ge=0.0, le=1.0, description="Saturation of existing color")
    detail: float = Field(0.1, ge=0.0, le=1.0, description="Multiscale local contrast")
    noise: float = Field(0.5, ge=0.0, le=1.0, description="Noise reduction relative to the measured noise")
    protect_cores: bool = True
    star_color: float = Field(0.0, ge=0.0, le=1.0, description="Saturation of existing star color inside the star mask")


class AutoRecipe(_Strict):
    """Automatic stages; each measures the image and either runs or is skipped with a recorded reason."""

    neutralize: bool = True
    gradient: bool = True
    white_balance: bool = True
    green_removal: bool = True
    star_stretch: bool = True
    cosmetic: bool = True  # isolated colored hot pixels and cold pixels on faint background (linear stacks)
    halo_reduction: bool = True  # measured blue/violet/magenta fringe in a narrow ring around bright stars
    banding: bool = True  # measured row/column banding (walking noise) on linear stacks


class ToneRecipe(_Strict):
    enabled: bool = True  # the stretch (linear) / midtone curve (rendered)
    brightness_ev: float = Field(0.0, ge=-1.0, le=1.0)
    shadows: float = Field(0.0, ge=-1.0, le=1.0)
    highlights: float = Field(0.0, ge=-1.0, le=1.0)
    black_point: float = Field(0.0, ge=-0.05, le=0.10)


class BackgroundRecipe(_Strict):
    """Supervised (user-confirmed sky regions) constant/planar correction; independent of the automatic stages."""

    enabled: bool = False
    method: Literal["constant", "planar"] = "constant"
    strength: Strength = "gentle"


class AdvancedRecipe(_Strict):
    """Exact values for experts. ``None`` means "chosen automatically". All bounded."""

    stretch_log_d: float | None = Field(None, ge=0.0, le=5.0)
    stretch_b: float | None = Field(None, ge=0.0, le=15.0)
    highlight_convergence: float | None = Field(None, ge=1.0, le=8.0)
    star_stretch_amount: float | None = Field(None, ge=0.0, le=1.0)
    hdr_amount: float | None = Field(None, ge=0.0, le=1.0)
    white_balance_limit: float | None = Field(None, ge=1.0, le=1.5)
    gradient_degree: int | None = Field(None, ge=1, le=3)
    scnr_amount: float | None = Field(None, ge=0.0, le=1.0)
    denoise_scales: int | None = Field(None, ge=2, le=6)
    detail_scale_px: float | None = Field(None, ge=4.0, le=64.0)
    tone_gain: float | None = Field(None, ge=1.0, le=2.5)
    background_strength: float | None = Field(None, ge=0.0, le=1.0)
    deconvolution: bool = False
    deconvolution_iterations: int | None = Field(None, ge=1, le=50)
    gradient_model: Literal["polynomial", "spline"] | None = None  # None: polynomial, or spline when its residual is large
    fine_sharpen: float | None = Field(None, ge=0.0, le=1.0)  # Moon & planets: small-scale wavelet sharpening
    surface_mode: bool = False  # Moon, Sun, planets: display anchored at the surface; Moon colour balanced on its disc


class AIRecipe(_Strict):
    """Optional learned (AI) tools; each replaces a classical step and is skipped with a reason if its model is missing."""

    background: bool = False  # GraXpert background extraction instead of the polynomial gradient model (linear only)
    denoise: bool = False  # GraXpert denoising instead of wavelet denoise; strength = the Noise reduction slider
    stars: bool = False  # Dark Star separation: finish the starless image, add the stars back (linear only)
    star_brightness: float = Field(1.0, ge=0.0, le=1.0, description="Fraction of separated star brightness added back to the display")
    star_size: float = Field(1.0, ge=0.5, le=1.0, description="Display size of the separated stars (1 = unchanged)")
    sharpen: bool = False  # Cosmic Clarity Sharpen (non-stellar and stellar models)
    sharpen_amount: float = Field(0.5, ge=0.0, le=1.0, description="Non-stellar sharpening strength")
    sharpen_stars: float = Field(0.5, ge=0.0, le=1.0, description="Stellar sharpening strength (0 skips the stellar model)")


class ObjectColorRecipe(_Strict):
    reds: float = Field(0.0, ge=-1.0, le=1.0)
    blues: float = Field(0.0, ge=-1.0, le=1.0)
    greens: float = Field(0.0, ge=-1.0, le=1.0)

    @property
    def active(self) -> bool:
        return bool(self.reds or self.blues or self.greens)


class FocusStretchRecipe(_Strict):
    enabled: bool = False
    strength: float = Field(0.5, ge=0.0, le=1.0)
    focus: float = Field(0.2, ge=0.0, le=1.0)
    protect_shadows: bool = True
    protect_highlights: bool = True


class Recipe(_Strict):
    schema_version: int = RECIPE_SCHEMA_VERSION
    preset: str = "natural"
    auto_preset: bool = False  # choose the look from image measurements (never from the object's name)
    look: LookRecipe = LookRecipe()
    auto: AutoRecipe = AutoRecipe()
    tone: ToneRecipe = ToneRecipe()
    background: BackgroundRecipe = BackgroundRecipe()
    protect_regions: bool = True
    advanced: AdvancedRecipe = AdvancedRecipe()
    ai: AIRecipe = AIRecipe()
    object_color: ObjectColorRecipe = ObjectColorRecipe()
    focus_stretch: FocusStretchRecipe = FocusStretchRecipe()
    catalog_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    catalog_builtin: bool = False  # Accurate star colours: built-in Gaia catalog through the image's sky solution
    hubble_strength: float = Field(0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _one_catalog(self) -> "Recipe":
        if self.catalog_builtin and self.catalog_sha256:
            raise ValueError("Use either Accurate star colours (built-in catalog) or an imported reference catalog, not both.")
        return self


class RecipeCompatibilityError(ValueError):
    """Raised for recipes this engine cannot run, with migration guidance."""


def parse_recipe(data: dict) -> Recipe:
    version = data.get("schema_version", RECIPE_SCHEMA_VERSION)
    if version in MIGRATABLE_SCHEMAS:
        data = {**data, "schema_version": RECIPE_SCHEMA_VERSION}
    elif version != RECIPE_SCHEMA_VERSION:
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


BUILTIN_PRESET_NAMES = {
    "auto": "Auto",
    "natural": "Natural",
    "vivid": "Vivid",
    "faint-detail": "Faint detail",
    "bright-core": "Bright core (HDR)",
    "star-field": "Star field",
    "seestar-match": "Seestar match",
    "moon-planets": "Moon & planets",
}
DEFAULT_PRESET = "auto"


def builtin_presets() -> dict[str, Recipe]:
    """Rendering styles chosen by the user (never inferred from the object's name). ``auto`` resolves per image to one of
    natural / faint-detail / bright-core / star-field from measurements (see ``auto_preset.py``)."""
    return {
        "auto": Recipe(preset="auto", auto_preset=True),
        "natural": Recipe(preset="natural"),
        "vivid": Recipe(preset="vivid", look=LookRecipe(background=0.10, contrast=0.5, color=0.6, detail=0.35, star_color=0.3)),
        "faint-detail": Recipe(
            preset="faint-detail", look=LookRecipe(background=0.16, stretch=0.5, contrast=0.15, color=0.4, detail=0.15, noise=0.75)
        ),
        "bright-core": Recipe(
            preset="bright-core", look=LookRecipe(contrast=0.25, color=0.33, detail=0.35), advanced=AdvancedRecipe(hdr_amount=0.8)
        ),
        "star-field": Recipe(
            preset="star-field", look=LookRecipe(background=0.10, stretch=-0.3, color=0.3, detail=0.0, noise=0.35, star_color=0.5),
            advanced=AdvancedRecipe(star_stretch_amount=0.6),
        ),
        "seestar-match": Recipe(preset="seestar-match", look=LookRecipe(background=0.15, contrast=0.0, color=0.17, detail=0.0, noise=0.4)),
        # Moon, Sun and planets (bright surfaces, few or no stars): a gentle stretch anchored at the surface (surface mode
        # also turns the star stretch off: a planet would be softened like a star), no core compression, and small-scale
        # wavelet sharpening instead of the Detail stage (which steps back from hard edges).
        "moon-planets": Recipe(
            preset="moon-planets", look=LookRecipe(background=0.04, stretch=-1.0, contrast=0.3, color=0.2, detail=0.0, noise=0.3,
                                                   protect_cores=False),
            advanced=AdvancedRecipe(fine_sharpen=0.6, stretch_log_d=0.5, surface_mode=True),
        ),
    }


def no_operations_recipe() -> Recipe:
    """An explicit no-operations recipe (supported; reproduces decoded display pixels)."""
    return Recipe(
        preset="custom",
        look=LookRecipe(contrast=0.0, color=0.0, detail=0.0, noise=0.0, protect_cores=False),
        auto=AutoRecipe(neutralize=False, gradient=False, white_balance=False, green_removal=False, star_stretch=False,
                        cosmetic=False, halo_reduction=False, banding=False),
        tone=ToneRecipe(enabled=False),
        background=BackgroundRecipe(enabled=False),
        protect_regions=False,
    )
