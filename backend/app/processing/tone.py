"""Tone mapping: base curves and the bounded manual offsets (brightness, shadows, highlights, black point).

All manual adjustments compose into ONE monotonic transform applied once, in a fixed order:
black point -> brightness (2**EV) -> shadows -> highlights. Neutral offsets add no transform.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

SHADOW_AMPLITUDE = 0.12
HIGHLIGHT_AMPLITUDE = 0.12
_BUMP_NORM = 27.0 / 4.0  # t*(1-t)^2 peaks at 4/27; normalized to peak 1


@dataclass(frozen=True)
class ManualTone:
    brightness_ev: float = 0.0
    shadows: float = 0.0
    highlights: float = 0.0
    black_point: float = 0.0

    @property
    def neutral(self) -> bool:
        return not (self.brightness_ev or self.shadows or self.highlights or self.black_point)

    def to_dict(self) -> dict[str, Any]:
        return {
            "brightness_ev": self.brightness_ev,
            "shadows": self.shadows,
            "highlights": self.highlights,
            "black_point": self.black_point,
            "order": ["black_point", "brightness_ev", "shadows", "highlights"],
            "shadow_curve": f"t + {SHADOW_AMPLITUDE}*shadows*27/4*t*(1-t)^2 on t in [0,1]",
            "highlight_curve": f"t + {HIGHLIGHT_AMPLITUDE}*highlights*27/4*(1-t)*t^2 on t in [0,1]",
        }


def _smooth_shadow(xp, t):
    c = xp.clip(t, 0.0, 1.0)
    return _BUMP_NORM * c * (1.0 - c) ** 2


def _smooth_highlight(xp, t):
    c = xp.clip(t, 0.0, 1.0)
    return _BUMP_NORM * (1.0 - c) * c**2


def apply_manual(xp, t, m: ManualTone):
    """Apply the composed manual transform to display luminance ``t`` (may exceed [0,1])."""
    if m.neutral:
        return t
    if m.black_point:
        t = (t - m.black_point) / (1.0 - m.black_point)
    if m.brightness_ev:
        t = t * float(2.0**m.brightness_ev)
    if m.shadows:
        t = t + SHADOW_AMPLITUDE * m.shadows * _smooth_shadow(xp, t)
    if m.highlights:
        t = t + HIGHLIGHT_AMPLITUDE * m.highlights * _smooth_highlight(xp, t)
    return t


def validate_monotonic(m: ManualTone) -> None:
    """Reject curve settings that would reverse brightness order."""
    grid = np.linspace(-0.2, 1.5, 4097, dtype=np.float64)
    out = apply_manual(np, grid, m)
    if np.any(np.diff(out) < -1e-12):
        raise ValueError("Tone settings would reverse brightness order; reduce Shadows/Highlights.")


def rational_gain(xp, L, gain: float):
    """Baseline rational midtone curve g*L/(1+(g-1)L); identity at g=1. Linear (slope g) below zero."""
    if gain == 1.0:
        return L
    pos = xp.maximum(L, 0.0)
    mapped = gain * pos / (1.0 + (gain - 1.0) * pos)
    return xp.where(L < 0, gain * L, mapped)


def asinh_map(xp, s_norm, k: float):
    """t = asinh(k*s)/asinh(k) for s = (L - black)/span >= 0."""
    return xp.arcsinh(k * s_norm) / float(np.arcsinh(k))


def smoothstep(xp, x):
    t = xp.clip(x, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)
