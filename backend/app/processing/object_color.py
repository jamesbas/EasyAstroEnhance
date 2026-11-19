"""Selective saturation around luminance, with smooth hue and signal masks."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

from .color import _fit_factor, luminance
from .imagedata import LUMA
from .recipe import ObjectColorRecipe
from .tone import smoothstep

HubbleInput = Literal["dualband", "unknown", "broadband", "unsupported"]


def hubble_input(header: Mapping | None, confirmed: bool = False) -> HubbleInput:
    if header is None:
        return "dualband" if confirmed else "unknown"
    mix = str(header.get("EAEMIX", "")).upper()
    if mix == "HOO":
        return "dualband"
    if mix in {"RGB", "LRGB", "HA-RGB"}:
        return "broadband"
    if mix:
        return "unsupported"
    filter_name = str(header.get("FILTER", "")).upper()
    key = re.sub(r"[^A-Z0-9]", "", filter_name)
    if key in {"IRCUT", "UVIRCUT", "CLEAR", "BROADBAND", "RGB", "LRGB", "NONE", "NIR"}:
        return "broadband"
    if key in {"HAOIII", "OIIIHA", "HALPHAOIII", "OIIIHALPHA", "HOO"}:
        return "dualband"
    # Seestar specifically uses LP for its built-in H-alpha/OIII filter, not generic light-pollution glass.
    instrument = " ".join(str(header.get(k, "")).upper() for k in ("INSTRUME", "TELESCOP"))
    if key == "LP" and "SEESTAR" in instrument:
        return "dualband"
    if "SII" in key or key in {"HA", "HALPHA", "OIII", "O3", "SHO", "S2"}:
        return "unsupported"
    return "dualband" if confirmed else "unknown"


def _normalized_tint(tint: tuple[float, float, float]) -> tuple[float, ...]:
    light = sum(t * w for t, w in zip(tint, LUMA, strict=True))
    return tuple(t / light for t in tint)


GOLD = _normalized_tint((1.52, 1.0, 0.41))
TEAL = _normalized_tint((0.42, 1.15, 1.36))


def hubble_style(xp, display, signal, stars, valid, sky_rgb: tuple[float, ...], sigma: float, strength: float):
    """Display-only gold/teal blend driven by background-subtracted Ha and OIII proxies."""
    L = luminance(xp, display)
    r, g, b = xp.moveaxis(signal, -1, 0)
    ha = xp.maximum(r - sky_rgb[0], 0.0)
    oxygen = xp.maximum(0.5 * ((g - sky_rgb[1]) + (b - sky_rgb[2])), 0.0)
    noise = max(sigma, 1e-6)
    reliable = smoothstep(xp, (xp.maximum(ha, oxygen) - 3.0 * noise) / (5.0 * noise))
    fraction = smoothstep(xp, (ha / xp.maximum(ha + oxygen, noise) - 0.2) / 0.6)
    light = L[..., None]
    chroma = light * (xp.asarray(TEAL, dtype=display.dtype) - 1 + fraction[..., None] *
                      (xp.asarray(GOLD, dtype=display.dtype) - xp.asarray(TEAL, dtype=display.dtype)))
    limit = xp.clip(0.98 * _fit_factor(xp, L, chroma), 0.0, 1.0)
    mapped = light + chroma * limit[..., None]
    mask = reliable * valid * (1 - xp.clip(2 * stars, 0, 1)) * (1 - smoothstep(xp, (L - 0.72) / 0.25))
    return display + (strength * mask)[..., None] * (mapped - display), mask


def selective_color(xp, rgb, stars, valid, sky: float, sigma: float, recipe: ObjectColorRecipe, scale: float = 1.0):
    L = luminance(xp, rgb)
    r, g, b = xp.moveaxis(rgb, -1, 0)
    # Opponent hue angle: red 0 degrees, green 120, blue 240. A smooth window avoids color seams.
    theta = xp.arctan2(1.7320508 * (g - b), 2 * r - g - b)
    chroma = rgb.max(axis=-1) - rgb.min(axis=-1)
    signal = smoothstep(xp, (L - sky - max(sigma, 0.008)) / (3 * max(sigma, 0.008)))
    protection = valid * (1 - xp.clip(2 * stars, 0, 1)) * (1 - smoothstep(xp, (L - 0.78) / 0.22))
    weight = signal * protection * smoothstep(xp, (chroma - 0.015) / 0.045)
    amount = xp.zeros_like(L)
    mask = xp.zeros_like(L)
    for level, center in ((recipe.reds, 0.0), (recipe.greens, 1.75), (recipe.blues, -2.55)):
        if level:
            hue = smoothstep(xp, (xp.cos(theta - center) - 0.35) / 0.55)
            amount += level * hue
            mask = xp.maximum(mask, hue)
    delta = rgb - L[..., None]
    factor = xp.clip(1 + 0.65 * scale * weight * amount, 0.35, 1.65)
    fit = _fit_factor(xp, L, delta)
    factor = xp.where(factor > 1, xp.minimum(factor, xp.maximum(1, 1 + 0.95 * (fit - 1))), factor)
    out = xp.where((factor != 1)[..., None], L[..., None] + factor[..., None] * delta, rgb)
    return out, weight * mask
