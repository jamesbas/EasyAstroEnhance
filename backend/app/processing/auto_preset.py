"""Auto preset (engine 1.6): choose a built-in rendering style per image from measurements of the image itself.

The measurements use a small binned copy (about 1 MP) shown with the frozen baseline display stretch: bright extended
cores, how much of the frame holds extended (non-star) signal and how faint it is, and how many stars there are. The
object's name, coordinates and any reference image are never used (fidelity rule 2). The choice and the measured values
are recorded in the processing report; the chosen preset's settings then run exactly as if the user had picked it.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import ndimage

from .backends.numpy_backend import NumpyBackend
from .color import luminance
from .imagedata import ImageData
from .linear_prep import clipped_stats
from .masks import masked_gaussian
from .star_protection import detect_stars
from .stretch import derive_frame, derive_normalization, fixed_map, to_normalized

PROXY_PIXELS = 1_000_000
SMOOTH_SIGMA = 3.0  # proxy pixels
EXT_LEVEL = 0.03  # extended signal: smoothed star-free display luminance this far above the sky
CORE_LEVEL = 0.75  # a bright core: smoothed display luminance above this in the baseline stretch
CORE_FRACTION = 0.002  # ... over at least this share of the frame
FAINT_EXT_FRACTION = 0.07  # extended signal covers a good part of the frame ...
FAINT_LEVEL = 0.12  # ... and is faint: its median rises less than this above the sky
STARFIELD_EXT_FRACTION = 0.005  # almost no extended signal (thin filaments and small galaxies stay on Natural) ...
STARFIELD_STARS_PER_MP = 100  # ... and a populated star field
CHOICES = ("natural", "faint-detail", "bright-core", "star-field")


def _bin(a: np.ndarray, valid: np.ndarray, f: int) -> tuple[np.ndarray, np.ndarray]:
    h, w = valid.shape[0] // f * f, valid.shape[1] // f * f
    v = valid[:h, :w].astype(np.float32)
    x = np.where(valid[..., None] if a.ndim == 3 else valid, a, 0)[:h, :w].astype(np.float64)
    shape = (h // f, f, w // f, f) + ((a.shape[2],) if a.ndim == 3 else ())
    vs = v.reshape(h // f, f, w // f, f).sum(axis=(1, 3))
    xs = x.reshape(shape).sum(axis=(1, 3))
    out = xs / np.maximum(vs, 1)[..., None] if a.ndim == 3 else xs / np.maximum(vs, 1)
    return out.astype(np.float32), vs >= 0.5 * f * f


def measure(image: ImageData) -> dict[str, Any]:
    h, w = image.height, image.width
    f = max(1, math.ceil(math.sqrt(h * w / PROXY_PIXELS)))
    px, valid = _bin(image.pixels, image.valid_mask, f)
    if image.domain == "linear":
        offset, scale = derive_normalization(px, valid)
        u = to_normalized(px, offset, scale)
        frame = derive_frame(u, valid, offset, scale)
        disp = fixed_map(np, u, frame)[0]
        work = u
    else:
        disp = np.clip(px, 0.0, 1.0)
        work = disp
    L = luminance(np, disp).astype(np.float32)
    stars = detect_stars(work, valid, 1e-6)
    accepted = int(stars.stats.get("accepted", 0))
    starfree = valid.copy()
    if stars.hard is not None:
        starfree &= ~ndimage.binary_dilation(stars.hard, iterations=2)
    S = masked_gaussian(NumpyBackend(), L, starfree.astype(np.float32), SMOOTH_SIGMA)
    sky, _ = clipped_stats(S[starfree] if starfree.any() else S[valid])
    ext = (S > sky + EXT_LEVEL) & starfree
    core = (S > CORE_LEVEL) & starfree
    n = max(int(valid.sum()), 1)
    return {
        "proxy": {"factor": f, "width": int(px.shape[1]), "height": int(px.shape[0])},
        "sky_display": float(sky),
        "extended_fraction": float(ext.sum() / n),
        "extended_median_above_sky": float(np.median(S[ext] - sky)) if ext.any() else 0.0,
        "core_fraction": float(core.sum() / n),
        "stars_per_mp": float(accepted / (h * w / 1e6)),
        "stars": accepted,
    }


def choose(m: dict[str, Any]) -> tuple[str, list[str]]:
    """The preset id and the reasons, in plain words."""
    if m["core_fraction"] >= CORE_FRACTION:
        return "bright-core", [f"a bright extended core covers {m['core_fraction']:.2%} of the frame"]
    if m["extended_fraction"] >= FAINT_EXT_FRACTION and m["extended_median_above_sky"] < FAINT_LEVEL:
        return "faint-detail", [f"faint extended signal covers {m['extended_fraction']:.0%} of the frame "
                                f"(median {m['extended_median_above_sky']:.3f} above the sky)"]
    if m["extended_fraction"] < STARFIELD_EXT_FRACTION and m["stars_per_mp"] >= STARFIELD_STARS_PER_MP:
        return "star-field", [f"mostly stars: {m['stars_per_mp']:.0f} stars per megapixel and extended signal in only "
                              f"{m['extended_fraction']:.1%} of the frame"]
    return "natural", ["no bright core, little faint extended signal and not a dense star field"]


_MEMO: dict[tuple, dict[str, Any]] = {}


def resolve(image: ImageData, recipe):
    """(recipe to run, report entry). An Auto recipe takes the look and the preset's exact Advanced values of the chosen
    built-in preset; everything else the user set (AI tools, automatic stages, tone, colour tools...) is kept."""
    from .recipe import BUILTIN_PRESET_NAMES, builtin_presets

    if not recipe.auto_preset:
        return recipe, None
    key = (image.source_hash, image.pixels.shape, image.domain, image.source_format)
    m = _MEMO.get(key)
    if m is None:
        m = measure(image)
        if len(_MEMO) > 8:
            _MEMO.clear()
        _MEMO[key] = m
    choice, reasons = choose(m)
    preset = builtin_presets()[choice]
    advanced = recipe.advanced.model_copy(update={k: v for k, v in preset.advanced.model_dump().items() if v is not None and v is not False})
    resolved = recipe.model_copy(update={"look": preset.look, "advanced": advanced, "auto_preset": False, "preset": choice})
    return resolved, {
        "chosen": choice, "label": BUILTIN_PRESET_NAMES[choice], "reasons": reasons, "measurements": m,
        "method": "measured on a ~1 MP binned copy shown with the baseline display stretch; the object's name is never used",
        "look": preset.look.model_dump(),
    }
