"""Synthetic test field with known RGB ratios and a FITS sky solution."""
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

CATALOG_GAINS = np.array([1.35, 1, 0.72])


def color_test_files(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    h, w = 200, 240
    yy, xx = np.mgrid[:h, :w]
    rng = np.random.default_rng(42)
    field = rng.normal(100, 0.25, size=(h, w, 3))
    field += np.exp(-0.5 * ((xx - 121) ** 2 / 23**2 + (yy - 100) ** 2 / 12**2))[..., None] * [4, 17, 29]
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [120, 100]
    wcs.wcs.crval = [359.98, 30]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    header = wcs.to_header()
    header["ROWORDER"] = "BOTTOM-UP"
    rows = ["ra_deg,dec_deg,r_over_g,b_over_g"]
    for i, (x, y) in enumerate([(x, y) for x in (25, 68, 173, 215) for y in (22, 62, 137, 175)]):
        cr, cb = 0.65 + 0.07 * i, 1.55 - 0.06 * i
        peak = 38 + i * 0.5
        field += (peak * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 3.2))[..., None] * ([cr, 1, cb] / CATALOG_GAINS)
        ra, dec = wcs.all_pix2world(x, y, 0)
        rows.append(f"{float(ra):.12f},{float(dec):.12f},{cr},{cb}")
    field[100, 6, :] = 160  # isolated defect defines white point; not a valid photometry candidate
    files = {key: folder / name for key, name in (
        ("rgb", "solved-rgb.fits"), ("dualband", "dualband.fits"), ("broadband", "broadband.fits"),
        ("ha", "ha.fits"), ("oiii", "oiii.fits"), ("csv", "reference.csv"),
    )}
    rgb_header = header.copy()
    rgb_header["CTYPE3"] = "RGB"
    fits.writeto(files["rgb"], np.moveaxis(field.astype(np.float32), -1, 0), rgb_header, overwrite=True)
    rgb_header["INSTRUME"] = "Seestar S30"
    rgb_header["FILTER"] = "LP"
    fits.writeto(files["dualband"], np.moveaxis(field.astype(np.float32), -1, 0), rgb_header, overwrite=True)
    rgb_header["FILTER"] = "IR-CUT"
    fits.writeto(files["broadband"], np.moveaxis(field.astype(np.float32), -1, 0), rgb_header, overwrite=True)
    fits.writeto(files["ha"], field[..., 0].astype(np.float32), header, overwrite=True)
    fits.writeto(files["oiii"], field[..., 2].astype(np.float32), header, overwrite=True)
    files["csv"].write_text("\n".join(rows) + "\n", encoding="utf-8")
    return files
