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


class StackCreate(StackFolders):
    request_key: str = Field(min_length=8, max_length=80)
    scale: Literal[1, 2] = 1
    grading: Literal["off", "lenient", "standard", "strict"] = "standard"
    rejection: Literal["sigma", "none"] = "sigma"
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


class BatchExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_ids: list[str] = Field(min_length=1, max_length=200)
    include: list[Literal["tiff", "jpeg", "comparison", "fits", "linear-tiff"]] = Field(default_factory=list)


class EditExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotation: int = Field(default=0, ge=-180, le=180)
    zoom: float = Field(default=1, ge=1, le=4)
    pan_x: float = Field(default=0, ge=-1, le=1)
    pan_y: float = Field(default=0, ge=-1, le=1)
    target: str = Field(default="", max_length=80)
    label: str = Field(default="", max_length=120)
    format: Literal["png", "jpeg"] = "png"


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False
