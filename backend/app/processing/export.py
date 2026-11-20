"""Export encoders (display PNG/TIFF/JPEG, processed FITS, comparison image). Pure functions: no HTTP or DB.

Display exports quantize only here, at the chosen bit depth. Previews are never used as masters.
"""
from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path
from typing import Any

import imagecodecs
import numpy as np
import tifffile
from astropy.io import fits
from PIL import Image, ImageDraw, ImageFont

from .imagedata import ImageData
from .readers.fits import SENSITIVE_KEYS
from .recipe import PIPELINE_VERSION

DEFERRED_TIFF = "enhanced-display.tif"  # rendered on request from the run's display.npy


def quantize(display: np.ndarray, bits: int) -> np.ndarray:
    maxv = 255 if bits == 8 else 65535
    dtype = np.uint8 if bits == 8 else np.uint16
    return np.rint(np.clip(display.astype(np.float64), 0.0, 1.0) * maxv).astype(dtype)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def encode_png(arr: np.ndarray, edit_metadata: bytes | None = None) -> bytes:
    png = bytes(imagecodecs.png_encode(np.ascontiguousarray(arr), level=6))
    # Insert sRGB (perceptual intent) and optional ASCII JSON for the sharing copy after IHDR.
    chunks = _png_chunk(b"sRGB", b"\x00")
    if edit_metadata is not None:
        chunks += _png_chunk(b"tEXt", b"EasyAstroEnhance\x00" + edit_metadata)
    return png[:33] + chunks + png[33:]


def write_png(path: Path, display: np.ndarray, bits: int) -> None:
    path.write_bytes(encode_png(quantize(display, bits)))


def write_tiff16(path: Path, display: np.ndarray) -> None:
    write_tiff16_u16(path, quantize(display, 16))


def write_tiff16_u16(path: Path, arr: np.ndarray, engine: str = PIPELINE_VERSION) -> None:
    """16-bit display TIFF from already quantized values (the stored viewer array is exactly ``quantize(display, 16)``)."""
    tifffile.imwrite(
        path, np.ascontiguousarray(arr), photometric="rgb" if arr.ndim == 3 else "minisblack", compression="zlib",
        software=f"EasyAstroEnhance {engine}", metadata=None,
    )


def to_u8(display: np.ndarray) -> np.ndarray:
    return quantize(display, 8)


def write_jpeg(path: Path, display: np.ndarray, quality: int = 95) -> None:
    arr = to_u8(display)
    Image.fromarray(arr, "RGB" if arr.ndim == 3 else "L").save(path, "JPEG", quality=quality, subsampling=0, optimize=True)


def resize_u8(arr: np.ndarray, max_edge: int) -> tuple[np.ndarray, float]:
    """Downsample for previews (never for masters). Returns (array, scale)."""
    h, w = arr.shape[:2]
    scale = min(1.0, max_edge / max(h, w))
    if scale >= 1.0:
        return arr, 1.0
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    im = Image.fromarray(arr, "RGB" if arr.ndim == 3 else "L").resize(size, Image.Resampling.LANCZOS)
    return np.asarray(im), scale


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def comparison_jpeg(path: Path, baseline: np.ndarray, enhanced: np.ndarray, left_label: str, right_label: str, max_edge: int = 1400) -> None:
    """Share-sized side-by-side comparison with both sides at identical geometry."""
    a, _ = resize_u8(to_u8(baseline), max_edge)
    b, _ = resize_u8(to_u8(enhanced), max_edge)
    ia = Image.fromarray(a, "RGB" if a.ndim == 3 else "L").convert("RGB")
    ib = Image.fromarray(b, "RGB" if b.ndim == 3 else "L").convert("RGB")
    bar = 40
    canvas = Image.new("RGB", (ia.width + ib.width + 6, ia.height + bar), (20, 22, 26))
    canvas.paste(ia, (0, bar))
    canvas.paste(ib, (ia.width + 6, bar))
    d = ImageDraw.Draw(canvas)
    f = _font(20)
    d.text((10, 8), left_label, fill=(230, 232, 236), font=f)
    d.text((ia.width + 16, 8), right_label, fill=(120, 170, 255), font=f)
    canvas.save(path, "JPEG", quality=92)


# ------------------------------------------------------------------------------------------------ FITS
_STRUCTURAL = {
    "SIMPLE", "BITPIX", "EXTEND", "XTENSION", "PCOUNT", "GCOUNT", "BSCALE", "BZERO", "BLANK", "DATAMIN", "DATAMAX",
    "CHECKSUM", "DATASUM", "BUNIT", "THEAP", "TFIELDS",
}


_COMPRESSION_PREFIXES = (
    "ZIMAGE", "ZCMPTYPE", "ZBITPIX", "ZNAXIS", "ZTILE", "ZNAME", "ZVAL", "ZQUANTIZ", "ZDITHER", "ZSIMPLE",
    "ZEXTEND", "ZPCOUNT", "ZGCOUNT", "ZTENSION", "ZMASKCMP", "ZHECKSUM", "ZDATASUM",
)


def _clean_header(src: fits.Header | None, strip_sensitive: bool) -> tuple[fits.Header, str | None]:
    out = fits.Header()
    bunit = None
    if src is None:
        return out, None
    bunit = src.get("BUNIT")
    for card in src.cards:
        key = card.keyword
        if key in _STRUCTURAL or key.startswith("NAXIS") or key.startswith(_COMPRESSION_PREFIXES):
            continue
        if key == "" or key in ("COMMENT", "HISTORY"):
            out.append(card)
            continue
        if strip_sensitive and key.upper() in SENSITIVE_KEYS:
            continue
        try:
            out.append(card)
        except Exception:
            continue
    return out, (str(bunit) if bunit is not None else None)


def write_fits(
    path: Path,
    image: ImageData,
    data: np.ndarray,
    kind: str,
    preset: str,
    strip_sensitive: bool = True,
    extra_history: list[str] | None = None,
    solved_wcs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write float FITS (stale integer scaling/BLANK removed; checksums added by Astropy).

    ``kind`` is ``processed-linear`` (source units, before any display-only operation) or
    ``display-processed`` (normalized display values mapped back with the recorded shared scale)."""
    arr = np.array(data, copy=True)
    if arr.dtype not in (np.float32, np.float64):
        arr = arr.astype(np.float32)
    if kind == "display-processed":
        arr = (arr.astype(np.float64) * image.normalization.scale + image.normalization.offset).astype(
            np.float64 if image.pixels.dtype == np.float64 else np.float32
        )
    arr = np.where(image.valid_mask[..., None] if arr.ndim == 3 else image.valid_mask, arr, np.nan).astype(arr.dtype)
    if image.flip_rows_on_export:
        arr = np.ascontiguousarray(arr[::-1])
    meta = image.metadata.get("fits", {})
    layout = meta.get("layout")
    if arr.ndim == 3 and layout == "rgb_planes":
        arr = np.moveaxis(arr, -1, 0)
    shape = meta.get("shape")
    if shape and int(np.prod(shape)) == arr.size:
        arr = arr.reshape(shape)
    header, bunit = _clean_header(image.header, strip_sensitive)
    hdu = fits.PrimaryHDU(data=np.ascontiguousarray(arr), header=header)
    h = hdu.header
    h["EAEVER"] = (PIPELINE_VERSION, "EasyAstroEnhance pipeline version")
    h["EAEKIND"] = (kind, "EasyAstroEnhance export kind")
    h["EAESHA"] = image.source_hash
    h["EAEPRE"] = (preset[:60], "preset/recipe name")
    if bunit:
        h["EAEUNIT"] = (bunit[:60], "original BUNIT")
    h.add_history(f"EasyAstroEnhance {PIPELINE_VERSION} {kind}.")
    if kind == "processed-linear":
        h.add_history("Contains only linear operations: background/gradient correction, per-channel sky offsets,")
        h.add_history("bounded white-balance gains, optional deconvolution and denoising. No stretch, tone,")
        h.add_history("contrast, saturation or star stretch. Exact values are in processing.json.")
    elif kind == "starless-linear":
        h.add_history("The processed-linear data with stars removed by learned (AI) star separation.")
        h.add_history("Large or saturated stars may remain partly. Stars-linear = processed - starless.")
    else:
        h.add_history("Display-processed values (tone/contrast/color applied); not linear data.")
    if strip_sensitive:
        h.add_history("Location/observer keywords were removed from this export.")
    for line in extra_history or []:
        h.add_history(line[:70])
    if solved_wcs:
        # a hinted solve replaces any (unverified) WCS in the source header; a verified header WCS is passed through as is
        for key in [k for k in h.keys() if k.split("_")[0] in WCS_KEY_PREFIXES or k[:5] in ("CTYPE", "CRVAL", "CRPIX", "CUNIT", "CDELT", "CROTA")
                    or k[:2] in ("CD", "PC") and len(k) <= 6]:
            del h[key]
        for k, v in solved_wcs.items():
            h[k] = v
        h["EAEWCS"] = ("solved", "WCS from the EasyAstroEnhance hinted solve")
        h.add_history("WCS solved by EasyAstroEnhance from catalog stars (Gaia DR3); see processing.json.")
    hdu.writeto(path, overwrite=True, checksum=True)
    return {"bitpix": int(hdu.header["BITPIX"]), "shape": list(arr.shape), "kind": kind}


WCS_KEY_PREFIXES = ("A", "B", "AP", "BP")


def header_text(header: fits.Header) -> str:
    return header.tostring(sep="\n", endcard=True)


