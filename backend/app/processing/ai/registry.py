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
COSMIC_SHARPEN_ATTRIBUTION = "Seti Astro — Cosmic Clarity Sharpen (Franklin Marek)"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    tool: str  # background | denoise | stars | sharpen
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
        *(
            ModelSpec(
                id=mid, tool="sharpen", title=title, file=fname, version="AI3.5s",
                url=f"https://github.com/setiastro/cosmicclarity/releases/download/Windows/{fname}", sha256=sha, size=size,
                license=COSMIC_LICENSE, license_url=COSMIC_LICENSE_URL, attribution=COSMIC_SHARPEN_ATTRIBUTION,
                source="https://github.com/setiastro/cosmicclarity",
            )
            for mid, title, fname, sha, size in (
                ("sharpen-stellar", "Cosmic Clarity Sharpen (stars)", "deep_sharp_stellar_cnn_AI3_5s.onnx",
                 "27729fb769300849a858a169db767bacfe5a884f20e1ffdd5db7c69e750b0f5a", 11_795_474),
                ("sharpen-nonstellar-1", "Cosmic Clarity Sharpen (detail, radius 1)", "deep_nonstellar_sharp_cnn_radius_1AI3_5s.onnx",
                 "71c1eda5a142f70d5c7df80daf5d96ceed811217db62071f0c127a32bb86b6b7", 11_797_802),
                ("sharpen-nonstellar-2", "Cosmic Clarity Sharpen (detail, radius 2)", "deep_nonstellar_sharp_cnn_radius_2AI3_5s.onnx",
                 "21691f14cfa59fea9bd0c6c912830cc70e25cd410f3fb07660c4aab2fd6817a0", 11_797_802),
                ("sharpen-nonstellar-4", "Cosmic Clarity Sharpen (detail, radius 4)", "deep_nonstellar_sharp_cnn_radius_4AI3_5s.onnx",
                 "4c64b5ffa112a954b40c3839b596ef80e64c58899fabf5f8aa2b77d28413734c", 11_797_802),
                ("sharpen-nonstellar-8", "Cosmic Clarity Sharpen (detail, radius 8)", "deep_nonstellar_sharp_cnn_radius_8AI3_5s.onnx",
                 "1a18de389315e1b5696040dd7725eec30cac9eb2ec5a982839ca0f6b8f24333f", 11_797_802),
            )
        ),
    )
}

# Super-resolution models published alongside these are never listed, downloaded or used (fidelity rule 1).
TOOL_MODELS = {
    "background": ["graxpert-background"], "denoise": ["graxpert-denoise"], "stars": ["darkstar-color", "darkstar-mono"],
    "sharpen": ["sharpen-stellar", "sharpen-nonstellar-1", "sharpen-nonstellar-2", "sharpen-nonstellar-4", "sharpen-nonstellar-8"],
}
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
