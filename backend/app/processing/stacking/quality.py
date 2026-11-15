"""Star measurement and frame grading for stacking (CPU, deterministic).

Stars are measured on a luminance proxy: the 2 x 2 super-pixel average of a raw CFA frame (half resolution, no
interpolation), the frame itself for mono, or the channel mean for stacked RGB (binned 2 x 2 above ~3 MP).
Each frame gets: star count, median FWHM and elongation (second moments), background and noise. Grading rejects
frames whose metrics are far from the session's typical values (clouds, trailing, bloated stars, bright sky).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage

from ..diagnostics import MAD_TO_SIGMA

DETECT_SIGMAS = 5.0
MAX_STARS = 200
MIN_AREA = 3
MAX_AREA = 400
BG_BOX = 32

GRADING = {
    # (min star-count ratio, max FWHM sigmas, max elongation, max background sigmas)
    "off": None,
    "lenient": (0.25, 6.0, 2.2, 8.0),
    "standard": (0.4, 4.0, 1.8, 5.0),
    "strict": (0.6, 3.0, 1.5, 3.5),
}


@dataclass
class StarList:
    x: np.ndarray  # full-resolution coordinates (pixel centres at integer + 0.0)
    y: np.ndarray
    flux: np.ndarray

    def top(self, n: int) -> "StarList":
        o = np.argsort(-self.flux)[:n]
        return StarList(self.x[o], self.y[o], self.flux[o])

    def to_lists(self) -> dict[str, list[float]]:
        return {"x": self.x.tolist(), "y": self.y.tolist(), "flux": self.flux.tolist()}

    @staticmethod
    def from_lists(d: dict[str, list[float]]) -> "StarList":
        return StarList(np.asarray(d["x"], float), np.asarray(d["y"], float), np.asarray(d["flux"], float))


@dataclass
class FrameStats:
    stars: int
    fwhm: float | None
    elongation: float | None
    background: float
    noise: float
    channel_background: list[float] = field(default_factory=list)
    star_flux: float | None = None  # median flux of the 20 brightest stars: transparency (thin cloud dims every star)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def luminance_proxy(img: np.ndarray, layout: str) -> tuple[np.ndarray, int]:
    """(proxy image, binning factor). Coordinates in the proxy map to full resolution as (p + 0.5) * f - 0.5."""
    if layout == "cfa":
        h, w = img.shape
        h2, w2 = h - h % 2, w - w % 2
        a = img[:h2, :w2]
        return 0.25 * (a[0::2, 0::2] + a[0::2, 1::2] + a[1::2, 0::2] + a[1::2, 1::2]), 2
    if img.ndim == 3:
        L = img.mean(axis=2)
        if L.size > 3_000_000:
            h2, w2 = L.shape[0] - L.shape[0] % 2, L.shape[1] - L.shape[1] % 2
            a = L[:h2, :w2]
            return 0.25 * (a[0::2, 0::2] + a[0::2, 1::2] + a[1::2, 0::2] + a[1::2, 1::2]), 2
        return L, 1
    return img, 1


def channel_backgrounds(img: np.ndarray, layout: str, pattern: str | None) -> list[float]:
    def med(a):
        v = a[:: max(1, a.shape[0] // 256), :: max(1, a.shape[1] // 256)].ravel()
        m = float(np.median(v))
        s = float(np.median(np.abs(v - m)) * MAD_TO_SIGMA) or 1.0
        keep = v[np.abs(v - m) < 3 * s]
        return float(np.median(keep)) if keep.size else m
    if layout == "cfa" and pattern:
        vals: dict[str, list[float]] = {"R": [], "G": [], "B": []}
        for i, ch in enumerate(pattern):
            dy, dx = divmod(i, 2)
            vals[ch].append(med(img[dy::2, dx::2]))
        return [float(np.mean(vals[c])) for c in "RGB"]
    if img.ndim == 3:
        return [med(img[..., c]) for c in range(3)]
    return [med(img)]


def measure(img: np.ndarray, layout: str, pattern: str | None = None) -> tuple[FrameStats, StarList]:
    L, f = luminance_proxy(img, layout)
    L = L.astype(np.float32)
    small = L[::4, ::4]
    m0 = float(np.median(small))
    s0 = float(np.median(np.abs(small - m0)) * MAD_TO_SIGMA) or 1.0
    bg = ndimage.median_filter(np.minimum(L, m0 + 3 * s0)[::4, ::4], size=max(3, BG_BOX // 4), mode="nearest")
    bg = ndimage.zoom(bg, (L.shape[0] / bg.shape[0], L.shape[1] / bg.shape[1]), order=1)[: L.shape[0], : L.shape[1]]
    if bg.shape != L.shape:
        bg = np.pad(bg, ((0, L.shape[0] - bg.shape[0]), (0, L.shape[1] - bg.shape[1])), mode="edge")
    resid = L - bg
    noise = float(np.median(np.abs(resid[::2, ::2] - np.median(resid[::2, ::2]))) * MAD_TO_SIGMA) or 1e-6
    det = ndimage.gaussian_filter(resid, 1.0) > DETECT_SIGMAS * noise / 2.0
    labels, n = ndimage.label(det)
    xs, ys, fl, fw, el = [], [], [], [], []
    if n:
        idx = np.arange(1, n + 1)
        area = ndimage.sum(det, labels, idx)
        flux = ndimage.sum(resid, labels, idx)
        peak = ndimage.maximum(resid, labels, idx)
        ok = (area >= MIN_AREA) & (area <= MAX_AREA) & (peak > DETECT_SIGMAS * noise)
        sel = idx[ok]
        if sel.size:
            w = np.where(labels > 0, np.maximum(resid, 0), 0)
            yy, xx = np.indices(L.shape, dtype=np.float32)
            s = ndimage.sum(w, labels, sel)
            cy = ndimage.sum(w * yy, labels, sel) / s
            cx = ndimage.sum(w * xx, labels, sel) / s
            vyy = ndimage.sum(w * yy * yy, labels, sel) / s - cy**2
            vxx = ndimage.sum(w * xx * xx, labels, sel) / s - cx**2
            vxy = ndimage.sum(w * xx * yy, labels, sel) / s - cx * cy
            tr, det2 = vxx + vyy, vxx * vyy - vxy**2
            disc = np.sqrt(np.maximum(tr**2 / 4 - det2, 0))
            l1, l2 = tr / 2 + disc, np.maximum(tr / 2 - disc, 1e-6)
            good = (s > 0) & (l1 > 0)
            xs, ys, fl = ((cx + 0.5) * f - 0.5)[good], ((cy + 0.5) * f - 0.5)[good], flux[ok][good]
            sig = np.sqrt(np.maximum((l1 + l2) / 2, 1e-6))[good] * f
            fw, el = 2.3548 * sig, np.sqrt(l1 / l2)[good]
    stars = StarList(np.asarray(xs, float), np.asarray(ys, float), np.asarray(fl, float)).top(MAX_STARS)
    bright = np.argsort(-np.asarray(fl))[:50] if len(fl) else []
    stats = FrameStats(
        stars=int(len(xs)),
        fwhm=float(np.median(np.asarray(fw)[bright])) if len(fw) else None,
        elongation=float(np.median(np.asarray(el)[bright])) if len(el) else None,
        background=float(np.median(bg)), noise=noise,
        channel_background=channel_backgrounds(img, layout, pattern),
        star_flux=float(np.median(np.sort(np.asarray(fl))[-20:])) if len(fl) else None,
    )
    return stats, stars


def grade(stats: list[FrameStats | None], mood: str) -> list[str | None]:
    """Reason for rejecting each frame (None = keep)."""
    out: list[str | None] = [None if s else "could not be measured" for s in stats]
    limits = GRADING.get(mood)
    good = [s for s in stats if s]
    if limits is None or len(good) < 5:
        return [r if r else None for r in out]
    min_ratio, fwhm_sig, max_elong, bg_sig = limits

    def robust(v):
        v = np.asarray([x for x in v if x is not None], float)
        if v.size == 0:
            return 0.0, 0.0
        m = float(np.median(v))
        return m, float(np.median(np.abs(v - m)) * MAD_TO_SIGMA)

    med_stars = float(np.median([s.stars for s in good]))
    fluxes = [s.star_flux for s in good if s.star_flux]
    med_flux = float(np.median(fluxes)) if fluxes else 0.0
    fw_m, fw_s = robust(s.fwhm for s in good)
    bg_m, bg_s = robust(s.background for s in good)
    for i, s in enumerate(stats):
        if s is None:
            continue
        if s.stars < max(8, min_ratio * med_stars):
            out[i] = f"only {s.stars} stars (session median {med_stars:.0f}): clouds or haze"
        elif med_flux > 0 and s.star_flux is not None and s.star_flux < min_ratio * med_flux:
            out[i] = f"stars {100 * s.star_flux / med_flux:.0f}% as bright as usual: clouds or haze"
        elif s.fwhm is not None and fw_s > 0 and s.fwhm > fw_m + fwhm_sig * max(fw_s, 0.05 * fw_m):
            out[i] = f"stars bloated (FWHM {s.fwhm:.2f} px vs {fw_m:.2f})"
        elif s.elongation is not None and s.elongation > max_elong:
            out[i] = f"stars trailed (elongation {s.elongation:.2f})"
        elif bg_s > 0 and s.background > bg_m + bg_sig * max(bg_s, 0.01 * abs(bg_m)):
            out[i] = "sky much brighter than the rest (dawn, moon or cloud glow)"
    return out
