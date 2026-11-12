# Status: verified vs. not yet verified

Engine 1.0.0 · recipe schema 2 · measured on the target PC (Windows 11, Intel Core Ultra 9 285K, 64 GB RAM,
NVIDIA GeForce RTX 5070 Ti 16 GB, driver 610.62 / CUDA 13.3, Python 3.12.10).

## Milestones

| # | Milestone | Gate | Result |
|---|---|---|---|
| 1 | Scaffold & contracts | Upload a JPEG, show its real thumbnail | **Passed** (API + Playwright; originals stored read-only, SHA-256 verified) |
| 2 | Rendered vertical slice | Real JPEG end to end; no-op and label tests pass | **Passed** on the user's two Seestar JPEGs; no-op PNG is pixel-exact; protected label pixels restored exactly |
| 3 | Precision & astronomy intake | Real uint16 TIFF and stacked FITS round trips | **Partially verified** – see below |
| 4 | Batch & resilience | Mixed batch with corrupt file and duplicate names | **Passed** (cancel, restart→interrupted, manual retry, idempotent request keys, ZIP) |
| 5 | Quality & polish | Release checklist on varied targets | **Partially verified** – features and tests done; visual review needs more real targets |
| 6 | GPU & handoff | Real GPU execution + CPU-only/failure paths | **Passed on the RTX 5070 Ti** (parity, tiling, OOM/device-failure fallback, CPU-only environment) |

## Real-file coverage

| Fixture (spec §11) | Status |
|---|---|
| User M33/M31/C12 Seestar JPEGs | 2 real JPEGs (M 31, C 12) processed, reviewed visually (`docs/visual-review/`, git-ignored). M33 JPEG not supplied. |
| **Real Seestar stacked RGB FITS** | **NOT PROVIDED – FITS support is not claimed complete for Seestar stacks.** |
| Real monochrome FITS | A real radio HI map (435×619, int32 + BSCALE/BZERO/BLANK, 82 307 blank pixels, WCS) passes the full API path in both "linear" and "already processed" states. It is not an optical stack. |
| Real high-bit TIFF | **NOT PROVIDED.** uint16/float32 TIFF verified with clearly labelled synthetic fixtures only. |
| Frame-filling nebula, sparse star field, already-stretched image, stack with a visible gradient | Not provided; only synthetic tests (planes + extended objects, sparse fields) exist. |
| Multi-plane cube (HST WFPC2) | Correctly refused with an explanation rather than guessed as RGB. |

Aesthetic acceptance is the user's judgement; tune strength tables after feedback (changing outputs requires a
`PIPELINE_VERSION` bump).

## Performance (tools/benchmark.py → docs/benchmarks.md, synthetic data, Brighter detail + local contrast)

| Image | CPU total | GPU total | GPU pixel group | Note |
|---|---|---|---|---|
| 2.1 MP rendered (Seestar-sized) | 4.2 s | 2.4 s | 0.12 s | target "≤15 s full processing for ~3 MP" met on CPU too |
| 8.3 MP rendered | 12.5 s | 4.4 s | 0.21 s | |
| 21 MP rendered | 29 s | 8.2 s | 0.62 s | |
| 21 MP linear RGB | 74 s | 18 s | 1.2 s | peak RAM ≈ 7.2 GB |

The GPU accelerates the pixel stages (16–40×); star detection, statistics and encoding stay on the CPU, so end-to-end
gain is 1.8–4×. Auto therefore uses the GPU from 2 MP (`EASYASTRO_GPU_THRESHOLD_PIXELS`). Cold start (CUDA/CuPy import,
context, kernel compile) happens once in the worker on the first GPU run or probe. A 100 MP linear RGB image would need
≈35 GB; the worker refuses up front when the estimate exceeds the RAM budget.

## Known limitations / not implemented

* Automatic caption (label) detection is not implemented; use "Does this image contain a label?" (draggable line) or
  Advanced rectangles. Text detection must never fabricate pixels, so it was left out of v1.
* Planar background uses a shared plane + per-channel constants only (independent channel planes are deferred).
* Star detection is conservative and CPU-only; on dense or very sparse fields it may be skipped (disclosed per run).
* Row flip for FITS display assumes bottom-up unless `ROWORDER=TOP-DOWN`; confirm with a real Seestar file.
* ICC profiles on 16-bit TIFF are not applied (no precision-preserving conversion path); disclosed in the report.
* Previews/ROI tiles are rendered in a request thread pool (bounded, memory-mapped); all decoding/enhancement runs in the worker.
* Deferred by design: calibration frames, stacking, debayering, cubes, plate solving, photometric calibration, higher-order
  gradients, deconvolution, star reduction/removal, narrowband palettes, installers, remote access.
* Swagger UI is disabled (it loads assets from a CDN); the OpenAPI schema is at `/api/v1/openapi.json`.
