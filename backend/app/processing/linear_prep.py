"""Linear-phase analysis for stacked data (CPU, global, deterministic): low-coverage edges, per-channel sky,
an automatic low-order gradient model, background neutralization and a bounded white balance from field stars.

Everything here *measures* the image and returns small models; the pixel group applies them. Each stage
reports why it was skipped when the measurement is not credible. Nothing is generated: the operations are
per-channel offsets, a smooth polynomial subtraction and per-channel gains, all recorded and reversible.
White balance from field stars is a statistical display balance, not photometric color calibration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage

from .diagnostics import MAD_TO_SIGMA, strided
from .parallel import thread_map

PEDESTAL_SIGMAS = 3.0
EDGE_SIGMAS = 6.0
GRID_BOXES = 16  # along the long axis
GRADIENT_TOLERANCE = 1.5  # boxes brighter than median + tol * spread are not sky
GRADIENT_MIN_RELATIVE = 0.25  # model amplitude below 0.25 x pixel noise is negligible
WB_MIN_STARS = 15
WB_MAX_DISPERSION = 0.5  # robust sigma of log color ratios above this: star colors too inconsistent
WB_DEFAULT_LIMIT = 1.25
WB_MAX_STARS = 3000
SATURATION_LEVEL = 0.999  # of the shared normalization scale (the data maximum)


def clipped_stats(values: np.ndarray, iters: int = 6, kappa: float = 3.0) -> tuple[float, float]:
    """Iterative kappa-sigma clipped median and robust sigma (MAD)."""
    v = strided(values).astype(np.float64, copy=False)
    if v.size == 0:
        return 0.0, 0.0
    m = float(np.median(v))
    s = float(np.median(np.abs(v - m)) * MAD_TO_SIGMA)
    for _ in range(iters):
        if s <= 0:
            break
        keep = v[np.abs(v - m) < kappa * s]
        if keep.size < 16:
            break
        m2 = float(np.median(keep))
        s2 = float(np.median(np.abs(keep - m2)) * MAD_TO_SIGMA)
        if abs(m2 - m) < 1e-12 and abs(s2 - s) < 1e-12:
            break
        m, s, v = m2, s2, keep
    return m, s


def channels(u: np.ndarray) -> list[np.ndarray]:
    return [u] if u.ndim == 2 else [u[..., c] for c in range(u.shape[2])]


# ------------------------------------------------------------------------------------------------ edges
def edge_mask(u: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Low-coverage borders (field rotation, mosaics): constant fill and darker-than-sky bands connected to
    the frame edge. Excluded from every statistic; still processed (never cropped)."""
    L = u if u.ndim == 2 else u.mean(axis=2)
    h, w = L.shape
    sky, sig = clipped_stats(L[valid])
    if sig <= 0:
        return np.zeros((h, w), bool), {"fraction": 0.0, "method": "none (flat data)"}
    sm = ndimage.uniform_filter(np.where(valid, L, sky), size=9, mode="nearest")
    # the 9x9 mean of pure noise has sigma ~ sig/9; a band EDGE_SIGMAS below sky (in that unit) is low coverage
    low = sm < sky - EDGE_SIGMAS * sig / 9.0 - 2.0 * sig
    flat = ndimage.uniform_filter((np.abs(L - ndimage.uniform_filter(L, 3, mode="nearest")) < 1e-9).astype(np.float32), 9) > 0.9
    cand = (low | flat | ~valid)
    labels, n = ndimage.label(cand)
    if n == 0:
        return np.zeros((h, w), bool), {"fraction": 0.0, "method": "connected-to-border low/constant regions"}
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    border = border[border > 0]
    mask = np.isin(labels, border) & valid
    frac = float(mask.mean())
    if frac > 0.5:  # implausible: probably a dark target or a bad estimate; do not exclude half the frame
        return np.zeros((h, w), bool), {"fraction": 0.0, "method": "rejected (would exclude over half the frame)"}
    return mask, {"fraction": frac, "method": "connected-to-border low/constant regions"}


# ------------------------------------------------------------------------------------------------ sky
@dataclass
class SkyStats:
    level: tuple[float, ...]
    sigma: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"level": list(self.level), "sigma": list(self.sigma), "method": "kappa-sigma clipped median of the dimmer 75% (luminance) of valid, non-edge pixels"}


SKY_DIM_PERCENTILE = 75.0


def sky_stats(u: np.ndarray, stat_weight: np.ndarray, threads: int = 1) -> SkyStats:
    """Per-channel sky level and noise from the dimmer part of the frame, so a bright target filling much of
    the field does not pull the 'sky' toward its own color. Channels may be measured on ``threads`` threads."""
    L = u if u.ndim == 2 else u.mean(axis=2)
    lw = L[stat_weight]
    use = stat_weight
    if lw.size:
        cut = float(np.percentile(strided(lw), SKY_DIM_PERCENTILE))
        use = stat_weight & (L <= cut)
    stats = thread_map(lambda ch: clipped_stats(ch[use]), channels(u), threads)
    return SkyStats(tuple(m for m, _ in stats), tuple(s for _, s in stats))


# ------------------------------------------------------------------------------------------------ gradient
def _poly_terms(xn: np.ndarray, yn: np.ndarray, degree: int) -> np.ndarray:
    cols = []
    for d in range(degree + 1):
        for i in range(d + 1):
            cols.append((xn ** (d - i)) * (yn ** i))
    return np.stack(cols, axis=-1)


@dataclass
class GradientModel:
    ok: bool
    degree: int
    coeffs: list[list[float]] = field(default_factory=list)  # per channel
    offsets: list[float] = field(default_factory=list)  # per-channel model median (subtracted model is zero-median)
    boxes_used: int = 0
    boxes_total: int = 0
    amplitude: list[float] = field(default_factory=list)
    relative_amplitude: float = 0.0
    reason: str | None = None
    kind: str = "polynomial"  # polynomial | spline
    spline_points: list[list[float]] = field(default_factory=list)  # kept sky boxes (normalized x, y)
    spline_values: list[list[float]] = field(default_factory=list)  # per channel, at the kept boxes
    spline_smoothing: float = 0.0
    choice: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        method = (f"robust polynomial (degree {self.degree}) fitted to sigma-clipped sky boxes; zero-median model subtracted"
                  if self.kind == "polynomial" else
                  "smoothed thin-plate spline through sigma-clipped sky boxes (GraXpert-style classical model); zero-median model subtracted")
        return {
            "method": method, "kind": self.kind, "choice": self.choice,
            "ok": self.ok, "degree": self.degree, "boxes_used": self.boxes_used, "boxes_total": self.boxes_total,
            "amplitude_per_channel": self.amplitude, "amplitude_relative_to_pixel_noise": self.relative_amplitude,
            "coefficients": self.coeffs if self.kind == "polynomial" else None,
            "spline_smoothing": self.spline_smoothing if self.kind == "spline" else None, "reason": self.reason,
        }


SPLINE_TRIGGER = 4.0  # polynomial residual at the sky boxes, in units of the scatter expected from noise alone
SPLINE_MIN_BOXES = 40
SPLINE_MIN_SKY_FRACTION = 0.8  # automatic only when most of the frame is empty sky (a spline would follow faint nebulosity)
SPLINE_GRID = 128


def _spline_grid(points: np.ndarray, values: np.ndarray, smoothing: float, n: int = SPLINE_GRID) -> np.ndarray:
    from scipy.interpolate import RBFInterpolator

    rbf = RBFInterpolator(points, values, kernel="thin_plate_spline", smoothing=smoothing)
    g = np.linspace(-1.0, 1.0, n)
    gx, gy = np.meshgrid(g, g)
    return rbf(np.column_stack([gx.ravel(), gy.ravel()])).reshape(n, n)


def fit_gradient(u: np.ndarray, stat_weight: np.ndarray, star_hard: np.ndarray | None, degree: int, sigma_pix: float,
                 kind: str | None = None) -> GradientModel:
    h, w = stat_weight.shape
    s = max(16, int(np.ceil(max(h, w) / GRID_BOXES)))
    use = stat_weight.copy()
    if star_hard is not None:
        use &= ~ndimage.binary_dilation(star_hard, iterations=3)
    chans = channels(u)
    L = u if u.ndim == 2 else u.mean(axis=2)
    xs, ys, vals, lbox, sbox = [], [], [], [], []
    total = 0
    for y0 in range(0, h - s // 2, s):
        for x0 in range(0, w - s // 2, s):
            total += 1
            sl = (slice(y0, min(h, y0 + s)), slice(x0, min(w, x0 + s)))
            m = use[sl]
            if m.mean() < 0.5:
                continue
            lv = L[sl][m]
            med = float(np.median(lv))
            sbox.append(float(np.median(np.abs(lv - med)) * MAD_TO_SIGMA))
            lbox.append(med)
            vals.append([float(np.median(c[sl][m])) for c in chans])
            xs.append((x0 + min(w, x0 + s)) / 2.0)
            ys.append((y0 + min(h, y0 + s)) / 2.0)
    n_terms = (degree + 1) * (degree + 2) // 2
    model = GradientModel(False, degree, boxes_total=total)
    if len(vals) < max(12, 3 * n_terms):
        model.reason = "Not enough empty sky to model a gradient (the target fills most of the frame)."
        return model
    lbox_a, sbox_a = np.array(lbox), np.array(sbox)
    vals_a = np.array(vals)
    xn = 2.0 * np.array(xs) / w - 1.0
    yn = 2.0 * np.array(ys) / h - 1.0
    med_l = float(np.median(lbox_a))
    spread = float(np.median(np.abs(lbox_a - med_l)) * MAD_TO_SIGMA)
    med_s = float(np.median(sbox_a))
    keep = (lbox_a <= med_l + GRADIENT_TOLERANCE * max(spread, sigma_pix * 0.05)) & (sbox_a <= 1.5 * med_s)
    A_all = _poly_terms(xn, yn, degree)
    for _ in range(4):
        if keep.sum() < max(12, 3 * n_terms):
            break
        coef_l, *_ = np.linalg.lstsq(A_all[keep], lbox_a[keep], rcond=None)
        resid = lbox_a - A_all @ coef_l
        rs = float(np.median(np.abs(resid[keep])) * MAD_TO_SIGMA) or 1e-12
        new_keep = keep & (resid < 2.5 * rs)
        if new_keep.sum() == keep.sum():
            break
        keep = new_keep
    if keep.sum() < max(12, 3 * n_terms):
        model.reason = "Too few sky samples remained after excluding the target and stars; gradient removal skipped."
        return model
    span_x = float(xn[keep].max() - xn[keep].min()) / 2.0
    span_y = float(yn[keep].max() - yn[keep].min()) / 2.0
    if span_x < 0.5 or span_y < 0.5:
        model.reason = "Sky samples do not cover the frame widely enough to model a gradient reliably."
        return model
    gy, gx = np.mgrid[-1:1:64j, -1:1:64j]
    G = _poly_terms(gx.ravel(), gy.ravel(), degree)
    coeffs, offsets, amps = [], [], []
    for c in range(vals_a.shape[1]):
        coef, *_ = np.linalg.lstsq(A_all[keep], vals_a[keep, c], rcond=None)
        grid = G @ coef
        coeffs.append([float(v) for v in coef])
        offsets.append(float(np.median(grid)))
        amps.append(float(grid.max() - grid.min()))
    model.coeffs, model.offsets, model.amplitude = coeffs, offsets, amps
    model.boxes_used = int(keep.sum())
    # Polynomial or spline: the spline is chosen when the polynomial leaves a residual the noise cannot explain.
    coef_l, *_ = np.linalg.lstsq(A_all[keep], lbox_a[keep], rcond=None)
    resid_poly = float(np.median(np.abs(lbox_a[keep] - A_all[keep] @ coef_l)) * MAD_TO_SIGMA)
    px_per_box = max(1.0, float(s * s) * 0.5)
    expected = 1.2533 * med_s / np.sqrt(px_per_box)
    ratio = resid_poly / max(expected, 1e-12)
    sky_fraction = float(keep.sum()) / max(total, 1)
    auto_spline = bool(ratio > SPLINE_TRIGGER and keep.sum() >= SPLINE_MIN_BOXES and sky_fraction >= SPLINE_MIN_SKY_FRACTION)
    use_spline = kind == "spline" or (kind is None and auto_spline)
    model.choice = {"requested": kind or "automatic", "polynomial_residual_vs_noise": ratio, "trigger": SPLINE_TRIGGER,
                    "min_boxes": SPLINE_MIN_BOXES, "sky_fraction": sky_fraction, "min_sky_fraction": SPLINE_MIN_SKY_FRACTION}
    if use_spline and keep.sum() >= 12:
        pts = np.column_stack([xn[keep], yn[keep]])
        sm = float(keep.sum()) * 0.01  # values are scaled to the expected box scatter, so this smooths toward noise level
        scale = max(expected, 1e-12)
        grids = [_spline_grid(pts, vals_a[keep, c] / scale, sm) * scale for c in range(vals_a.shape[1])]
        model.kind, model.spline_points, model.spline_smoothing = "spline", pts.tolist(), sm
        model.spline_values = [[float(v) / scale for v in vals_a[keep, c]] for c in range(vals_a.shape[1])]
        model.choice["spline_scale"] = scale
        model.offsets = [float(np.median(g)) for g in grids]
        model.amplitude = amps = [float(g.max() - g.min()) for g in grids]
    model.relative_amplitude = float(max(amps) / max(sigma_pix, 1e-12))
    if model.relative_amplitude < GRADIENT_MIN_RELATIVE:
        model.reason = f"No significant gradient (model amplitude {model.relative_amplitude:.2f} x pixel noise)."
        return model
    model.ok = True
    return model


def gradient_map(model: GradientModel, h: int, w: int, dtype=np.float32) -> np.ndarray:
    """Zero-median model per channel at full resolution (H x W or H x W x C)."""
    if model.kind == "spline":
        from .ai.tiles import resize_linear

        pts = np.asarray(model.spline_points)
        scale = float(model.choice.get("spline_scale", 1.0))
        grids = [_spline_grid(pts, np.asarray(v), model.spline_smoothing) * scale for v in model.spline_values]
        full = resize_linear(np.stack(grids, -1).astype(np.float32), h, w)
        out = [(full[..., c] - off).astype(dtype) for c, off in enumerate(model.offsets)]
        return out[0] if len(out) == 1 else np.stack(out, axis=-1)
    yy = np.linspace(-1.0 + 1.0 / h, 1.0 - 1.0 / h, h, dtype=np.float64)
    xx = np.linspace(-1.0 + 1.0 / w, 1.0 - 1.0 / w, w, dtype=np.float64)
    out = []
    for coef, off in zip(model.coeffs, model.offsets):
        acc = np.zeros((h, w), np.float64)
        k = 0
        for d in range(model.degree + 1):
            for i in range(d + 1):
                acc += coef[k] * np.outer(yy ** i, xx ** (d - i))
                k += 1
        out.append((acc - off).astype(dtype))
    return out[0] if len(out) == 1 else np.stack(out, axis=-1)


# ------------------------------------------------------------------------------------------------ white balance
@dataclass
class WhiteBalance:
    ok: bool
    factors: tuple[float, float, float] = (1.0, 1.0, 1.0)
    raw_factors: tuple[float, float, float] | None = None
    stars_used: int = 0
    dispersion: float | None = None
    limit: float = WB_DEFAULT_LIMIT
    clamped: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "median color ratio of unsaturated, isolated field stars (average star treated as white); bounded gains",
            "ok": self.ok, "factors_rgb": list(self.factors), "raw_factors_rgb": list(self.raw_factors) if self.raw_factors else None,
            "stars_used": self.stars_used, "log_ratio_dispersion": self.dispersion, "limit": self.limit, "clamped": self.clamped,
            "reason": self.reason,
            "note": "Statistical display white balance, not photometric color calibration (no catalog or plate solve).",
        }


def measure_star_fluxes(u_corr: np.ndarray, star_hard: np.ndarray, saturated: np.ndarray, sigma_l: float,
                         valid: np.ndarray | None = None):
    """Positions and aperture fluxes of isolated, unsaturated stars after sky subtraction."""
    labels, n = ndimage.label(star_hard)
    objs = ndimage.find_objects(labels)
    h, w = star_hard.shape
    L = u_corr.mean(axis=2)
    peaks = ndimage.maximum(L, labels, index=np.arange(1, n + 1)) if n else np.array([])
    order = np.argsort(-np.asarray(peaks))[:WB_MAX_STARS] if n else []
    for idx in order:
        sl = objs[idx]
        if sl is None:
            continue
        lab = idx + 1
        y0, y1 = max(0, sl[0].start - 8), min(h, sl[0].stop + 8)
        x0, x1 = max(0, sl[1].start - 8), min(w, sl[1].stop + 8)
        comp = labels[y0:y1, x0:x1] == lab
        ap = ndimage.binary_dilation(comp, iterations=2)
        if saturated[y0:y1, x0:x1][ap].any():
            continue
        inner = ndimage.binary_dilation(comp, iterations=4)
        outer = ndimage.binary_dilation(comp, iterations=7)
        ann = outer & ~inner & (labels[y0:y1, x0:x1] == 0)
        if valid is not None:
            local = valid[y0:y1, x0:x1]
            if not local[ap].all():
                continue
            ann &= local
        if ann.sum() < 12:
            continue
        sub = u_corr[y0:y1, x0:x1]
        bg = np.median(sub[ann], axis=0)
        if float(bg.mean()) > 3.0 * sigma_l:  # embedded in nebulosity/galaxy light: color is contaminated
            continue
        npx = int(ap.sum())
        flux = sub[ap].sum(axis=0) - bg * npx
        if (flux <= 0).any() or float(flux.mean()) < 10.0 * sigma_l * np.sqrt(npx):
            continue
        yy, xx = np.nonzero(comp)
        yield (x0 + xx.mean(), y0 + yy.mean()), flux


def star_white_balance(
    u_corr: np.ndarray, star_hard: np.ndarray | None, saturated: np.ndarray, sigma_l: float, limit: float = WB_DEFAULT_LIMIT,
) -> WhiteBalance:
    """``u_corr``: H x W x 3 linear data with the sky removed (background ~ 0 in every channel)."""
    wb = WhiteBalance(False, limit=limit)
    if u_corr.ndim != 3:
        wb.reason = "Monochrome image."
        return wb
    if star_hard is None or not star_hard.any():
        wb.reason = "Star detection was not reliable, so there is no star color reference."
        return wb
    ratios = [(f[0] / f[1], f[2] / f[1]) for _, f in measure_star_fluxes(u_corr, star_hard, saturated, sigma_l)]
    wb.stars_used = len(ratios)
    if len(ratios) < WB_MIN_STARS:
        wb.reason = f"Only {len(ratios)} isolated, unsaturated stars were found (need {WB_MIN_STARS}); white balance skipped."
        return wb
    lr = np.log(np.array(ratios))
    med = np.median(lr, axis=0)
    disp = float((np.median(np.abs(lr - med), axis=0) * MAD_TO_SIGMA).max())
    wb.dispersion = disp
    if disp > WB_MAX_DISPERSION:
        wb.reason = f"Star colors are too inconsistent (dispersion {disp:.2f}); white balance skipped."
        return wb
    raw = (float(np.exp(-med[0])), 1.0, float(np.exp(-med[1])))
    clamped = tuple(float(np.clip(f, 1.0 / limit, limit)) for f in raw)
    wb.raw_factors = raw
    wb.factors = clamped  # type: ignore[assignment]
    wb.clamped = any(abs(a - b) > 1e-9 for a, b in zip(raw, clamped))
    wb.ok = True
    return wb
