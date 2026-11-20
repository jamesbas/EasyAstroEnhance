"""Reference star colours from the Gaia BP-RP colour index (transformation version 1).

A documented, generic approximation, not camera-specific spectrophotometry (fidelity rule 6):

1. BP-RP -> effective temperature by interpolating log10(Teff) along the main-sequence table below (after Pecaut &
   Mamajek 2013, Gaia DR2/DR3 colour columns of E. Mamajek's "Modern Mean Dwarf Stellar Color and Effective Temperature
   Sequence"). Giants of the same colour are a little cooler; the error is small next to the gain tolerance.
2. A blackbody at that temperature is integrated through three Gaussian passbands that approximate a typical
   broadband colour sensor behind an IR-cut filter (centres 610 / 535 / 465 nm, FWHM 100 / 95 / 90 nm).
3. Ratios are normalized so that a G2V star (BP-RP 0.82, the Sun) is white: r/g = b/g = 1, the usual white reference
   of photometric colour calibration in amateur software.

Interstellar reddening is already part of the observed Gaia colour, as it is of the camera's view, so no
dereddening is applied. Stars outside BP-RP 0.0-2.5 or without a colour index are not used.
"""
from __future__ import annotations

import numpy as np

TRANSFORM_VERSION = 1
USABLE_BPRP = (0.0, 2.5)
WHITE_BPRP = 0.82  # G2V

# (BP-RP, Teff K) along the dwarf sequence
_SEQUENCE = np.array([
    (-0.36, 31400), (-0.17, 15700), (-0.07, 11400), (0.00, 9700), (0.20, 8100), (0.38, 7220), (0.59, 6510),
    (0.74, 5920), (0.82, 5770), (0.85, 5660), (0.98, 5270), (1.15, 4870), (1.43, 4440), (1.84, 3850), (2.22, 3560),
    (2.83, 3210), (3.25, 3060),
])
_BANDS = {"r": (610.0, 100.0), "g": (535.0, 95.0), "b": (465.0, 90.0)}
_WL = np.linspace(380.0, 720.0, 341)  # nm


def teff_from_bprp(bp_rp: np.ndarray) -> np.ndarray:
    c = np.clip(np.asarray(bp_rp, np.float64), _SEQUENCE[0, 0], _SEQUENCE[-1, 0])
    return 10 ** np.interp(c, _SEQUENCE[:, 0], np.log10(_SEQUENCE[:, 1]))


def _band_fluxes(teff: np.ndarray) -> np.ndarray:
    lam = _WL * 1e-9
    t = np.asarray(teff, np.float64)[:, None]
    planck = 1.0 / (lam**5 * (np.exp(np.minimum(1.4387769e-2 / (lam * t), 700.0)) - 1.0))
    out = []
    for c in "rgb":
        mu, fwhm = _BANDS[c]
        resp = np.exp(-0.5 * ((_WL - mu) / (fwhm / 2.3548)) ** 2)
        out.append((planck * resp * _WL).sum(axis=1))  # photon-counting: energy x wavelength
    return np.stack(out, axis=1)


_WHITE = _band_fluxes(teff_from_bprp(np.array([WHITE_BPRP])))[0]


def rgb_ratios(bp_rp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(r/g, b/g) relative to a G2V star, for each BP-RP value."""
    f = _band_fluxes(teff_from_bprp(bp_rp)) / _WHITE
    return f[:, 0] / f[:, 1], f[:, 2] / f[:, 1]


def usable(bp_rp: np.ndarray) -> np.ndarray:
    b = np.asarray(bp_rp, np.float64)
    return np.isfinite(b) & (b >= USABLE_BPRP[0]) & (b <= USABLE_BPRP[1])


METHOD = (f"Gaia BP-RP -> Teff (dwarf sequence) -> blackbody through generic broadband RGB passbands (610/535/465 nm), "
          f"white = G2V (BP-RP {WHITE_BPRP}); transformation version {TRANSFORM_VERSION}. Relative colour, not absolute "
          f"flux calibration or camera-specific spectrophotometry.")
