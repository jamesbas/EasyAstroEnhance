"""Display stretches for linear data and the shared tone helpers.

* Baseline ("Original shown with a display stretch"): a linked STF/autostretch on the shared-normalized
  source, frozen per asset: shadows at the mean of ``median_c - 2.8 sigma_c``, one midtone balance chosen so
  the mean channel median lands on ``BASELINE_TARGET``. Linked, so the source's color cast stays visible.
* Enhanced: a color-preserving hyperbolic luminance stretch (VeraLux HyperMetric Stretch form)
  ``Ls = (asinh(D*L + b) - asinh(b)) / (asinh(D + b) - asinh(b))`` with highlight convergence
  ``rgb = Ls * (r * (1 - Ls**p) + Ls**p)`` (bright cores fade to white instead of saturated color blobs), then
  a midtone transfer function (MTF) that places the median sky exactly at the target background. The white
  point is the data's saturation level, so nothing is clipped by the stretch itself.
* The stretch factor D is auto-solved from statistics so the brightest extended (non-star) signal lands at a
  chosen display level; the Stretch slider shifts D in decades from there.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from .color import luminance
from .diagnostics import MAD_TO_SIGMA, percentile, strided
from .tone import smoothstep

FRAME_VERSION = 2
BASELINE_TARGET = 0.15
BASELINE_SHADOW_SIGMAS = 2.8
FLOOR_SIGMAS = 5.0  # display black floor below the sky; denoised sky noise has heavy tails, so 5 sigma keeps new black clipping << 0.1%
DEFAULT_B = 6.0
DEFAULT_P = 3.5
LOG_D_MIN, LOG_D_MAX = 0.0, 5.5
HI_TARGET_PROTECT = 0.88
HI_TARGET_OPEN = 0.96
HI_PERCENTILE = 99.9
STAR_D_FACTOR = 1.0 / 8.0
COLOR_CONFIDENCE_SIGMAS = 4.0


def mtf(xp, m: float, x):
    """Midtone transfer function: 0 -> 0, m -> 0.5, 1 -> 1."""
    return ((m - 1.0) * x) / ((2.0 * m - 1.0) * x - m)


def mtf_balance(target: float, x: float) -> float:
    """Midtone balance m such that MTF(m, x) = target (0 < x < 1)."""
    x = float(np.clip(x, 1e-9, 1.0 - 1e-9))
    return float(np.clip((target - 1.0) * x / ((2.0 * target - 1.0) * x - target), 1e-7, 1.0 - 1e-7))


# ------------------------------------------------------------------------------------------------ baseline
@dataclass(frozen=True)
class LinearFrame:
    """Frozen baseline display mapping, in shared-normalized units."""

    scale: float
    offset: float
    c0: float
    m: float
    target: float
    sky: float
    sigma_sky: float
    version: int = FRAME_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> "LinearFrame | None":
        """Return None for frames written by an older engine (they must be re-derived)."""
        if not d or int(d.get("version", 1)) != FRAME_VERSION:
            return None
        return LinearFrame(**{k: (int(d[k]) if k == "version" else float(d[k])) for k in LinearFrame.__dataclass_fields__})


def derive_normalization(pixels: np.ndarray, weight: np.ndarray) -> tuple[float, float]:
    """Shared (offset, scale). Offset is 0 (keeps the physical zero point and negatives); scale is the maximum
    valid value over all channels, so 1.0 is the data's saturation level and the white point of the display."""
    vals = pixels[weight] if pixels.ndim == 2 else pixels[weight].reshape(-1)
    if vals.size == 0:
        return 0.0, 1.0
    scale = float(np.max(vals))
    if not np.isfinite(scale) or scale <= 0:
        scale = float(np.max(np.abs(vals))) or 1.0
    return 0.0, scale


def derive_frame(u: np.ndarray, weight: np.ndarray, offset: float, scale: float, target: float = BASELINE_TARGET) -> LinearFrame:
    chans = [u] if u.ndim == 2 else [u[..., c] for c in range(u.shape[2])]
    meds, sigs = [], []
    for ch in chans:
        v = strided(ch[weight]).astype(np.float64)
        if v.size == 0:
            meds.append(0.0)
            sigs.append(0.0)
            continue
        md = float(np.median(v))
        meds.append(md)
        sigs.append(max(float(np.median(np.abs(v - md)) * MAD_TO_SIGMA), 1e-6))
    c0 = max(0.0, float(np.mean([m - BASELINE_SHADOW_SIGMAS * s for m, s in zip(meds, sigs)])))
    c0 = min(c0, 0.99)
    mean_med = float(np.mean(meds))
    m = mtf_balance(target, (mean_med - c0) / (1.0 - c0))
    return LinearFrame(scale, offset, c0, m, target, mean_med, float(np.mean(sigs)))


def fixed_map(xp, u, frame: LinearFrame):
    """Baseline display of normalized linear data: (display, display luminance). Negative physical values map
    to black in the display only; they are untouched in ``u``."""
    v = xp.clip((u - frame.c0) / (1.0 - frame.c0), 0.0, 1.0)
    y = xp.clip(mtf(xp, frame.m, v), 0.0, 1.0)  # float32 rounding can land a hair above 1 at the white point
    return y, luminance(xp, y)


def to_normalized(pixels: np.ndarray, offset: float, scale: float) -> np.ndarray:
    return ((pixels.astype(np.float64) - offset) / scale).astype(np.float32)


def from_normalized(u: np.ndarray, offset: float, scale: float, dtype) -> np.ndarray:
    return (u.astype(np.float64) * scale + offset).astype(dtype)


# ------------------------------------------------------------------------------------------------ enhanced stretch
def stretch_luminance(xp, x):
    """Equal-weight luminance used by the stretch (robust for strongly colored nebulae; ratios <= 3)."""
    if x.ndim == 2:
        return x
    return (x[..., 0] + x[..., 1] + x[..., 2]) * (1.0 / 3.0)


def hyperbolic(xp, L, D: float, b: float):
    den = float(np.arcsinh(D + b) - np.arcsinh(b))
    return (xp.arcsinh(D * L + b) - float(np.arcsinh(b))) / den


@dataclass(frozen=True)
class StretchParams:
    white: float
    D: float
    b: float
    p: float
    floor: float
    m: float
    target: float
    D_auto: float | None = None
    d_source: str = "auto"
    hi_level: float = 0.0
    hi_target: float = HI_TARGET_PROTECT
    hi_display: float = 0.0
    sky_level: float = 0.0
    sky_sigma: float = 0.0
    sky_display_sigma: float = 0.0
    pivot: float | None = None
    floor_sigmas: float = FLOOR_SIGMAS

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["log10_D"] = float(np.log10(self.D))
        d["formula"] = (
            "u = x / white; L = mean(u); Ls = (asinh(D*L+b)-asinh(b))/(asinh(D+b)-asinh(b)); "
            "rgb = Ls*(u/L*(1-Ls^p)+Ls^p); y = MTF(m, (rgb-floor)/(1-floor))"
        )
        if self.pivot is not None:
            d["formula"] = "Endpoint-normalized asinh(D * (L - pivot)), followed by sky-anchored MTF and highlight convergence."
        return d

    def gentler(self, factor: float = STAR_D_FACTOR) -> "StretchParams":
        """The same stretch with a smaller D, re-balanced so the sky lands at the same display level."""
        return solve_fixed(self.sky_level, self.sky_sigma, self.hi_level, self.white, self.target, max(1.0, self.D * factor), self.b, self.p,
                           self.hi_target, None, "star-gentle", self.pivot, self.floor_sigmas)


def _curve(xp, L, D: float, b: float, pivot: float | None):
    if pivot is None:
        return hyperbolic(xp, L, D, b)
    lo = float(np.arcsinh(-D * pivot))
    hi = float(np.arcsinh(D * (1 - pivot)))
    return (xp.arcsinh(D * (L - pivot)) - lo) / (hi - lo)


def apply_stretch(xp, x, sp: StretchParams):
    """``x``: processed linear data (sky on a positive pedestal). Returns display values in [0, 1].

    Color ratios are trusted only where the signal clears the sky noise: within ``COLOR_CONFIDENCE_SIGMAS`` of
    the sky they blend toward neutral, so per-channel noise is not turned into colored speckle or clipped
    channels (the faint-signal color is unreliable there anyway)."""
    u = xp.maximum(x * (1.0 / sp.white), 0.0)
    L = stretch_luminance(xp, u)
    Ls = xp.clip(_curve(xp, L, sp.D, sp.b, sp.pivot), 0.0, 1.0)
    if u.ndim == 3:
        r = u / xp.maximum(L, 1e-12)[..., None]
        sky_u, sig_u = sp.sky_level / sp.white, max(sp.sky_sigma / sp.white, 1e-12)
        conf = smoothstep(xp, (L - sky_u) / (COLOR_CONFIDENCE_SIGMAS * sig_u))[..., None]
        r = 1.0 + conf * (r - 1.0)
        k = (Ls ** sp.p)[..., None]
        y = Ls[..., None] * (r * (1.0 - k) + k)
        mx = y.max(axis=-1)
        y = xp.where((mx > 1.0)[..., None], y / xp.maximum(mx, 1e-12)[..., None], y)
    else:
        y = Ls
    v = xp.clip((y - sp.floor) / (1.0 - sp.floor), 0.0, 1.0)
    return mtf(xp, sp.m, v)


def _chain_parts(sky: float, sigma: float, hi: float, white: float, target: float, D: float, b: float,
                 pivot: float | None = None, floor_sigmas: float = FLOOR_SIGMAS):
    Hs = float(_curve(np, np.float64(sky / white), D, b, pivot))
    sp = float(_curve(np, np.float64((sky + sigma) / white), D, b, pivot))
    sm = float(_curve(np, np.float64(max(sky - sigma, 0.0) / white), D, b, pivot))
    s_pre = max((sp - sm) / 2.0, 1e-12)
    floor = max(0.0, Hs - floor_sigmas * s_pre)
    m = mtf_balance(target, (Hs - floor) / (1.0 - floor))
    Hh = float(_curve(np, np.float64(min(hi / white, 1.0)), D, b, pivot))
    out_hi = float(mtf(np, m, np.clip((Hh - floor) / (1.0 - floor), 0.0, 1.0)))
    s_disp = float(mtf(np, m, np.clip((sp - floor) / (1.0 - floor), 0, 1)) - mtf(np, m, np.clip((sm - floor) / (1.0 - floor), 0, 1))) / 2.0
    return floor, m, out_hi, s_disp


def solve_fixed(sky, sigma, hi, white, target, D, b, p, hi_target, D_auto, source,
                pivot: float | None = None, floor_sigmas: float = FLOOR_SIGMAS) -> StretchParams:
    floor, m, out_hi, s_disp = _chain_parts(sky, sigma, hi, white, target, D, b, pivot, floor_sigmas)
    return StretchParams(white, float(D), b, p, floor, m, target, D_auto, source, hi, hi_target, out_hi, sky, sigma, s_disp, pivot, floor_sigmas)


def solve_focus(sky: float, sigma: float, hi: float, white: float, target: float, strength: float, focus: float,
                protect_shadows: bool, protect_highlights: bool) -> StretchParams:
    hi = max(hi, sky + 3 * sigma)
    pivot = float(np.clip((sky + focus * (hi - sky)) / white, 0, 1))
    return solve_fixed(sky, sigma, hi, white, target, 10.0 ** (3.0 * strength), 0.0,
                       2.0 if protect_highlights else 6.0, HI_TARGET_PROTECT if protect_highlights else HI_TARGET_OPEN,
                       None, "manual-focus", pivot, 8.0 if protect_shadows else FLOOR_SIGMAS)


def solve_stretch(
    sky: float, sigma: float, hi: float, white: float, target: float, *, protect_cores: bool, amount: float,
    log_d: float | None = None, b: float | None = None, p: float | None = None, decades_per_unit: float = 0.75,
) -> StretchParams:
    """Choose D so the bright extended signal ``hi`` lands at the preset display level with the sky at ``target``;
    then shift by the Stretch slider. A fixed ``log_d`` (Advanced) bypasses the solver."""
    b = DEFAULT_B if b is None else float(b)
    p = DEFAULT_P if p is None else float(p)
    hi_target = HI_TARGET_PROTECT if protect_cores else HI_TARGET_OPEN
    hi = max(hi, sky + 3.0 * sigma)
    if log_d is not None:
        return solve_fixed(sky, sigma, hi, white, target, 10.0 ** float(log_d), b, p, hi_target, None, "advanced")
    grid = np.linspace(LOG_D_MIN, LOG_D_MAX, 111)
    outs = np.array([_chain_parts(sky, sigma, hi, white, target, 10.0**g, b)[2] for g in grid])
    below = np.nonzero(outs <= hi_target)[0]
    if below.size == 0:
        best = LOG_D_MAX
    elif below[0] == 0:
        best = LOG_D_MIN
    else:
        lo_g, hi_g = grid[below[0] - 1], grid[below[0]]
        for _ in range(40):
            mid = 0.5 * (lo_g + hi_g)
            if _chain_parts(sky, sigma, hi, white, target, 10.0**mid, b)[2] <= hi_target:
                hi_g = mid
            else:
                lo_g = mid
        best = hi_g
    D_auto = 10.0**best
    D = float(np.clip(D_auto * 10.0 ** (decades_per_unit * amount), 10.0**LOG_D_MIN, 10.0**LOG_D_MAX))
    return solve_fixed(sky, sigma, hi, white, target, D, b, p, hi_target, D_auto, "auto")


def stretch_statistics(x: np.ndarray, stat_weight: np.ndarray, star_hard: np.ndarray | None) -> tuple[float, float, float]:
    """Sky level, sky sigma and the bright extended-signal level of the stretch luminance (CPU)."""
    from .linear_prep import clipped_stats

    L = stretch_luminance(np, x)
    sky, sigma = clipped_stats(L[stat_weight])
    use = stat_weight if star_hard is None else (stat_weight & ~star_hard)
    hi = percentile(L[use], HI_PERCENTILE) if use.any() else sky + 10 * sigma
    return sky, max(sigma, 1e-9), hi


# ------------------------------------------------------------------------------------------------ rendered tone
def rendered_sky_balance(sky_after_gain: float, target: float) -> tuple[float, float]:
    """MTF midtone balance moving the (already rendered) sky toward ``target``, limited to 0.6x..1.6x of its
    current level so one button never makes a dramatically different image from a finished JPEG."""
    if sky_after_gain <= 1e-4:
        return 0.5, sky_after_gain
    goal = float(np.clip(target, 0.6 * sky_after_gain, 1.6 * sky_after_gain))
    return mtf_balance(goal, sky_after_gain), goal
