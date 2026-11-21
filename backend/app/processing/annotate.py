"""Object annotations, compass and scale bar for the separate Edit export sharing copy (spec amendment 1.7 B).

Positions come from the image's sky solution (verified header WCS or hinted solve) and are carried through the same
rotation, crop and scaling as the edited pixels (``frame_points`` mirrors ``edit_export.reframe``). Marks are drawn on
the sharing copy only; regular exports, runs and originals are unchanged. Object identity places text only; it never
changes pixel values (fidelity rule 2).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .catalogs.objects import TYPE_LABELS, DeepSkyObject, in_cone
from .export import _font

MIN_ELLIPSE_PX = 14  # objects smaller than this on the output get a ring of this size
OBJECT_COLOR = (65535, 58000, 30000)  # soft yellow
GUIDE_COLOR = (65535, 65535, 65535)


@dataclass(frozen=True)
class Annotations:
    objects: bool = False
    hidden: tuple[str, ...] = ()  # object names the user unticked
    max_mag: float | None = None
    compass: bool = False
    scale_bar: bool = False

    @property
    def any(self) -> bool:
        return self.objects or self.compass or self.scale_bar


@dataclass
class FrameGeometry:
    """Maps display-array points (y, x) to the edited output, as ``edit_export.reframe`` does to pixels."""
    src_h: int
    src_w: int
    out_h: int
    out_w: int
    scale: float  # output pixels per display pixel
    _f: Any = field(repr=False)

    def map(self, y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self._f(np.asarray(y, np.float64), np.asarray(x, np.float64))


def frame_geometry(h: int, w: int, frame, max_edge: int | None = None) -> FrameGeometry:
    rot = frame.rotation
    if rot % 90 == 0:
        n = (-(rot // 90)) % 4  # np.rot90 counter-clockwise steps
        bh, bw = (h, w) if n % 2 == 0 else (w, h)
    else:
        n = None
        a = math.radians(rot)
        c, s = math.cos(a), math.sin(a)
        bw = math.ceil(w * abs(c) + h * abs(s))
        bh = math.ceil(h * abs(c) + w * abs(s))
    cw, ch = max(1, round(bw / frame.zoom)), max(1, round(bh / frame.zoom))
    left = round((bw - cw) * (frame.pan_x + 1) / 2)
    top = round((bh - ch) * (frame.pan_y + 1) / 2)
    scale = min(1.0, math.sqrt(w * h / (cw * ch)))
    if max_edge is not None:
        scale = min(scale, max_edge / max(cw, ch))
    ow, oh = max(1, int(cw * scale)), max(1, int(ch * scale))
    sx, sy = cw / ow, ch / oh

    def affine_inverse(yy, xx, hh, ww, c_, s_, bw_, bh_, left_, top_):
        x0 = left_ + (sx - bw_) / 2
        y0 = top_ + (sy - bh_) / 2
        oy0 = (hh - 1) / 2 + c_ * y0 - s_ * x0
        ox0 = (ww - 1) / 2 + s_ * y0 + c_ * x0
        dy, dx = yy - oy0, xx - ox0
        return (c_ * dy + s_ * dx) / sy, (-s_ * dy + c_ * dx) / sx

    if n is not None:
        def f(y, x):
            hh, ww = h, w
            for _ in range(n):  # one counter-clockwise quarter turn: (y, x) -> (W - 1 - x, y)
                y, x = ww - 1 - x, y
                hh, ww = ww, hh
            y, x = y - top, x - left
            if (ow, oh) == (cw, ch):
                return y, x
            return affine_inverse(y, x, ch, cw, 1.0, 0.0, cw, ch, 0, 0)
    else:
        def f(y, x):
            return affine_inverse(y, x, h, w, c, s, bw, bh, left, top)
    return FrameGeometry(h, w, oh, ow, ow / cw, f)


def _sky_to_display(solution: dict[str, Any], ra, dec):
    """World -> display-array (y, x) through the stored solution (WCS in the FITS file's row order)."""
    from .sky_solution import wcs_from_cards

    w = wcs_from_cards(solution["header"])
    x, y = w.all_world2pix(np.atleast_1d(ra), np.atleast_1d(dec), 0, quiet=True)
    if solution.get("flip_rows"):
        y = solution["height"] - 1 - y
    return y, x


def _display_to_sky(solution: dict[str, Any], y, x):
    from .sky_solution import wcs_from_cards

    w = wcs_from_cards(solution["header"])
    yf = (solution["height"] - 1 - np.asarray(y)) if solution.get("flip_rows") else y
    ra, dec = w.all_pix2world(np.atleast_1d(x), np.atleast_1d(yf), 0)
    return ra, dec


def objects_in_frame(solution: dict[str, Any], objects: tuple[DeepSkyObject, ...], geo: FrameGeometry,
                     max_mag: float | None = None) -> list[dict[str, Any]]:
    """Catalogued objects whose position falls inside the framed output, largest first."""
    radius = 0.75 * math.hypot(*solution["field_deg"])
    cand = in_cone(objects, solution["center_ra"], solution["center_dec"], radius)
    if not cand:
        return []
    y, x = _sky_to_display(solution, [o.ra for o in cand], [o.dec for o in cand])
    oy, ox = geo.map(y, x)
    px_per_arcmin = 60.0 / solution["scale_arcsec"] * geo.scale
    out = []
    for o, yy, xx, py, px in zip(cand, y, x, oy, ox):
        if not (np.isfinite(py) and 0 <= py < geo.out_h and 0 <= px < geo.out_w):
            continue
        if not (0 <= yy < geo.src_h and 0 <= xx < geo.src_w):
            continue
        if max_mag is not None and o.mag is not None and o.mag > max_mag:
            continue
        size_px = (o.major_arcmin or 0) * px_per_arcmin
        out.append({"name": o.name, "id": o.id, "type": TYPE_LABELS.get(o.type, o.type), "common": list(o.common[:1]),
                    "mag": o.mag, "major_arcmin": o.major_arcmin, "minor_arcmin": o.minor_arcmin, "pa_deg": o.pa_deg,
                    "x": float(px), "y": float(py), "size_px": float(size_px), "_obj": o})
    out.sort(key=lambda d: (-(d["major_arcmin"] or 0), d["mag"] if d["mag"] is not None else 99))
    return out


def _north_east(solution: dict[str, Any], geo: FrameGeometry, y: float, x: float) -> tuple[np.ndarray, np.ndarray]:
    """Unit vectors (dy, dx) in the output pointing north and east at a display point."""
    ra, dec = _display_to_sky(solution, [y], [x])
    step = solution["scale_arcsec"] * 20 / 3600
    yn, xn = _sky_to_display(solution, ra, dec + step)
    ye, xe = _sky_to_display(solution, ra + step / max(math.cos(math.radians(float(dec[0]))), 1e-3), dec)
    p0 = np.array(geo.map(np.array([y]), np.array([x]))).ravel()
    pn = np.array(geo.map(yn, xn)).ravel()
    pe = np.array(geo.map(ye, xe)).ravel()
    n, e = pn - p0, pe - p0
    return n / max(np.linalg.norm(n), 1e-9), e / max(np.linalg.norm(e), 1e-9)


def _nice_length(arcmin_max: float) -> float:
    best = 0.5
    for v in (0.5, 1, 2, 5, 10, 15, 20, 30, 60, 90, 120, 180, 300, 600):
        if v <= arcmin_max:
            best = v
    return best


def draw(image: np.ndarray, solution: dict[str, Any], objects: tuple[DeepSkyObject, ...], geo: FrameGeometry,
         ann: Annotations) -> dict[str, Any]:
    """Draw the requested marks into ``image`` (uint16, the edited output) in place; returns what was drawn."""
    h, w = image.shape[:2]
    lw = max(1, round(min(w, h) / 700))
    fsize = max(10, round(min(w, h) * 0.022))
    font = _font(fsize)
    obj_mask = Image.new("L", (w, h))
    guide_mask = Image.new("L", (w, h))
    od, gd = ImageDraw.Draw(obj_mask), ImageDraw.Draw(guide_mask)
    drawn: dict[str, Any] = {"objects": [], "compass": False, "scale_bar": None, "reserved": []}
    if ann.objects:
        placed: list[tuple[float, float, float, float]] = []
        for o in objects_in_frame(solution, objects, geo, ann.max_mag):
            if o["name"] in ann.hidden:
                continue
            obj: DeepSkyObject = o["_obj"]
            a = max(o["size_px"] / 2, MIN_ELLIPSE_PX / 2)
            b = max((obj.minor_arcmin or obj.major_arcmin or 0) * 60.0 / solution["scale_arcsec"] * geo.scale / 2, MIN_ELLIPSE_PX / 2)
            nvec, evec = _north_east(solution, geo, *_inverse_hint(o, solution))
            pa = math.radians(obj.pa_deg or 0.0)  # from north through east
            major = nvec * math.cos(pa) + evec * math.sin(pa)
            minor = np.array([-major[1], major[0]])
            t = np.linspace(0, 2 * math.pi, 73)
            pts = [(o["x"] + a * math.cos(tt) * major[1] + b * math.sin(tt) * minor[1],
                    o["y"] + a * math.cos(tt) * major[0] + b * math.sin(tt) * minor[0]) for tt in t]
            od.line(pts, fill=255, width=lw)
            label = o["name"] + (f" · {o['common'][0]}" if o["common"] else "")
            tx, ty = o["x"] + max(a, b) * 0.75 + 4, o["y"] - max(a, b) * 0.75 - fsize
            bx = od.textbbox((tx, ty), label, font=font)
            if bx[2] > w - 2:
                tx -= bx[2] - (w - 2)
            ty = min(max(ty, 2), h - fsize - 4)
            bx = od.textbbox((tx, ty), label, font=font)
            if any(not (bx[2] < p[0] or bx[0] > p[2] or bx[3] < p[1] or bx[1] > p[3]) for p in placed):
                ty = bx[3] + 2 if bx[3] + fsize < h else ty - fsize - 4
                bx = od.textbbox((tx, ty), label, font=font)
            placed.append(bx)
            od.text((tx, ty), label, font=font, fill=255)
            drawn["objects"].append(o["name"])
    margin = max(8, round(min(w, h) * 0.03))
    if ann.compass:
        cx, cy = w - margin - fsize * 3, margin + fsize * 3
        sy_, sx_ = _inverse_point(geo, solution, cy, cx)
        nvec, evec = _north_east(solution, geo, sy_, sx_)
        length = fsize * 2.6
        for vec, letter in ((nvec, "N"), (evec, "E")):
            ex, ey = cx + vec[1] * length, cy + vec[0] * length
            gd.line([(cx, cy), (ex, ey)], fill=255, width=lw + 1)
            head = np.array([vec[0], vec[1]])
            side = np.array([-head[1], head[0]])
            for sgn in (1, -1):
                hy, hx = (np.array([ey, ex]) - head * fsize * 0.6 + sgn * side * fsize * 0.35)
                gd.line([(ex, ey), (hx, hy)], fill=255, width=lw + 1)
            gd.text((ex + vec[1] * fsize * 0.5 - fsize * 0.3, ey + vec[0] * fsize * 0.5 - fsize * 0.6), letter, font=font, fill=255)
        drawn["compass"] = True
        reach = length + fsize * 1.2
        drawn["reserved"].append((cx - reach, cy - reach, cx + reach, cy + reach))
    if ann.scale_bar:
        px_per_arcmin = 60.0 / solution["scale_arcsec"] * geo.scale
        arcmin = _nice_length(0.25 * w / px_per_arcmin)
        length = arcmin * px_per_arcmin
        x1, y1 = w - margin, h - margin - fsize
        gd.line([(x1 - length, y1), (x1, y1)], fill=255, width=lw + 1)
        for xx in (x1 - length, x1):
            gd.line([(xx, y1 - fsize * 0.4), (xx, y1 + fsize * 0.4)], fill=255, width=lw + 1)
        text = f"{arcmin:g}'" if arcmin < 60 else f"{arcmin / 60:g}°"  # ASCII arcminute mark: the built-in font has no ′
        tb = gd.textbbox((0, 0), text, font=font)
        gd.text((x1 - length / 2 - (tb[2] - tb[0]) / 2, y1 - fsize * 1.5), text, font=font, fill=255)
        drawn["scale_bar"] = {"arcmin": arcmin, "pixels": length}
        drawn["reserved"].append((x1 - length - fsize * 0.5, y1 - fsize * 1.7, x1 + fsize * 0.5, y1 + fsize * 0.6))
    for mask, color in ((obj_mask, OBJECT_COLOR), (guide_mask, GUIDE_COLOR)):
        a = np.asarray(mask, dtype=np.uint32)
        if not a.any():
            continue
        if image.ndim == 3:
            col = np.array(color, dtype=np.uint32)[None, None, : image.shape[2]]
            a3 = a[..., None]
            image[:] = ((image.astype(np.uint32) * (255 - a3) + col * a3 + 127) // 255).astype(np.uint16)
        else:
            image[:] = ((image.astype(np.uint32) * (255 - a) + 65535 * a + 127) // 255).astype(np.uint16)
    return drawn


def _inverse_point(geo: FrameGeometry, solution: dict[str, Any], oy: float, ox: float) -> tuple[float, float]:
    """A display point that maps close to the output point (oy, ox), found from the frame's linear mapping."""
    y0, x0 = geo.map(np.array([0.0, 0.0, 100.0]), np.array([0.0, 100.0, 0.0]))
    A = np.array([[(y0[2] - y0[0]) / 100, (y0[1] - y0[0]) / 100], [(x0[2] - x0[0]) / 100, (x0[1] - x0[0]) / 100]])
    sy, sx = np.linalg.solve(A, np.array([oy - y0[0], ox - x0[0]]))
    return float(np.clip(sy, 0, geo.src_h - 1)), float(np.clip(sx, 0, geo.src_w - 1))


def _inverse_hint(o: dict[str, Any], solution: dict[str, Any]) -> tuple[float, float]:
    y, x = _sky_to_display(solution, [o["_obj"].ra], [o["_obj"].dec])
    return float(y[0]), float(x[0])
