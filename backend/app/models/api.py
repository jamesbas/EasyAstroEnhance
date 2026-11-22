"""Pydantic request/response models for the local /api/v1 API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..processing.recipe import Recipe


class Rect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int
    y: int
    w: int
    h: int


class InterpretationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hdu: int | None = None
    layout: str | None = None
    state: Literal["linear", "rendered", "unsure"] | None = None
    dualband_confirmed: bool | None = None


class RegionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regions: list[Rect] = Field(default_factory=list, max_length=32)


class BackgroundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["constant", "planar"]
    samples: list[Rect] = Field(default_factory=list, max_length=64)
    strength: float = Field(0.5, ge=0.0, le=1.0)
    confirmed: bool = False


class PresetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    recipe: dict[str, Any]


class PresetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=60)
    recipe: dict[str, Any] | None = None


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=80)
    asset_ids: list[str] = Field(min_length=1, max_length=50)
    recipe: Recipe
    preset_id: str | None = None
    force: bool = False


class StackFolders(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder: str = Field(min_length=1, max_length=500)
    mode: Literal["auto", "subs", "sessions"] = "auto"
    darks: str | None = Field(default=None, max_length=500)
    flats: str | None = Field(default=None, max_length=500)
    bias: str | None = Field(default=None, max_length=500)
    darkflats: str | None = Field(default=None, max_length=500)
    mosaic: bool | None = None  # None: detected from the frames (Seestar mosaic sub-frames or spread pointings)


class StackCreate(StackFolders):
    request_key: str = Field(min_length=8, max_length=80)
    scale: Literal[1, 2] = 1
    grading: Literal["off", "lenient", "standard", "strict"] = "standard"
    rejection: Literal["sigma", "none"] = "sigma"
    color_balance: bool = True
    auto_enhance: bool = False
    recipe: Recipe | None = None
    preset_id: str | None = None


class ComputePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: Literal["auto", "gpu", "cpu"] | None = None
    gpu_memory_fraction: float | None = Field(None, ge=0.1, le=0.7)
    ram_fraction: float | None = Field(None, ge=0.2, le=0.8)


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strip_location: bool | None = None
    keep_runs_per_image: int | None = Field(None, ge=0, le=50)


class BatchExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_ids: list[str] = Field(min_length=1, max_length=200)
    include: list[Literal["tiff", "jpeg", "comparison", "fits", "linear-tiff"]] = Field(default_factory=list)


class AnnotationsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objects: bool = False
    hidden: list[str] = Field(default_factory=list, max_length=500)
    max_mag: float | None = Field(default=None, ge=0, le=20)
    compass: bool = False
    scale_bar: bool = False


CaptionPosition = Literal["bottom-left", "bottom-center", "bottom-right", "top-left", "top-center", "top-right"]


class CaptionPlacementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: CaptionPosition = "bottom-left"
    size: float = Field(default=1.0, ge=0.5, le=3)  # relative to the standard caption size


class TextStyleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    font: Literal["sans", "serif", "script", "mono"] = "sans"
    color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    box: bool = True


class EditExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotation: int = Field(default=0, ge=-180, le=180)
    zoom: float = Field(default=1, ge=1, le=4)
    pan_x: float = Field(default=0, ge=-1, le=1)
    pan_y: float = Field(default=0, ge=-1, le=1)
    target: str = Field(default="", max_length=80)
    label: str = Field(default="", max_length=120)
    format: Literal["png", "jpeg"] = "png"
    annotations: AnnotationsIn = AnnotationsIn()
    text_style: TextStyleIn = TextStyleIn()
    target_place: CaptionPlacementIn = CaptionPlacementIn()
    label_place: CaptionPlacementIn = CaptionPlacementIn()


class CurrentRunIn(BaseModel):
    """Go back to an earlier result of the image."""
    run_id: str = Field(min_length=1, max_length=80)


class FramingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotation: int = Field(default=0, ge=-180, le=180)
    zoom: float = Field(default=1, ge=1, le=4)
    pan_x: float = Field(default=0, ge=-1, le=1)
    pan_y: float = Field(default=0, ge=-1, le=1)
    max_mag: float | None = Field(default=None, ge=0, le=20)


class PresetPreviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    recipe: Recipe


class PresetPreviewsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[PresetPreviewItem] = Field(min_length=1, max_length=16)


class SkySolveIn(BaseModel):
    """Optional hints for files without usable pointing data (all optional; none = use the file's own header)."""
    model_config = ConfigDict(extra="forbid")
    ra: float | None = Field(default=None, ge=0, lt=360)
    dec: float | None = Field(default=None, ge=-90, le=90)
    field_width_deg: float | None = Field(default=None, gt=0.05, le=20)
    name: str | None = Field(default=None, min_length=1, max_length=60)


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(min_length=1, max_length=50)


class SeestarScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str | None = Field(default=None, max_length=500)


class FolderBrowseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str | None = Field(default=None, max_length=500)


class LivePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe: Recipe


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False
