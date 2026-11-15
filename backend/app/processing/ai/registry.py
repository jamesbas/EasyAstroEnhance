"""Pinned model files for the optional AI tools (fixed URLs and SHA-256; nothing user-supplied is downloaded)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

GRAXPERT_LICENSE = "CC BY-NC-SA 4.0 (non-commercial use)"
GRAXPERT_LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
GRAXPERT_ATTRIBUTION = "GraXpert Development Team and contributors (graxpert.com)"
COSMIC_LICENSE = "MIT"
COSMIC_LICENSE_URL = "https://github.com/setiastro/cosmicclarity/blob/main/LICENSE"
COSMIC_ATTRIBUTION = "Seti Astro — Cosmic Clarity Dark Star (Franklin Marek)"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    tool: str  # background | denoise | stars
    title: str
    file: str
    version: str
    url: str
    sha256: str
    size: int
    license: str
    license_url: str
    attribution: str
    source: str
    graxpert_dir: str | None = None  # folder of an existing GraXpert installation that may hold the same file

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MODELS: dict[str, ModelSpec] = {
    m.id: m for m in (
        ModelSpec(
            id="graxpert-background", tool="background", title="GraXpert background extraction", file="graxpert-background-1.0.1.onnx",
            version="1.0.1", url="https://huggingface.co/jromanghf/graxpert-models/resolve/main/graxpert-background-1.0.1.onnx",
            sha256="4ed3ef68c9f44e821ea4e47572770bb9d4d5df447feae3e758d4c0480fca1f03", size=217_663_463,
            license=GRAXPERT_LICENSE, license_url=GRAXPERT_LICENSE_URL, attribution=GRAXPERT_ATTRIBUTION,
            source="https://github.com/Steffenhir/GraXpert", graxpert_dir="bge-ai-models",
        ),
        ModelSpec(
            id="graxpert-denoise", tool="denoise", title="GraXpert denoising", file="graxpert-denoise-3.0.2.onnx",
            version="3.0.2", url="https://huggingface.co/jromanghf/graxpert-models/resolve/main/graxpert-denoise-3.0.2.onnx",
            sha256="e61c880e7fb955917e91141660e66801c9de5c4f3d9946dc449e5a7dd7346563", size=477_703_971,
            license=GRAXPERT_LICENSE, license_url=GRAXPERT_LICENSE_URL, attribution=GRAXPERT_ATTRIBUTION,
            source="https://github.com/Steffenhir/GraXpert", graxpert_dir="denoise-ai-models",
        ),
        ModelSpec(
            id="darkstar-color", tool="stars", title="Dark Star star separation (colour)", file="darkstar_v2.1c.onnx",
            version="2.1c", url="https://github.com/setiastro/cosmicclarity/releases/download/Windows/darkstar_v2.1c.onnx",
            sha256="d9c3ab0ee808cbbe576aa3ea4c806b1e3117e47d807603bf03c0bb2f849667a6", size=15_184_572,
            license=COSMIC_LICENSE, license_url=COSMIC_LICENSE_URL, attribution=COSMIC_ATTRIBUTION,
            source="https://github.com/setiastro/cosmicclarity",
        ),
        ModelSpec(
            id="darkstar-mono", tool="stars", title="Dark Star star separation (monochrome)", file="darkstar_v2.1.onnx",
            version="2.1", url="https://github.com/setiastro/cosmicclarity/releases/download/Windows/darkstar_v2.1.onnx",
            sha256="e10a1e4ff2b0a47d35035b947fd0cb392bb047a3356e46b7e1c8807aff664917", size=15_184_572,
            license=COSMIC_LICENSE, license_url=COSMIC_LICENSE_URL, attribution=COSMIC_ATTRIBUTION,
            source="https://github.com/setiastro/cosmicclarity",
        ),
    )
}

TOOL_MODELS = {"background": ["graxpert-background"], "denoise": ["graxpert-denoise"], "stars": ["darkstar-color", "darkstar-mono"]}
VERIFIED_SUFFIX = ".sha256"


def model_file(models_dir: Path, spec: ModelSpec) -> Path:
    return Path(models_dir) / spec.file


def installed(models_dir: Path | None, spec: ModelSpec) -> Path | None:
    """The verified model file, or None. The SHA-256 is checked once at download; a sidecar file records it."""
    if models_dir is None:
        return None
    p = model_file(models_dir, spec)
    side = p.with_name(p.name + VERIFIED_SUFFIX)
    try:
        if p.stat().st_size == spec.size and side.read_text(encoding="ascii").strip() == spec.sha256:
            return p
    except OSError:
        return None
    return None
