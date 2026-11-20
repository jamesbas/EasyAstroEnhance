# Status: verified vs. not yet verified

Historical performance baselines: engine **1.2.0**, recipe schema **4** · measured on the target PC (Windows 11, Intel Core Ultra 9 285K,
64 GB RAM, NVIDIA GeForce RTX 5070 Ti 16 GB, driver 610.62 / CUDA 13.3, Python 3.12.10).

## Engine 1.7 — higher-end capabilities (spec amendments 1.7 and 1.9)

| Item | Result |
|---|---|
| Star catalog | Gaia DR3, G < 13.5: 11 193 267 stars, 134.7 MB (SHA-256 `81f828a1…`); no empty 1° cell anywhere on the sky (minimum 33 stars), 75 stars within 0.6° even at the north galactic pole. Built by `backend/tools/build_star_catalog.py`. |
| Sky solution | Real Seestar stacks M 31, M 42, M 45, C 22: header WCS verified (182–192 matches, 0.73–1.34 px); with the WCS removed, solved from header hints in 1.9–2.5 s at 0.42–0.55 px RMS, within 1–11″ of the header solution. |
| Accurate star colours | M 31, M 45 and a 4-frame C 22 (S30 IRCUT): gains R 0.76–0.81, B 1.15–1.17 — consistent across targets — and within 0.03 of field-star white balance on M 31; M 42 LP correctly refused (dual-band). |
| AI sharpening | Cosmic Clarity Sharpen on M 31 via DirectML ≈ 12 s, sky noise unchanged (SNR gate). |
| Star size | M 31: median separated-star FWHM 5.9 px → 4.1 px (70 %) → 2.8 px (50 %); centroids and peaks kept (unit tests). |
| Banding, spline gradient | Banding skipped on all five real stacks (no banding above noise); synthetic read-out banding removed. The spline model is not chosen automatically on M 31, M 42 or M 45 (it would follow nebulosity). |
| Large-scale structure (Vivid) | Reviewed on M 31 and M 42: slightly less core glare and crisper dust lanes; the first version darkened M 31's outer disk, so only a quarter of the band's negative lobe is applied. |
| Moon & planets | A 1495-frame lunar RAW video stacked (374 frames, 26 s) and Auto chose Moon & planets: black sky, neutral disc, no clipping. Jupiter (1581 frames, 264 × 480 ROI) stacks in 5 s; the recording itself is over-exposed (42 % of the disc at full scale), which the stack report now flags. |
| Mosaics | NGC 7000 (6 subs, 2 panels) → 1337 × 2150 in 5 s; IC 1805 (84 subs, 41 panels of ~2 frames) → 52 frames used, 2713 × 3113 in 50 s, no visible seams; cloudy late frames rejected against nearby pointings and the session. |
| GPU memory | The three AI tools' DirectML sessions held 5.1 GB of GPU memory indefinitely; the worker now releases them after 60 s idle (measured: 5.5 GB → 0.37 GB, the runtime's own context). Reload costs ≈ 3 s on a 40 s AI run. |
| Fixes from testing | Star color with AI star separation failed on the GPU only (CuPy `clip` on a scalar mask) — fixed, GPU parity test added; a failed live preview's error object blanked the page — fixed, plus an app-level error boundary; Edit export's preview overlapped its controls in short windows — fixed (browser test); every run with Accurate star colours applied failed while writing the FITS history (it expected a CSV hash) — fixed, and the full app path (import, solve, all AI tools, every export, annotations, live preview) verified on the real M 101 stack. |
| Import from Seestar | Real MyWorks folder (55 targets) listed in 0.04 s from names only; browser test adds a stack and opens a pre-filled sub-frame stack. |
| Tests | Backend 311 (new: `tests/unit/test_engine17.py`, reference-data API, layer and AI-sharpening tests in `test_ai.py`); Playwright 32 (new `phase3.spec.ts`). |

Not verified: blind or JPEG-only sky solving on real data (typed name path is unit-level only), annotations drawn on real
solved images in the browser (rendering verified in Python), Sun videos (the Solar folder is empty), SER videos.

## Engine 1.6 — one-button polish and output fixes (spec amendment 1.8)

| Item | Result |
|---|---|
| Auto preset (default) | Calibrated on 22 real Seestar targets: M31, M42 → Bright core; NGC 7000, IC 1805, NGC 2237, IC 1318, IC 2574, M101, M33, M81, M17, M27, M45, NGC 7023, IC 434, M78 → Faint detail; C 22 IRCUT → Star field; M13, M51, NGC 281, Veil, NGC 2903 and a one-frame C 22 LP stack → Natural. Measuring takes 0.3–0.8 s. |
| Cosmetic correction | On real stacks every uncoloured isolated spike was a star centre, so only coloured hot pixels and cold pixels are repaired (8 σ, isolated, faint background). Unit tests cover the white-spike, bright-structure, protected and monochrome cases. |
| Dual-band defaults (F1) | Seestar LP stacks (M42 LP, C 22 LP) skip star white balance and green removal with the reason; IRCUT stacks unchanged. |
| Star colour, fringe reduction | Visual review sheets on M31, M42 LP, M45, C 22 LP and C 22 IRCUT (full frame + bright-star crops, engine 1.5 vs 1.6) in `docs/visual-review/engine-1.6/` (git-ignored). Fringe reduction ran on M31, M42, C 22 LP and C 22 IR; it was skipped on M45 because the reflection nebula colours the reference ring equally. The effect is deliberately subtle. |
| Linear-stage cache | A display-only change on the 8.3 MP M31 stack: 1.8 s GPU / 4.0 s CPU (full run ≈ 10 s / 13 s); the result is bit-identical to a fresh run (unit test + live-preview integration test). |
| Live preview, quick looks, Simple panel, restore settings, folder browsing, crop suggestion | Browser tests (`phase2.spec.ts`, `stacking.spec.ts`) and API tests pass; Crop stacking edges on the real C 22 LP stack keeps 98.4 % of the frame inside the clean area (M31: no crop needed). |
| GPU parity | Vivid on real M31 IRCUT and C 22 LP stacks, CPU vs GPU pixel groups: the same applied/skipped decisions for cosmetic, white balance, green removal, star colour and fringe reduction; display max difference 1.3e-5 (M31) and 4.8e-4 (C 22 LP), no pixel differs by one 8-bit step. |

Not verified: Auto on rendered JPEGs other than the Seestar M31 JPG (chose Bright core).

## Engine 1.3 — optional color workflow

The CPU checks cover selective hue changes with star, sky and protected-region masking; the manual focus
curve's monotonicity and sky anchor; catalog RGB gain recovery and fallback on synthetic solved FITS; channel
assignment, WCS alignment across different grid sizes, source SHA-256 preservation and publication as a new
linear FITS. Browser tests exercise the live color mask, local catalog import, focused stretch and HOO workflow.
On a real Seestar M31 stack, the Object Color and Manual focus previews were reviewed at fit and 100%;
both left the processed-linear array identical to the automatic run, and the original file hash was unchanged.
Real reference-star/dual-band datasets and GPU execution of the new controls were not used for these tests.

Engine 1.3.1: visually reviewed the single-stack Hubble-style palette on a real Seestar M42 LP stack. The
two renders used the same linear pipeline, the processed-linear arrays were pixel-identical and the original's
SHA-256 was unchanged. CPU tests also verify bright-star/sky masking, the IR-cut guard, per-file confirmation,
and the one-click browser action. GPU parity for the new palette was not tested.

## Engine 1.1 (improve-enhance.md, section 8) — verified on real Seestar stacks

| Item | Result |
|---|---|
| Seestar row order (P0-1) | Stacked FITS kept as stored; correlation with the telescope's JPG 0.98 (was 0.49 flipped). Test: `test_real_seestar_stack_one_button_acceptance`. |
| Neutral sky / target level (P0-2, P0-3) | M31 (S30 Pro 4K and 1080p), M45 and M42 (LP): sky channel spread < 0.01, sky at the preset level (Natural 0.12 ± 0.003). |
| Clipping guardrail (P0-4) | Did not fire in any run (all six presets on M31 1080p; Natural, Vivid, Bright core on M31 4K; Natural, Bright core on M42; Natural on M45). Engine 1.0 flagged every Seestar run. |
| Star cores (P0-5) | Highlight convergence: saturated cores white, no grey discs or dark rings (synthetic radial-profile test). |
| One button, presets, sliders (P1-6, P1-7) | Six presets, six sliders + Protect bright cores, auto-solved stretch; Playwright suite passes (18/18). |
| White balance, SCNR, pop, saturation, gradient, denoise, edges (P1-8…14) | Implemented with skip reasons; unit tests in `tests/unit/test_one_button.py`. |
| HDR cores, multiscale detail, deconvolution, star stretch (P2-15…18) | Implemented; deconvolution is opt-in (Advanced) and marked experimental. |

Timings for an 8.3 MP Seestar S30 stack (Natural, engine 1.5.0 after the phase 1 performance work): CPU ≈ 13 s (was ≈ 31 s);
GPU ≈ 10 s (was ≈ 15 s). The GPU pixel groups take about 0.3–0.4 s each after warm-up; the rest is CPU analysis (stars,
edge mask, sky and noise statistics, white balance, stretch solve), now partly parallel. The first GPU run includes CUDA start-up.

Visual acceptance is the user's judgement. Tuning constants (stretch target 0.88, HDR threshold, detail edge roll-off,
white-balance limit) are documented in the code and the processing report; changing them requires a `PIPELINE_VERSION` bump.

## Optional AI tools (spec amendment 1.5) — verified on real Seestar data

| Item | Result |
|---|---|
| Runtime | ONNX Runtime DirectML 1.24.4 on the RTX 5070 Ti; all four pinned models load and run on the GPU, with CPU fallback on failure (tested). |
| Speed (8.3 MP M31 stack, GPU) | Background 1.5 s, denoise 16–17 s, star separation 6–11 s. 2 MP M31 through the app: 0.8 s / 6.2 s / 2.9 s, about 18.5 s per job. |
| AI noise reduction | Colour mottle in M31 sky reduced 2.5× (5.0 → 2.0 display units); fine luminance grain about 21% below full-strength wavelet denoise at an equal stretch; star and core peaks kept (above 250 MAD unchanged). |
| AI star separation | Starless + stars equals the input exactly. M31's core stays in the starless layer: flattening before inference plus an extended-structure gate. Without them, Dark Star punched a hole in the bulge (found and fixed during review). |
| AI background extraction | Removes an added linear gradient to below 30% of its strength on the real M31 stack (test). On your 360-frame M31 stack it slightly darkens the faintest outer halo. |
| Stretch safeguard | AI-denoised sky made the auto-stretch solver choose D ≈ 3,600 (all tools: 217,000) vs 384 classical, amplifying colour mottle. AI-denoised data now count as at most 2× cleaner: D 834 / 1,214. |
| Visual review | Your `M 31 - stacked 360 frames` with your settings (Faint detail, noise 1.0): clearer dust lanes and arm HII regions, smoother sky, smaller stars at the same look. |
| Tests | `tests/unit/test_ai.py` (synthetic ONNX models: exact tiling, normalization round-trips, pass-through, stretch inversion, gating, fallback, pipeline wiring, noise floor, migration; 4 real-model tests), `tests/integration/test_ai_api.py` (verified download, corrupted file rejected, delete, preset migration), `frontend/tests/ai.spec.ts`. |

Not yet verified: AI tools on nebula stacks (M42/M45) and on mono FITS through the full app (unit-tested only); the
non-Windows CUDA provider path.

## Stacking (spec amendment 1.4) — verified on real Seestar sub-frames

| Item | Result |
|---|---|
| Raw subs, `D:\Seestar\MyWorks\M 42_sub` (77 × 30 s, Seestar S30, GRBG 1080 × 1920) | 65 frames used; 12 skipped with reasons (11 at the end of the session as clouds arrived — star counts fell from 160 to 14 — and one with bloated stars). Alignment 0.40 px RMS median over 10° of field rotation; 906 fixed hot/cold pixels repaired; ≈ 0.8 % of samples rejected (kappa 3); 19 s native (streaming two-pass rejection), 105 s with 2× drizzle (2160 × 3840; 0.03 % of output pixels filled from the native stack). Same orientation and framing as the telescope's own 77-frame stack; with an identical display stretch it shows more faint stars and nebulosity. |
| Synthetic acceptance (`tests/unit/test_stacking.py`) | Rotation/shift recovered to < 0.05° / 0.3 px; satellite trail and hot pixels removed; noise falls ≈ √N; cloudy frame rejected with a reason; darks + flats calibrate (vignetting removed); 2× drizzle; streaming path matches the in-memory path; GPU matches CPU; merging three nights. |
| API / UI (`tests/integration/test_stacking_api.py`, `frontend/tests/stacking.spec.ts`) | Scan validation, idempotent create, new linear image is `ready` and **not** enhanced by default, auto-enhance creates exactly one job when ticked, cancel/retry, history clear, source folder unchanged. |

Not yet verified on real data: darks/flats from a real camera (the Seestar does not save them by default) and merging real stacks from several nights (synthetic tests only).

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
| **Real Seestar stacked RGB FITS** | **PROVIDED and verified** (M31 ×2, M45, M42 from `D:\Seestar\MyWorks`, read-only): orientation, neutral sky, targets and guardrail checked by a `realfiles` test. |
| Real monochrome FITS | A real radio HI map (435×619, int32 + BSCALE/BZERO/BLANK, 82 307 blank pixels, WCS) passes the full API path in both "linear" and "already processed" states. It is not an optical stack. |
| Real high-bit TIFF | **NOT PROVIDED.** uint16/float32 TIFF verified with clearly labelled synthetic fixtures only. |
| Frame-filling nebula, sparse star field, already-stretched image, stack with a visible gradient | Real: M42 (extended emission nebula, LP filter), M45 (dense star field + reflection nebula), Seestar JPGs (already stretched); all four Seestar stacks had measurable gradients (2–4× pixel noise) that the automatic model removed. Frame-filling skip path covered by synthetic tests. |
| Multi-plane cube (HST WFPC2) | Correctly refused with an explanation rather than guessed as RGB. |

Aesthetic acceptance is the user's judgement; tune strength tables after feedback (changing outputs requires a
`PIPELINE_VERSION` bump).

## Performance (tools/benchmark.py → docs/benchmarks.md, synthetic data, engine 1.7.0, Vivid preset)

| Image | CPU total | GPU total | GPU pixel group | Note |
|---|---|---|---|---|
| 2.1 MP rendered (Seestar-sized) | 3.8 s | 3.3 s | 0.24 s | was 8.7 s / 5.9 s before the phase 1 work |
| 8.3 MP rendered | 8.5 s | 6.1 s | 0.48 s | was 21.2 s / 10.1 s |
| 8.3 MP linear RGB | 13.8 s | 11.2 s | 0.61 s | engine 1.6: 12.6 s / 10.0 s (+banding check, large-scale band); a display-only change on the real M31 stack: 4.0 s / 1.8 s |
| 21 MP linear RGB | 32.0 s | 22.2 s | 1.3 s | engine 1.6: 29.1 s / 19.6 s; peak RAM ≈ 6.4 GB |

CPU pixel groups use up to 8 threads on overlapping tiles (`EASYASTRO_CPU_THREADS` caps it); the results are
bit-for-bit identical to a single full-frame pass, and the speed-ups changed no output pixel or measured parameter
(verified on real Seestar M31, M42 LP and JPEG files on CPU and GPU). The GPU accelerates the pixel stages (16–40×);
star detection, statistics and encoding stay on the CPU, so end-to-end
gain is 1.3–1.6×. Auto therefore uses the GPU from 2 MP (`EASYASTRO_GPU_THRESHOLD_PIXELS`). Cold start (CUDA/CuPy import,
context, kernel compile) happens once in the worker on the first GPU run or probe. A 100 MP linear RGB image would need
≈35 GB; the worker refuses up front when the estimate exceeds the RAM budget.

## Known limitations / not implemented

* Automatic caption (label) detection is not implemented; use "Does this image contain a label?" (draggable line) or
  Advanced rectangles. Text detection must never fabricate pixels, so it was left out of v1.
* Planar background uses a shared plane + per-channel constants only (independent channel planes are deferred).
* Star detection is conservative and CPU-only; on dense or very sparse fields it may be skipped (disclosed per run).
* FITS rows are treated as bottom-up unless `ROWORDER` says otherwise; ZWO Seestar files without `ROWORDER` are kept as
  stored (verified against the telescope's JPG). Assets prepared by engine 1.0 are re-prepared once at start-up; their
  label rectangles and sky samples are cleared if the display orientation changed.
* Default white balance assumes the typical isolated field star is white. It is not photometric calibration.
  Accurate star colours (built-in Gaia catalog) and imported catalogs fit relative RGB gains through a generic passband
  model — not camera-specific spectrophotometry. Sky solving needs pointing hints (FITS header, a typed name or
  coordinates); blind solving is not implemented.
* Field-rotation borders are excluded from statistics but stay visible (never cropped automatically); Edit export's
  **Crop stacking edges** frames them out on request.
* Deconvolution (opt-in) uses one Moffat PSF for the whole frame; the 3 × 3 zone FWHM is reported but not used to vary
  the PSF across the field. AI sharpening, when enabled, replaces it.
* Video stacking aligns whole frames (no multi-point alignment), so a planet that warps in poor seeing is averaged as
  recorded; over-exposed recordings are flagged, not repaired. MP4 and SER files are not read. Mosaic panels are
  levelled by background offsets only (no seam blending); banding repair handles rows and columns, not diagonal
  patterns.
* ICC profiles on 16-bit TIFF are not applied (no precision-preserving conversion path); disclosed in the report.
* Previews/ROI tiles are rendered in a request thread pool (bounded, memory-mapped); all decoding/enhancement runs in the worker.
* Stacking: debayering is bilinear and resampling is bilinear (slight softening at 100 %; 2× drizzle is the sharper
  option with many frames). Registration is a similarity transform (no lens-distortion model). Frames from different
  cameras/filters are excluded, not merged. Small analysis tasks (for example background suggestions) wait while a stack
  runs because both share the single worker.
* AI tools: GraXpert models are CC BY-NC-SA 4.0 (non-commercial use). AI background extraction can darken the faintest
  outer halo of a frame-filling galaxy; AI star separation leaves very large saturated stars partly in the starless
  layer (they are added back unchanged). AI tools other than the four listed stay out of scope.
* Deferred by design: cubes, blind plate solving, absolute flux calibration, super-resolution, learned processing
  beyond the approved tools, installers, remote access.
* Swagger UI is disabled (it loads assets from a CDN); the OpenAPI schema is at `/api/v1/openapi.json`.
