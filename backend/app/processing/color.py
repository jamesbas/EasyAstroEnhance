"""Color handling in the display domain: luminance, guarded luminance-ratio reconstruction,
hue-preserving gamut mapping and protected saturation. Written against ``xp`` (NumPy/CuPy)."""
from __future__ import annotations

from .tone import smoothstep

W_R, W_G, W_B = 0.2126, 0.7152, 0.0722
RATIO_CAP = 6.0
DARK_BLEND = 0.08  # below this luminance reconstruction blends toward an additive shift
EPS = 1e-6


def luminance(xp, x):
    """Display-domain luma weights (not physical radiometry)."""
    if x.ndim == 2:
        return x
    return x[..., 0] * W_R + x[..., 1] * W_G + x[..., 2] * W_B


def reconstruct_rgb(xp, x, L0, L1):
    """Move RGB from luminance ``L0`` to ``L1`` without blindly multiplying by huge ratios:
    multiplicative where signal is strong, an additive shift in the dark (capped ratio)."""
    if x.ndim == 2:
        return L1
    safe = L0 > EPS
    ratio = xp.where(safe, L1 / xp.maximum(L0, EPS), 1.0)
    ratio = xp.minimum(ratio, RATIO_CAP)
    mul = x * ratio[..., None]
    add = x + (L1 - L0)[..., None]
    w = smoothstep(xp, L0 / DARK_BLEND)[..., None]
    return w * mul + (1.0 - w) * add


def _fit_factor(xp, lum_c, d):
    """Largest f (>=0) such that lum_c + f*d stays inside [0, 1] for all channels."""
    lc = lum_c[..., None]
    big = 1e9
    pos = xp.where(d > 1e-12, (1.0 - lc) / xp.maximum(d, 1e-12), big)
    neg = xp.where(d < -1e-12, lc / xp.maximum(-d, 1e-12), big)
    return xp.minimum(pos.min(axis=-1), neg.min(axis=-1))


def gamut_fit(xp, y):
    """Desaturate toward the pixel's own luminance only where a channel leaves [0, 1].
    Preserves hue far better than independent per-channel clipping."""
    if y.ndim == 2:
        return y
    ly = luminance(xp, y)
    lc = xp.clip(ly, 0.0, 1.0)
    inside = ((y >= 0.0) & (y <= 1.0)).all(axis=-1)
    d = y - ly[..., None]
    f = xp.clip(_fit_factor(xp, lc, d), 0.0, 1.0)
    fitted = lc[..., None] + f[..., None] * d
    return xp.where(inside[..., None], y, fitted)


def saturate(xp, y, amount: float):
    """Boost existing color (saturation >= 1) about the pixel's luminance. The boost fades near black
    (noise) and near white, and is limited per pixel so no channel leaves [0, 1]."""
    if y.ndim == 2 or amount <= 1.0:
        return y
    ly = luminance(xp, y)
    lc = xp.clip(ly, 0.0, 1.0)
    d = y - ly[..., None]
    fade = smoothstep(xp, lc / 0.06) * (1.0 - smoothstep(xp, (lc - 0.85) / 0.15))
    s_eff = 1.0 + (amount - 1.0) * fade
    f = xp.maximum(1.0, xp.minimum(s_eff, _fit_factor(xp, lc, d)))
    return ly[..., None] + f[..., None] * d
