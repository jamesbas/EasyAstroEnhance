# Test fixtures

No sample photographs are distributed with this repository (`samplepics/` is git-ignored and holds only files the
owner supplied locally; tests marked `realfiles` skip when it is absent).

All other test images (synthetic Gaussian-star fields, linear stacks, TIFF/FITS files, planes, ramps) are generated in
code at test time by `tests/conftest.py` and the individual tests. They are **synthetic test fixtures only** — never
shipped as example output and never used as content for any user's image.

The real files referenced by `realfiles` tests, if present:

| File | What it is | What it exercises |
|---|---|---|
| `Enhanced_*_M 31_*.JPG`, `Enhanced_*_C 12_*.JPG` | Seestar S30 enhanced JPEGs (user-supplied) | JPEG vertical slice, visual review |
| `M33_HI_25sec-peak.fits`, `-noise.fits` | Radio HI maps: 4-axis (435×619×1×1) int32 with BSCALE/BZERO/BLANK, WCS | real scaled mono FITS end-to-end, BLANK mask, degenerate axes |
| `hst-wfpc-II-800-800-4.fits` | HST WFPC2 4-plane float cube | cube intake guidance (never guessed as RGB) |

None of these is a Seestar stacked RGB FITS; that release-gate fixture is still outstanding.
