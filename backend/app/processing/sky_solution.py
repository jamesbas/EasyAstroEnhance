"""Sky solution (spec amendment 1.7 A): verify a header WCS against catalog stars, or solve from pointing/scale hints.

All coordinates here are 0-based pixel positions in the FITS file's own row order (so a solution can be written to a
processed FITS and compared with the header WCS); ``to_image_xy`` converts to the displayed array. No blind solving,
no network: the search starts at the hinted centre and covers at most 1.5 field diagonals around it.

Method: stars are measured with the stacking detector; the catalog field is projected gnomonically at each candidate
scale and both parities; the stacking triangle matcher (rotation-, scale- and shift-invariant, RANSAC-confirmed) pairs
image and catalog stars; a TAN projection (plus SIP order 2 when at least 60 matches support it and the residual
improves) is fitted to every unambiguous match; and the result must pass the same checks as a header WCS.
"""
from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io.fits import Header
from astropy.wcs import WCS, FITSFixedWarning
from astropy.wcs.utils import fit_wcs_from_points, proj_plane_pixel_scales
from scipy.spatial import cKDTree

from .catalogs.stars import StarCatalog
from .imagedata import ImageData
from .stacking.quality import StarList, measure
from .stacking.register import match

VERIFY_MIN_MATCHES = 12
VERIFY_MAX_RMS_PX = 1.5
VERIFY_MIN_FRACTION = 0.5
VERIFY_BRIGHTEST = 50
MATCH_RADIUS_PX = 3.0
SCALE_TOLERANCE = 0.15
SEARCH_DIAGONALS = 1.5
SIP_MIN_MATCHES = 60
CATALOG_TRIANGLE_STARS = 80  # the detector skips very bright, bloated stars, so the image's brightest are fainter catalog stars
IMAGE_TRIANGLE_STARS = 40
DETECT_MAX_AREA = 3000  # px: keep bright (bloated, saturated) stars so the image's brightest are the catalog's brightest
SCALE_LADDER = tuple(round(0.6 * 1.3**k, 3) for k in range(11))  # arcsec/px, used only when no scale hint exists


@dataclass
class Hints:
    ra: float | None = None
    dec: float | None = None
    scales: list[float] = field(default_factory=list)  # deg/px candidates
    source: str = ""
    notes: list[str] = field(default_factory=list)


def _wcs(header) -> WCS | None:
    if header is None:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FITSFixedWarning)
            w = WCS(header, naxis=[1, 2]).celestial if not isinstance(header, WCS) else header
        return w if w.has_celestial else None
    except (ValueError, TypeError, KeyError):
        return None


def _scale_deg(w: WCS) -> float:
    return float(np.mean(proj_plane_pixel_scales(w)))


def hints_from_header(header, width: int, height: int) -> Hints:
    h = Hints()
    if header is None:
        return h
    w = _wcs(header)
    if w is not None:
        c = w.pixel_to_world(width / 2 - 0.5, height / 2 - 0.5)
        h.ra, h.dec, h.source = float(c.ra.deg), float(c.dec.deg), "header WCS"
        h.scales = [_scale_deg(w)]
    if h.ra is None:
        for kr, kd in (("RA", "DEC"), ("OBJCTRA", "OBJCTDEC"), ("CRVAL1", "CRVAL2")):
            if kr in header and kd in header:
                try:
                    rv, dv = header[kr], header[kd]
                    c = SkyCoord(rv, dv, unit=("deg", "deg")) if isinstance(rv, (int, float)) else SkyCoord(f"{rv} {dv}", unit=("hourangle", "deg"))
                    h.ra, h.dec, h.source = float(c.ra.deg), float(c.dec.deg), f"header {kr}/{kd}"
                    break
                except (ValueError, TypeError):
                    continue
    try:
        focal = float(header.get("FOCALLEN") or 0)
        pix = float(header.get("XPIXSZ") or header.get("PIXSIZE1") or 0) * float(header.get("XBINNING") or 1)
    except (TypeError, ValueError):
        focal = pix = 0.0
    if focal > 0 and pix > 0:
        s = pix / (focal * 1000.0) * 180.0 / math.pi
        # the stored pixel size does not always match the saved image (for example 2x-binned or upsampled stacks)
        for c in (s, s / 2, s * 2):
            if all(abs(c / x - 1) > 0.05 for x in h.scales):
                h.scales.append(c)
        h.notes.append(f"scale hint {s * 3600:.2f}\"/px from FOCALLEN and XPIXSZ (also tried half and double)")
    return h


def detect(image: ImageData) -> tuple[StarList, float | None]:
    """Stars (brightest first) in FITS-file pixel coordinates, and their median FWHM."""
    px = image.pixels
    L = px.mean(axis=2) if px.ndim == 3 else px
    L = np.where(image.valid_mask, L, np.median(L[image.valid_mask]) if image.valid_mask.any() else 0).astype(np.float32)
    stats, stars = measure(L, "mono", max_area=DETECT_MAX_AREA)
    y = (image.height - 1 - stars.y) if image.flip_rows_on_export else stars.y
    return StarList(stars.x, y, stars.flux), stats.fwhm


def to_image_xy(image_height: int, flip_rows: bool, x, y):
    return x, (image_height - 1 - np.asarray(y)) if flip_rows else y


def _catalog_field(cat: StarCatalog, w: WCS, width: int, height: int) -> dict[str, np.ndarray]:
    c = w.pixel_to_world(width / 2 - 0.5, height / 2 - 0.5)
    radius = 0.55 * math.hypot(width, height) * _scale_deg(w)
    stars = cat.cone(float(c.ra.deg), float(c.dec.deg), radius)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        x, y = w.all_world2pix(stars["ra"], stars["dec"], 0, quiet=True)
    inside = np.isfinite(x) & np.isfinite(y) & (x >= -0.5) & (x < width - 0.5) & (y >= -0.5) & (y < height - 0.5)
    return {k: v[inside] for k, v in stars.items()} | {"x": x[inside], "y": y[inside]}


def _pairs(stars: StarList, cx: np.ndarray, cy: np.ndarray, radius: float = MATCH_RADIUS_PX) -> np.ndarray:
    """(star index, catalog index) for unambiguous nearest matches: one catalog star within ``radius``, the next one
    clearly farther."""
    if len(cx) == 0 or len(stars.x) == 0:
        return np.zeros((0, 2), np.int64)
    k = min(2, len(cx))
    d, i = cKDTree(np.column_stack([cx, cy])).query(np.column_stack([stars.x, stars.y]), k=k)
    if k == 1:
        d, i = d[:, None], i[:, None]
        d = np.column_stack([d, np.full(len(d), np.inf)])
    ok = (d[:, 0] <= radius) & (d[:, 1] - d[:, 0] > 1.0)
    pairs = np.column_stack([np.nonzero(ok)[0], i[ok, 0]])
    # one catalog star may serve only one image star
    _, first = np.unique(pairs[:, 1], return_index=True)
    return pairs[np.sort(first)]


def verify(w: WCS, stars: StarList, cat: StarCatalog, width: int, height: int) -> dict[str, Any]:
    field_ = _catalog_field(cat, w, width, height)
    order = np.argsort(-stars.flux)
    stars = StarList(stars.x[order], stars.y[order], stars.flux[order])
    pairs = _pairs(stars, field_["x"], field_["y"])
    n = len(pairs)
    rms = float(np.sqrt(np.mean((stars.x[pairs[:, 0]] - field_["x"][pairs[:, 1]]) ** 2 + (stars.y[pairs[:, 0]] - field_["y"][pairs[:, 1]]) ** 2))) if n else None
    top = min(VERIFY_BRIGHTEST, len(stars.x))
    frac = float(np.sum(pairs[:, 0] < top) / top) if top else 0.0
    ok = n >= VERIFY_MIN_MATCHES and rms is not None and rms <= VERIFY_MAX_RMS_PX and frac >= VERIFY_MIN_FRACTION
    reason = None
    if not ok:
        reason = (f"{n} catalog matches (need {VERIFY_MIN_MATCHES}), RMS {rms:.2f} px (max {VERIFY_MAX_RMS_PX}), "
                  f"{frac:.0%} of the brightest {top} stars matched (need {VERIFY_MIN_FRACTION:.0%})" if rms is not None
                  else f"no detected star matches a catalog star ({len(field_['x'])} catalog stars in the field)")
    return {"ok": ok, "matches": n, "rms_px": rms, "brightest_fraction": frac, "catalog_stars_in_field": int(len(field_["x"])),
            "detected_stars": int(len(stars.x)), "reason": reason, "pairs": pairs, "stars": stars, "field": field_}


def _gnomonic(ra0: float, dec0: float, ra: np.ndarray, dec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a0, d0, a, d = map(np.radians, (ra0, dec0, ra, dec))
    den = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    xi = np.cos(d) * np.sin(a - a0) / den
    eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / den
    return np.degrees(xi), np.degrees(eta)


def _fit(stars: StarList, field_: dict[str, np.ndarray], pairs: np.ndarray, sip: int | None) -> WCS:
    world = SkyCoord(field_["ra"][pairs[:, 1]], field_["dec"][pairs[:, 1]], unit="deg")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fit_wcs_from_points((stars.x[pairs[:, 0]], stars.y[pairs[:, 0]]), world, proj_point="center", projection="TAN", sip_degree=sip)


def _refine(w: WCS, stars: StarList, cat: StarCatalog, width: int, height: int) -> tuple[WCS, dict[str, Any]]:
    """Re-collect matches over the whole field and refit (TAN, then SIP order 2 when it is supported and helps)."""
    best = verify(w, stars, cat, width, height)
    for _ in range(3):
        if best["matches"] < 6:
            break
        w2 = _fit(best["stars"], best["field"], best["pairs"], None)
        v2 = verify(w2, stars, cat, width, height)
        if v2["matches"] < best["matches"] and v2["ok"] <= best["ok"]:
            break
        w, best = w2, v2
    if best["matches"] >= SIP_MIN_MATCHES:
        w3 = _fit(best["stars"], best["field"], best["pairs"], 2)
        v3 = verify(w3, stars, cat, width, height)
        if v3["ok"] and v3["rms_px"] < best["rms_px"] * 0.95 and v3["matches"] >= best["matches"]:
            w, best = w3, v3
    return w, best


def _candidate_centres(ra0: float, dec0: float, field_deg: float, diag_deg: float):
    """(ring, ra, dec): the hint first, then rings half a field apart out to 1.5 field diagonals."""
    yield 0, ra0, dec0
    step = field_deg / 2
    for ring in range(1, int(math.ceil(SEARCH_DIAGONALS * diag_deg / step)) + 1):
        r = ring * step
        n = max(6, int(round(2 * math.pi * r / step)))
        for k in range(n):
            th = 2 * math.pi * k / n
            dd = dec0 + r * math.cos(th)
            if abs(dd) > 90:
                continue
            yield ring, (ra0 + r * math.sin(th) / max(math.cos(math.radians(dd)), 1e-3)) % 360.0, dd


def solve_hinted(stars: StarList, cat: StarCatalog, hints: Hints, width: int, height: int,
                 check: Callable[[], None] | None = None, deadline_s: float = 120.0) -> tuple[WCS | None, dict[str, Any]]:
    if hints.ra is None or hints.dec is None:
        return None, {"reason": "No pointing hint: the file has no RA/DEC; type the approximate centre or a target name."}
    if len(stars.x) < 10:
        return None, {"reason": f"Only {len(stars.x)} stars were detected; at least 10 are needed to solve."}
    scales = hints.scales or [s / 3600 for s in SCALE_LADDER]
    t0 = time.perf_counter()
    cur = stars.top(200)
    tried = 0
    # nearest positions first, every scale at each distance (the hinted scale may be off by 2x)
    plan = sorted(((ring, si, ra_c, dec_c) for si, scale in enumerate(scales)
                   for ring, ra_c, dec_c in _candidate_centres(hints.ra, hints.dec, min(width, height) * scale, math.hypot(width, height) * scale)),
                  key=lambda c: (c[0], c[1]))
    for _ring, si, ra_c, dec_c in plan:
        scale = scales[si]
        diag = math.hypot(width, height) * scale
        if check:
            check()
        if time.perf_counter() - t0 > deadline_s:
            return None, {"reason": f"No match within {deadline_s:.0f} s around the hint ({tried} positions tried).", "tried": tried}
        cone = cat.cone(ra_c, dec_c, 0.5 * diag)
        if len(cone["ra"]) < 10:
            continue
        xi, eta = _gnomonic(ra_c, dec_c, cone["ra"], cone["dec"])
        flux = 10 ** (-0.4 * (cone["g"] - 10))
        for parity in (1.0, -1.0):
            tried += 1
            ref = StarList(parity * xi / scale, -eta / scale, flux)
            m = match(ref, cur, (1 - SCALE_TOLERANCE, 1 + SCALE_TOLERANCE), n_top=IMAGE_TRIANGLE_STARS, n_top_ref=CATALOG_TRIANGLE_STARS)
            if not m.ok or m.transform is None:
                continue
            # image star -> tangent plane: build an initial TAN WCS from the similarity transform
            t = m.transform
            tx, ty = t.apply(cur.x, cur.y)
            tree = cKDTree(np.column_stack([ref.x, ref.y]))
            d, i = tree.query(np.column_stack([tx, ty]), distance_upper_bound=2.5)
            good = np.isfinite(d)
            if good.sum() < 8:
                continue
            field0 = {"ra": cone["ra"], "dec": cone["dec"]}
            w0 = _fit(cur, field0, np.column_stack([np.nonzero(good)[0], i[good]]), None)
            w, v = _refine(w0, stars, cat, width, height)
            if v["ok"]:
                return w, {"tried": tried, "scale_hint_arcsec": scale * 3600, "parity": "mirrored" if parity < 0 else "normal",
                           "seconds": round(time.perf_counter() - t0, 2), **_public(v)}
    return None, {"reason": f"No confirmed match around the hint ({tried} position/scale/parity combinations tried).", "tried": tried,
                  "seconds": round(time.perf_counter() - t0, 2)}


def _public(v: dict[str, Any]) -> dict[str, Any]:
    return {k: v[k] for k in ("matches", "rms_px", "brightest_fraction", "catalog_stars_in_field", "detected_stars")}


def describe(w: WCS, width: int, height: int) -> dict[str, Any]:
    c = w.pixel_to_world(width / 2 - 0.5, height / 2 - 0.5)
    cd = w.pixel_scale_matrix
    north = np.linalg.solve(cd, [0.0, 1.0])  # pixel direction of increasing declination
    return {"center_ra": float(c.ra.deg), "center_dec": float(c.dec.deg), "center": c.to_string("hmsdms", precision=0),
            "scale_arcsec": _scale_deg(w) * 3600,
            "north_angle_deg": float(np.degrees(np.arctan2(north[0], north[1]))),  # from the file's +y axis toward +x
            "field_deg": [width * _scale_deg(w), height * _scale_deg(w)], "mirrored": bool(np.linalg.det(cd) > 0),
            "sip": w.sip is not None}


def header_cards(w: WCS) -> dict[str, Any]:
    h = w.to_header(relax=True)
    return {k: h[k] for k in h if k not in ("COMMENT", "HISTORY", "WCSAXES", "DATEREF", "MJDREF", "MJDREFI", "MJDREFF")}


def wcs_from_cards(cards: dict[str, Any]) -> WCS | None:
    hdr = Header()
    for k, v in cards.items():
        hdr[k] = v
    return _wcs(hdr)


def sky_solution(image: ImageData, cat: StarCatalog, user: dict[str, Any] | None = None, check: Callable[[], None] | None = None,
                 resolve_name: Callable[[str], tuple[float, float, str] | None] | None = None) -> dict[str, Any]:
    """The per-image sky solution: header WCS (verified), else a hinted solve. Never raises for an unsolvable image."""
    t0 = time.perf_counter()
    W, H = image.width, image.height
    stars, fwhm = detect(image)
    out: dict[str, Any] = {"status": "unavailable", "source": None, "reason": None, "detected_stars": int(len(stars.x)),
                           "star_fwhm_px": fwhm, "catalog": cat.header.get("source"), "checks": {
                               "min_matches": VERIFY_MIN_MATCHES, "max_rms_px": VERIFY_MAX_RMS_PX,
                               "min_brightest_fraction": VERIFY_MIN_FRACTION, "brightest": VERIFY_BRIGHTEST}}
    header_note = None
    hw = _wcs(image.header)
    if hw is not None and not (user and (user.get("ra") is not None or user.get("name"))):
        v = verify(hw, stars, cat, W, H)
        if v["ok"]:
            out.update(status="verified", source="header", header=header_cards(hw), **describe(hw, W, H), **_public(v),
                       seconds=round(time.perf_counter() - t0, 2))
            return out
        header_note = f"The file's WCS did not pass verification: {v['reason']}."
    hints = hints_from_header(image.header, W, H)
    if user:
        if user.get("name") and resolve_name:
            r = resolve_name(str(user["name"]))
            if r is None:
                out["reason"] = f"“{user['name']}” was not found in the object catalog."
                return out
            hints.ra, hints.dec, hints.source = r[0], r[1], f"target name ({r[2]})"
        if user.get("ra") is not None and user.get("dec") is not None:
            hints.ra, hints.dec, hints.source = float(user["ra"]), float(user["dec"]), "typed coordinates"
        if user.get("field_width_deg"):
            hints.scales = [float(user["field_width_deg"]) / W]
    w, info = solve_hinted(stars, cat, hints, W, H, check)
    out["hints"] = {"source": hints.source, "ra": hints.ra, "dec": hints.dec, "scales_arcsec": [s * 3600 for s in hints.scales], "notes": hints.notes}
    if w is None:
        out["reason"] = " ".join(filter(None, [header_note, info.get("reason")]))
        out["seconds"] = round(time.perf_counter() - t0, 2)
        return out
    out.update(status="solved", source="hinted solve", header=header_cards(w), **describe(w, W, H),
               **{k: v for k, v in info.items() if k not in ("reason", "seconds")}, header_note=header_note,
               seconds=round(time.perf_counter() - t0, 2))
    return out
