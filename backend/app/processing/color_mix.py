"""Linear FITS channel combination on the first input's grid; never modify a source."""
from __future__ import annotations

from typing import Callable

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import NoConvergence
from scipy import ndimage

from .catalog_color import celestial_wcs
from .color import luminance
from .imagedata import ImageData, ProcessingError

MIX_ROLES = {
    "RGB": ("Red", "Green", "Blue"),
    "LRGB": ("Red", "Green", "Blue", "Luminance"),
    "HOO": ("Ha", "OIII"),
    "SHO": ("SII", "Ha", "OIII"),
    "DUAL-SHO": ("Ha/OIII", "SII/OIII"),
    "HA-RGB": ("Broadband RGB", "Ha"),
}
RGB_SLOTS = {"DUAL-SHO": {0, 1}, "HA-RGB": {0}}


def _coordinates(sw, rw, x, y, source: ImageData, ref: ImageData):
    ry = ref.height - 1 - y if ref.flip_rows_on_export else y
    sky = rw.pixel_to_world(x, ry)
    if not isinstance(sky, SkyCoord):
        raise ValueError("the reference WCS is not celestial")
    sx, sy = sw.world_to_pixel(sky)
    return sx, source.height - 1 - sy if source.flip_rows_on_export else sy


def _align(source: ImageData, ref: ImageData, prealigned: bool, check: Callable[[], None]):
    same = source.pixels.shape[:2] == ref.pixels.shape[:2]
    if source is ref:
        return source.pixels, source.valid_mask, "reference"
    rw, sw = celestial_wcs(ref.header), celestial_wcs(source.header)
    if rw is None or sw is None:
        if same and prealigned:
            return source.pixels, source.valid_mask, "user-confirmed same grid"
        raise ProcessingError("NEED_ALIGNMENT", "Use solved FITS masters or confirm that same-size masters are already aligned.")
    try:
        xx, yy = np.meshgrid(np.linspace(0, ref.width - 1, 5), np.linspace(0, ref.height - 1, 5))
        sx, sy = _coordinates(sw, rw, xx, yy, source, ref)
        if same and np.allclose(sx, xx, atol=1e-4, rtol=0) and np.allclose(sy, yy, atol=1e-4, rtol=0):
            return source.pixels, source.valid_mask, "same WCS grid"
        shape = (ref.height, ref.width)
        out = np.empty(shape + source.pixels.shape[2:], dtype=np.result_type(source.pixels, np.float32))
        valid = np.empty(shape, dtype=bool)
        planes = (source.pixels,) if source.channels == 1 else np.moveaxis(source.pixels, -1, 0)
        dest = (out,) if source.channels == 1 else np.moveaxis(out, -1, 0)
        mask = source.valid_mask.astype(np.float32)
        for top in range(0, ref.height, 128):
            check()
            stop = min(top + 128, ref.height)
            x, y = np.meshgrid(np.arange(ref.width), np.arange(top, stop))
            sx, sy = _coordinates(sw, rw, x, y, source, ref)
            coords = np.stack((sy, sx))
            valid[top:stop] = ndimage.map_coordinates(mask, coords, order=1, mode="constant", cval=0) >= 1 - 1e-6
            for d, p in zip(dest, planes):
                d[top:stop] = ndimage.map_coordinates(p, coords, order=1, mode="constant", cval=0)
        return out, valid, "celestial WCS (bilinear)"
    except (ValueError, NoConvergence) as exc:
        raise ProcessingError("MIX_WCS", "Unable to align these masters with their FITS sky coordinates.", str(exc)) from exc


def combine_channels(
    images: list[ImageData], mode: str, gains: list[float], strength: float, prealigned: bool, check: Callable[[], None],
) -> tuple[np.ndarray, fits.Header]:
    roles = MIX_ROLES[mode]
    if len(images) != len(roles) or len(gains) != len(roles):
        raise ProcessingError("MIX_ROLES", "Select one master and one scale for each channel role.")
    ref = images[0]
    inputs: list[np.ndarray] = []
    methods = []
    valid = ref.valid_mask.copy()
    for i, (image, gain, role) in enumerate(zip(images, gains, roles, strict=True)):
        if image.domain != "linear" or image.channels != (3 if i in RGB_SLOTS.get(mode, ()) else 1):
            raise ProcessingError("MIX_INPUT", f"{role} needs a confirmed linear {'RGB' if i in RGB_SLOTS.get(mode, ()) else 'monochrome'} master.")
        values, mask, method = _align(image, ref, prealigned, check)
        inputs.append(values if gain == 1 else values * gain)
        valid &= mask
        methods.append(method)
    if valid.mean() < 0.25:
        raise ProcessingError("MIX_OVERLAP", "The masters have less than 25% valid common coverage on the reference grid.")
    if mode in ("RGB", "SHO", "LRGB"):
        rgb = np.stack(inputs[:3], axis=-1)
        if mode == "LRGB":
            # Mix separately scaled luminance into all three channels without a per-channel autostretch.
            rgb += (strength * (inputs[3] - luminance(np, rgb)))[..., None]
    elif mode == "HOO":
        rgb = np.stack((inputs[0], inputs[1], inputs[1]), axis=-1)
    elif mode == "DUAL-SHO":
        ha, sii = inputs
        rgb = np.stack((sii[..., 0], ha[..., 0], (ha[..., 1] + ha[..., 2] + sii[..., 1] + sii[..., 2]) * 0.25), axis=-1)
    else:
        rgb = inputs[0].copy()
        r = rgb[..., 0]
        r += strength * np.maximum(inputs[1] - r, 0)
    if not np.isfinite(rgb[valid]).all():
        raise ProcessingError("MIX_NONFINITE", "This mix overflowed. Try smaller scales.")
    rgb[~valid] = np.nan
    wcs = celestial_wcs(ref.header)
    header = wcs.to_header(relax=True) if wcs is not None else fits.Header()
    header["ROWORDER"] = "BOTTOM-UP" if ref.flip_rows_on_export else "TOP-DOWN"
    header["CTYPE3"] = "RGB"
    header["EAEMIX"] = mode
    if all(img.units == ref.units for img in images) and "unspecified" not in ref.units:
        header["BUNIT"] = ref.units
    header.add_history(f"EasyAstroEnhance linear channel mix: {mode}, strength={strength:g}.")
    header.add_history(f"Common valid coverage: {valid.mean():.6f}. Other pixels are NaN.")
    if mode == "DUAL-SHO":
        header.add_history("OIII is estimated as mean of G and B from both input stacks.")
    for role, amp, method, image in zip(roles, gains, methods, images, strict=True):
        header.add_history(f"{role}: scale={amp:g}, alignment={method}.")
        header.add_history(f"SHA256 {image.source_hash}")
    return rgb[::-1] if ref.flip_rows_on_export else rgb, header
