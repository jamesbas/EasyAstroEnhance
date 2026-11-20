"""Lucky imaging of Seestar Moon / planet / Sun videos (H13): uncompressed RAW AVI reader and a frame-selecting stacker.

Seestar "RAW" videos are uncompressed 8-bit Bayer frames in an AVI (OpenDML, with an AVIX continuation beyond 1 GB);
a ``.avi.txt`` sidecar names the Bayer pattern (for example ``Bayer = GR``). The stacker:

1. scores every frame for sharpness on a 2 x 2 super-pixel luminance proxy: the variance of the Laplacian of the lightly
   smoothed proxy, divided by the squared mean brightness so dimmer (cloud-veiled) frames are not favoured;
2. drops frames dimmer than 70 % of the median (clouds) and keeps the sharpest ``keep`` fraction (at least 20 frames);
3. aligns each kept frame to the sharpest one by phase correlation with a sub-pixel (parabolic) peak - a global
   translation; local (multi-point) alignment is not done;
4. debayers each kept frame (bilinear) and averages them on the shifted grid; pixels some frames did not cover are
   averaged over the frames that did.

Every output value is an average of measured, resampled pixels: nothing is synthesized. The result is a linear RGB FITS.
"""
from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
from astropy.io import fits
from scipy import ndimage

from ..imagedata import ProcessingError
from .calibrate import debayer

VIDEO_STACK_VERSION = "1.0.0"
DEFAULT_KEEP = 0.25
MIN_KEEP = 20
MIN_BRIGHTNESS = 0.7
SATURATION_WARN = 0.05  # warn when this share of the target's bright pixels is at full scale
FRAME_IDS = (b"00db", b"00dc")
BAYER_FROM_SEESTAR = {"GR": "GRBG", "RG": "RGGB", "BG": "BGGR", "GB": "GBRG"}


@dataclass
class RawVideo:
    path: Path
    width: int
    height: int
    bits: int
    bottom_up: bool
    offsets: list[int] = field(default_factory=list)
    bayer: str | None = None
    sidecar: dict[str, str] = field(default_factory=dict)

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * (self.bits // 8)

    def read(self, i: int, fh=None) -> np.ndarray:
        own = fh is None
        f = open(self.path, "rb") if own else fh
        try:
            f.seek(self.offsets[i])
            buf = f.read(self.frame_bytes)
        finally:
            if own:
                f.close()
        a = np.frombuffer(buf, dtype=np.uint8 if self.bits == 8 else "<u2").reshape(self.height, self.width)
        return a[::-1] if self.bottom_up else a


def read_sidecar(path: Path) -> dict[str, str]:
    side = path.with_name(path.name + ".txt")
    out: dict[str, str] = {}
    try:
        for line in side.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("[") and line.endswith("]"):
                out["INSTRUMENT"] = line[1:-1]
            elif "=" in line:
                k, v = line.split("=", 1)
                out[k.strip().upper()] = v.strip()
    except OSError:
        pass
    return out


def open_avi(path: str | Path) -> RawVideo:
    p = Path(path)
    size = p.stat().st_size
    with open(p, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"AVI ":
            raise ProcessingError("NOT_AVI", "This is not an AVI video.")
        width = height = bits = 0
        bottom_up = True
        offsets: list[int] = []

        def walk(start: int, end: int, in_movi: bool) -> None:
            nonlocal width, height, bits, bottom_up
            off = start
            while off + 8 <= min(end, size):
                f.seek(off)
                cid, sz = struct.unpack("<4sI", f.read(8))
                if cid in (b"RIFF", b"LIST"):
                    kind = f.read(4)
                    if kind in (b"AVI ", b"AVIX", b"hdrl", b"strl", b"movi", b"rec "):
                        walk(off + 12, off + 8 + sz, in_movi or kind == b"movi")
                elif cid == b"strf" and not width:
                    _, w, h, _, bc = struct.unpack("<IiiHH", f.read(16))
                    width, height, bits, bottom_up = w, abs(h), bc, h > 0
                elif in_movi and cid in FRAME_IDS and width and sz == width * height * (bits // 8) and off + 8 + sz <= size:
                    offsets.append(off + 8)
                off += 8 + sz + (sz & 1)

        walk(12, size, False)  # continues past the first RIFF into any AVIX continuation (sizes are clamped to the file)
    if not width or bits not in (8, 16):
        raise ProcessingError("UNSUPPORTED_VIDEO", "Only uncompressed 8- or 16-bit RAW videos (Seestar \"RAW\" AVI) can be stacked.")
    if not offsets:
        raise ProcessingError("NO_FRAMES", "No video frames were found in this file.")
    side = read_sidecar(p)
    bayer = BAYER_FROM_SEESTAR.get(side.get("BAYER", "").upper())
    return RawVideo(p, width, height, bits, bottom_up, offsets, bayer, side)


def _proxy(raw: np.ndarray) -> np.ndarray:
    h, w = raw.shape[0] // 2 * 2, raw.shape[1] // 2 * 2
    a = raw[:h, :w].astype(np.float32)
    return 0.25 * (a[0::2, 0::2] + a[0::2, 1::2] + a[1::2, 0::2] + a[1::2, 1::2])


def sharpness(p: np.ndarray) -> tuple[float, float]:
    s = ndimage.gaussian_filter(p, 1.0)
    lap = ndimage.laplace(s)
    mean = float(p.mean())
    return float(lap.var() / max(mean, 1e-6) ** 2), mean


def _phase_shift(ref_f: np.ndarray, img: np.ndarray, window: np.ndarray) -> tuple[float, float, float]:
    """(dy, dx, peak) that moves ``img`` onto the reference (sub-pixel, parabolic peak)."""
    F = np.fft.rfft2((img - img.mean()) * window)
    R = ref_f * np.conj(F)
    R /= np.maximum(np.abs(R), 1e-12)
    c = np.fft.irfft2(R, s=img.shape)
    iy, ix = np.unravel_index(int(np.argmax(c)), c.shape)
    h, w = c.shape

    def sub(cm, c0, cp):
        d = cm - 2 * c0 + cp
        return 0.5 * (cm - cp) / d if abs(d) > 1e-12 else 0.0

    dy = iy + sub(c[(iy - 1) % h, ix], c[iy, ix], c[(iy + 1) % h, ix])
    dx = ix + sub(c[iy, (ix - 1) % w], c[iy, ix], c[iy, (ix + 1) % w])
    dy = dy - h if dy > h / 2 else dy
    dx = dx - w if dx > w / 2 else dx
    return float(dy), float(dx), float(c[iy, ix])


def stack_video(video: RawVideo, keep: float = DEFAULT_KEEP, check: Callable[[], None] | None = None,
                progress: Callable[[str, float], None] | None = None) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """(H x W x 3 float32 in 0..1 (mono: H x W), coverage count, report)."""
    t0 = time.perf_counter()
    n = len(video.offsets)
    scores = np.zeros(n)
    bright = np.zeros(n)
    with open(video.path, "rb") as fh:
        for i in range(n):
            if check and i % 16 == 0:
                check()
            if progress and i % 25 == 0:
                progress(f"Grading video frames ({i}/{n})", 0.4 * i / n)
            scores[i], bright[i] = sharpness(_proxy(video.read(i, fh)))
        ok = bright >= MIN_BRIGHTNESS * np.median(bright)
        order = [int(i) for i in np.argsort(-scores) if ok[i]]
        n_keep = min(len(order), max(MIN_KEEP, int(round(keep * n))))
        chosen = order[:n_keep]
        if len(chosen) < 2:
            raise ProcessingError("TOO_FEW_FRAMES", "Too few usable frames in this video (clouds or a very short recording).")
        ref = _proxy(video.read(chosen[0], fh))
        full_code = (1 << video.bits) - 1
        best_raw = video.read(chosen[0], fh)
        bright_px = best_raw >= 0.5 * float(best_raw.max())
        saturated_share = float((best_raw >= full_code).sum() / max(int(bright_px.sum()), 1))
        window = np.outer(np.hanning(ref.shape[0]), np.hanning(ref.shape[1])).astype(np.float32)
        ref_f = np.fft.rfft2((ref - ref.mean()) * window)
        scale = 255.0 if video.bits == 8 else 65535.0
        H, W = video.height, video.width
        acc = np.zeros((H, W, 3) if video.bayer else (H, W), np.float64)
        cov = np.zeros((H, W), np.float32)
        shifts = []
        for k, i in enumerate(chosen):
            if check:
                check()
            if progress and k % 5 == 0:
                progress(f"Aligning and stacking ({k}/{len(chosen)})", 0.4 + 0.6 * k / len(chosen))
            raw = video.read(i, fh).astype(np.float32) / scale
            dy, dx, _ = (0.0, 0.0, 1.0) if k == 0 else _phase_shift(ref_f, _proxy(video.read(i, fh)), window)
            dy, dx = 2 * dy, 2 * dx  # proxy pixels are 2 x 2 frame pixels
            shifts.append((dy, dx))
            img = debayer(raw, video.bayer) if video.bayer else raw
            m = np.ones((H, W), np.float32)
            if img.ndim == 3:
                img = np.stack([ndimage.shift(img[..., c], (dy, dx), order=1, mode="constant", cval=0.0) for c in range(3)], -1)
            else:
                img = ndimage.shift(img, (dy, dx), order=1, mode="constant", cval=0.0)
            m = ndimage.shift(m, (dy, dx), order=1, mode="constant", cval=0.0)
            acc += img * (m[..., None] if img.ndim == 3 else m)
            cov += m
    data = (acc / np.maximum(cov, 1e-6)[..., None] if acc.ndim == 3 else acc / np.maximum(cov, 1e-6)).astype(np.float32)
    data[cov < 0.5] = np.nan
    sh = np.array(shifts)
    report = {
        "mode": "video", "video_stack_version": VIDEO_STACK_VERSION, "frames_total": n, "frames_used": len(chosen),
        "rejected_dim_frames": int((~ok).sum()), "keep_fraction": keep, "bayer": video.bayer, "frame_size": [W, H],
        "bits": video.bits, "sharpness": {"best": float(scores[chosen[0]]), "worst_kept": float(scores[chosen[-1]]),
                                          "median_all": float(np.median(scores))},
        "alignment": {"method": "phase correlation on a 2x2 super-pixel proxy, sub-pixel parabolic peak (global translation)",
                      "max_shift_px": float(np.abs(sh).max()) if len(sh) else 0.0},
        "integration": {"method": "bilinear debayer, shift, mean over covering frames"},
        "saturation": {"bright_pixels_at_full_scale": round(saturated_share, 3),
                       "warning": (f"{saturated_share:.0%} of the target's bright pixels are at full scale in the recorded frames "
                                   "(over-exposed): detail there was not recorded and cannot be recovered. Lower the exposure or gain "
                                   "when recording.") if saturated_share >= SATURATION_WARN else None},
        "seconds": round(time.perf_counter() - t0, 1),
    }
    return data, cov, report


def write_video_fits(path: Path, video: RawVideo, data: np.ndarray, report: dict[str, Any]) -> None:
    arr = np.moveaxis(data, -1, 0) if data.ndim == 3 else data
    h = fits.Header()
    side = video.sidecar
    if side.get("INSTRUMENT"):
        h["INSTRUME"] = side["INSTRUMENT"][:60]
    if side.get("OBJECT"):
        h["OBJECT"] = side["OBJECT"][:60]
    if side.get("DATE-OBS"):
        h["DATE-OBS"] = side["DATE-OBS"][:60]
    h["IMAGETYP"] = ("Light", "lucky-imaging stack of video frames")
    h["STACKCNT"] = (report["frames_used"], "video frames integrated")
    h["ROWORDER"] = ("TOP-DOWN", "rows stored in display order")
    if data.ndim == 3:
        h["CTYPE3"] = ("RGB", "colour planes")
    h["BUNIT"] = ("relative", "frame values / full scale")
    h["EAESTACK"] = ("video", "EasyAstroEnhance stacking mode")
    hdu = fits.PrimaryHDU(data=np.ascontiguousarray(arr.astype(np.float32)), header=h)
    hdu.header.add_history(f"EasyAstroEnhance video stack {VIDEO_STACK_VERSION}: {report['frames_used']}/{report['frames_total']} "
                           "sharpest frames, phase-correlation alignment, mean.")
    hdu.writeto(path, overwrite=True, checksum=True)


def is_video(path: str | Path) -> bool:
    return bool(re.search(r"\.(avi)$", str(path), re.I))
