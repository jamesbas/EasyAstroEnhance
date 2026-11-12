"""Supervised background correction: robust sky-patch statistics, constant neutralization and an optional
first-order (planar) spatial model.

Only a plane ``a + b*x + c*y`` in normalized coordinates is ever fitted. Patches are confirmed by the user
(automatic checks cannot prove a patch is empty sky). The model is persisted per asset and run and is never
copied through presets or "Apply to all".
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.spatial import ConvexHull

from .color import luminance
from .diagnostics import MAD_TO_SIGMA, median_mad_sigma, percentile

MIN_PATCHES = {"constant": 3, "planar": 6}
MIN_PATCH_SIDE = 8
MIN_VALID_PIXELS = 64
MIN_VALID_FRACTION = 0.8
MAX_STAR_FRACTION_WARN = 0.05
MAX_STAR_FRACTION_ERROR = 0.4
MIN_SPAN = 0.5  # planar: patch centers must span at least half the frame on each axis
MIN_HULL_AREA = 0.08  # planar: convex hull of centers must cover >= 8% of the frame area
MAX_CONDITION_WARN = 30.0
MAX_CONDITION_ERROR = 100.0
DIM_FRACTION = 0.65  # per-patch statistic uses the dimmest 65% of pixels (excludes stars)


@dataclass
class Issue:
    level: str  # "error" blocks confirmation; "warning" is shown and may be accepted
    code: str
    message: str
    sample: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "code": self.code, "message": self.message, "sample": self.sample}


@dataclass
class BgModel:
    method: str
    channels: int
    offsets: list[float] = field(default_factory=list)  # per-channel sky level estimates
    reference_level: float = 0.0
    plane: dict[str, float] | None = None
    samples: list[dict[str, Any]] = field(default_factory=list)
    residuals: dict[str, Any] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def model_hash(self) -> str:
        payload = {
            "method": self.method,
            "samples": [[s["x"], s["y"], s["w"], s["h"]] for s in self.samples],
            "offsets": [round(v, 9) for v in self.offsets],
            "plane": None if not self.plane else {k: round(v, 9) for k, v in self.plane.items()},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "ok": self.ok,
            "model_hash": self.model_hash(),
            "channel_offsets": self.offsets,
            "reference_level": self.reference_level,
            "plane": self.plane,
            "samples": self.samples,
            "residuals": self.residuals,
            "issues": [i.as_dict() for i in self.issues],
        }


def _norm_coords(width: int, height: int, xs, ys):
    return 2.0 * (np.asarray(xs) + 0.5) / width - 1.0, 2.0 * (np.asarray(ys) + 0.5) / height - 1.0


def _overlap(a: dict[str, int], b: dict[str, int]) -> bool:
    return not (
        a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]
    )


def patch_estimate(work: np.ndarray, weight: np.ndarray, star_hard: np.ndarray | None, rect: dict[str, int]):
    """Channel-wise median of the dimmest 65% of usable pixels. Returns (estimate[C], n_used, star_fraction, info)."""
    sl = (slice(rect["y"], rect["y"] + rect["h"]), slice(rect["x"], rect["x"] + rect["w"]))
    use = weight[sl].copy()
    star_fraction = 0.0
    if star_hard is not None:
        star_fraction = float((star_hard[sl] & weight[sl]).mean())
        use &= ~star_hard[sl]
    patch = work[sl]
    n_total = rect["w"] * rect["h"]
    if use.sum() == 0:
        return None, 0, star_fraction, {}
    L = luminance(np, patch)[use]
    cut = np.quantile(L, DIM_FRACTION)
    keep = L <= cut
    vals = patch[use][keep] if patch.ndim == 3 else patch[use][keep]
    est = np.atleast_1d(np.median(vals, axis=0)).astype(np.float64)
    # Internal diagnostics for extended-signal evidence.
    _, sigma_p = median_mad_sigma(L)
    info = {"valid_fraction": float(use.sum() / n_total), "internal_sigma": sigma_p, "p95_excess": float(np.quantile(L, 0.95) - np.median(L))}
    ys, xs = np.nonzero(use)
    if len(xs) > 32:
        xc, yc = xs - xs.mean(), ys - ys.mean()
        info["internal_slope_x"] = float(np.polyfit(xc, L, 1)[0] * rect["w"])
        info["internal_slope_y"] = float(np.polyfit(yc, L, 1)[0] * rect["h"])
    return est, int(keep.sum()), star_fraction, info


def _huber_plane(xn, yn, v, floor: float):
    A = np.column_stack([np.ones_like(xn), xn, yn])
    w = np.ones_like(v)
    coef = np.zeros(3)
    for _ in range(30):
        sw = np.sqrt(w)
        coef, *_ = np.linalg.lstsq(A * sw[:, None], v * sw, rcond=None)
        res = v - A @ coef
        s = max(MAD_TO_SIGMA * float(np.median(np.abs(res - np.median(res)))), floor, 1e-12)
        k = 1.345 * s
        new_w = np.where(np.abs(res) <= k, 1.0, k / np.maximum(np.abs(res), 1e-12))
        if np.allclose(new_w, w, atol=1e-6):
            w = new_w
            break
        w = new_w
    res = v - A @ coef
    return coef, res, w, A


def build_model(
    work: np.ndarray,
    weight: np.ndarray,
    star_hard: np.ndarray | None,
    samples: list[dict[str, int]],
    method: str,
    sigma_pixel: float,
    protected: np.ndarray | None = None,
) -> BgModel:
    """Validate patches and fit the requested model. All checks are server-side; ``model.ok`` gates use."""
    h, w = weight.shape
    c = 1 if work.ndim == 2 else work.shape[2]
    model = BgModel(method=method, channels=c)
    issues = model.issues
    need = MIN_PATCHES[method]
    if len(samples) < need:
        issues.append(
            Issue("error", "TOO_FEW_PATCHES", f"{'Overall balance' if method == 'constant' else 'Uneven-sky correction'} needs at least {need} confirmed sky regions; {len(samples)} given.")
        )
        return model

    rects: list[dict[str, int]] = []
    for i, s in enumerate(samples):
        try:
            r = {k: int(s[k]) for k in ("x", "y", "w", "h")}
        except (KeyError, TypeError, ValueError):
            issues.append(Issue("error", "INVALID_PATCH", "Each sky region needs integer x, y, w and h.", i))
            continue
        if r["w"] < MIN_PATCH_SIDE or r["h"] < MIN_PATCH_SIDE:
            issues.append(Issue("error", "PATCH_TOO_SMALL", f"Sky region {i + 1} is smaller than {MIN_PATCH_SIDE}×{MIN_PATCH_SIDE} pixels.", i))
            continue
        if r["x"] < 0 or r["y"] < 0 or r["x"] + r["w"] > w or r["y"] + r["h"] > h:
            issues.append(Issue("error", "PATCH_OUT_OF_BOUNDS", f"Sky region {i + 1} extends outside the image.", i))
            continue
        rects.append(r)
    if issues:
        return model
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if _overlap(rects[i], rects[j]):
                issues.append(Issue("error", "PATCHES_OVERLAP", f"Sky regions {i + 1} and {j + 1} overlap.", j))
    if protected is not None:
        for i, r in enumerate(rects):
            if protected[r["y"] : r["y"] + r["h"], r["x"] : r["x"] + r["w"]].any():
                issues.append(Issue("error", "PATCH_IN_PROTECTED", f"Sky region {i + 1} overlaps a protected label region.", i))
    if issues:
        return model

    ests, infos = [], []
    for i, r in enumerate(rects):
        est, n_used, star_frac, info = patch_estimate(work, weight, star_hard, r)
        if est is None or n_used < MIN_VALID_PIXELS or not np.all(np.isfinite(est)):
            issues.append(Issue("error", "PATCH_NO_VALID_PIXELS", f"Sky region {i + 1} has too few valid, star-free pixels.", i))
            ests.append(None)
            infos.append({})
            continue
        if info["valid_fraction"] < MIN_VALID_FRACTION:
            issues.append(Issue("error", "PATCH_MOSTLY_INVALID", f"Sky region {i + 1} is mostly invalid, protected or star-covered.", i))
        if star_frac > MAX_STAR_FRACTION_ERROR:
            issues.append(Issue("error", "PATCH_STAR_CONTAMINATED", f"Sky region {i + 1} is dominated by stars.", i))
        elif star_frac > MAX_STAR_FRACTION_WARN:
            issues.append(Issue("warning", "PATCH_STARS", f"Sky region {i + 1} contains stars (excluded from its statistics).", i))
        ests.append(est)
        infos.append(info | {"n_used": n_used, "star_fraction": star_frac})
    if not model.ok:
        return model

    E = np.vstack(ests)  # patches x channels
    sig_med = max(sigma_pixel, 1e-12) * 1.2533 / np.sqrt(np.array([max(i["n_used"], 1) for i in infos], dtype=np.float64))
    offsets = np.median(E, axis=0)
    model.offsets = [float(v) for v in offsets]
    model.reference_level = float(np.mean(offsets))
    centers_x = np.array([r["x"] + r["w"] / 2 for r in rects])
    centers_y = np.array([r["y"] + r["h"] / 2 for r in rects])

    # Brighter-than-the-darkest-sky and internal-structure hints (extended signal cannot be proven absent).
    L_all = luminance(np, work)
    sky_ref = percentile(L_all[weight], 20.0) if weight.any() else 0.0
    _, sigma_frame = median_mad_sigma(L_all[weight]) if weight.any() else (0.0, 0.0)
    for i, (est, info) in enumerate(zip(E, infos)):
        lum_est = float(np.mean(est)) if c == 1 else float(est @ np.array([0.2126, 0.7152, 0.0722]))
        if lum_est > sky_ref + 5.0 * max(sigma_frame, 1e-12):
            issues.append(Issue("warning", "PATCH_BRIGHT", f"Sky region {i + 1} is brighter than the darker parts of the frame; check that it is empty sky.", i))
        if info.get("p95_excess", 0.0) > 4.0 * max(sigma_pixel, 1e-12):
            issues.append(Issue("warning", "PATCH_STRUCTURE", f"Sky region {i + 1} contains bright structure or stars.", i))
        slope = max(abs(info.get("internal_slope_x", 0.0)), abs(info.get("internal_slope_y", 0.0)))
        if slope > 5.0 * float(sig_med[i]) * 2:
            issues.append(Issue("warning", "PATCH_GRADIENT", f"Sky region {i + 1} shows a strong internal gradient (possible extended signal).", i))

    spread = E - offsets
    res: dict[str, Any] = {
        "patch_noise_sigma": float(np.mean(sig_med)),
        "channel_spread_rms": float(np.sqrt(np.mean(spread**2))),
    }
    if method == "constant":
        if np.max(np.abs(spread)) > 6.0 * float(np.max(sig_med)):
            issues.append(Issue("warning", "PATCHES_INCONSISTENT", "Sky regions differ by more than noise explains. The sky may vary across the frame; consider Uneven sky (gradient) or skip.", None))
        model.residuals = res
        model.samples = [{**r, "estimate": [float(v) for v in e]} for r, e in zip(rects, E)]
        return model

    # ---- planar model -------------------------------------------------------------------------------
    xn, yn = _norm_coords(w, h, centers_x, centers_y)
    span_x, span_y = float(xn.max() - xn.min()) / 2.0, float(yn.max() - yn.min()) / 2.0
    if span_x < MIN_SPAN or span_y < MIN_SPAN:
        issues.append(Issue("error", "POOR_COVERAGE", f"Sky regions must be spread across the frame (they cover {span_x:.0%} × {span_y:.0%}; need at least {MIN_SPAN:.0%} on both axes).", None))
    try:
        area = float(ConvexHull(np.column_stack([xn, yn])).volume) / 4.0
    except Exception:
        area = 0.0
    if area < MIN_HULL_AREA:
        issues.append(Issue("error", "COLLINEAR_OR_CLUSTERED", "Sky regions are collinear or too clustered to define a plane.", None))
    A = np.column_stack([np.ones_like(xn), xn, yn])
    cond = float(np.linalg.cond(A))
    res["condition_number"] = cond
    if cond > MAX_CONDITION_ERROR:
        issues.append(Issue("error", "ILL_CONDITIONED", f"The sky-region layout is ill-conditioned (condition number {cond:.0f}).", None))
    elif cond > MAX_CONDITION_WARN:
        issues.append(Issue("warning", "WEAK_CONDITIONING", f"The sky-region layout is only weakly conditioned (condition number {cond:.0f}).", None))
    if not model.ok:
        model.residuals = res
        return model

    # Shared spatial trend (per-patch mean over channels of the offset-removed estimates); channel
    # offsets are handled by the constant term, so nothing is subtracted twice.
    trend = spread.mean(axis=1)
    floor = float(np.mean(sig_med))
    coef, resid, weights, _ = _huber_plane(xn, yn, trend, floor)
    rms = float(np.sqrt(np.mean(resid**2)))
    robust_s = max(MAD_TO_SIGMA * float(np.median(np.abs(resid - np.median(resid)))), floor)
    outliers = [int(i) for i in np.nonzero(np.abs(resid) > 4.0 * robust_s)[0]]
    for i in outliers:
        issues.append(Issue("warning", "PATCH_OUTLIER", f"Sky region {i + 1} disagrees with the fitted plane (residual {resid[i]:.3g}); consider excluding it.", i))
    corners = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]], dtype=np.float64)
    amplitude = float(np.ptp(coef[1] * corners[:, 0] + coef[2] * corners[:, 1]))
    res.update(rms=rms, max_abs=float(np.max(np.abs(resid))), outlier_samples=outliers, amplitude=amplitude, per_sample=[float(v) for v in resid])
    if amplitude < 3.0 * floor:
        issues.append(Issue("warning", "GRADIENT_NOT_SIGNIFICANT", "The fitted gradient is within noise; uneven-sky correction is probably unnecessary.", None))
    if rms > 3.0 * floor:
        issues.append(Issue("warning", "POOR_FIT", "The sky regions do not agree with a flat plane (possible extended signal or a more complex gradient). Skip, or choose emptier regions.", None))
    xr, yr = _norm_coords(w, h, centers_x.mean(), centers_y.mean())
    model.plane = {"a": float(coef[0]), "b": float(coef[1]), "c": float(coef[2]), "ref_x": float(xr), "ref_y": float(yr)}
    model.residuals = res
    model.samples = [{**r, "estimate": [float(v) for v in e], "residual": float(rv)} for r, e, rv in zip(rects, E, resid)]
    return model


def plane_map(model: BgModel, height: int, width: int) -> np.ndarray | None:
    """Plane relative to the reference position (so mean sky level is preserved): g(x,y) - g(ref)."""
    if model.plane is None:
        return None
    p = model.plane
    xn = (2.0 * (np.arange(width, dtype=np.float64) + 0.5) / width - 1.0 - p["ref_x"]) * p["b"]
    yn = (2.0 * (np.arange(height, dtype=np.float64) + 0.5) / height - 1.0 - p["ref_y"]) * p["c"]
    return (yn[:, None] + xn[None, :]).astype(np.float32)


def channel_offset_vector(model: BgModel, strength: float) -> np.ndarray:
    off = np.asarray(model.offsets, dtype=np.float64)
    return (strength * (off - model.reference_level)).astype(np.float32)


def suggest_patches(work: np.ndarray, weight: np.ndarray, star_hard: np.ndarray | None, count: int = 8) -> list[dict[str, int]]:
    """Heuristic candidates only; the user must confirm them. Dark corners alone are not evidence of sky."""
    h, w = weight.shape
    L = luminance(np, work)
    side = int(np.clip(min(h, w) // 12, 24, 128))
    cells = []
    for y in range(0, h - side + 1, side):
        for x in range(0, w - side + 1, side):
            sl = (slice(y, y + side), slice(x, x + side))
            if weight[sl].mean() < 0.95:
                continue
            if star_hard is not None and star_hard[sl].any():
                continue
            v = L[sl]
            cells.append((float(np.median(v)), float(np.std(v)), x, y))
    if len(cells) < count:
        return []
    med = np.array([c[0] for c in cells])
    sd = np.array([c[1] for c in cells])
    ok = (med <= np.quantile(med, 0.3)) & (sd <= 1.5 * np.median(sd))
    pool = [c for c, keep in zip(cells, ok) if keep] or cells
    pool.sort()
    chosen = [pool[0]]
    while len(chosen) < min(count, len(pool)):
        best = max(
            (c for c in pool if c not in chosen),
            key=lambda c: min((c[2] - k[2]) ** 2 + (c[3] - k[3]) ** 2 for k in chosen),
        )
        chosen.append(best)
    return [{"x": c[2], "y": c[3], "w": side, "h": side} for c in chosen]
