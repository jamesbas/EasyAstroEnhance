# Status: verified vs. not yet verified

Historical performance baselines: engine **1.2.0**, recipe schema **4** · measured on the target PC (Windows 11, Intel Core Ultra 9 285K,
64 GB RAM, NVIDIA GeForce RTX 5070 Ti 16 GB, driver 610.62 / CUDA 13.3, Python 3.12.10).

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

## Performance (tools/benchmark.py → docs/benchmarks.md, synthetic data, engine 1.6.0, Vivid preset)

| Image | CPU total | GPU total | GPU pixel group | Note |
|---|---|---|---|---|
| 2.1 MP rendered (Seestar-sized) | 3.8 s | 3.3 s | 0.28 s | was 8.7 s / 5.9 s before the phase 1 work |
| 8.3 MP rendered | 8.2 s | 5.8 s | 0.46 s | was 21.2 s / 10.1 s |
| 8.3 MP linear RGB | 12.6 s | 10.0 s | 0.59 s | engine 1.5: 11.1 s / 8.6 s (+cosmetic repair and fringe check); a display-only change on the real M31 stack: 4.0 s / 1.8 s |
| 21 MP linear RGB | 29.1 s | 19.6 s | 1.3 s | engine 1.5: 25.7 s / 16.1 s; peak RAM ≈ 6.4 GB |

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
  Optional offline catalog color uses relative RGB ratios, requires an existing celestial FITS solution and does not
  ship a reference catalog.
* Field-rotation borders are excluded from statistics but stay visible (never cropped automatically); Edit export's
  **Crop stacking edges** frames them out on request.
* Deconvolution is experimental (opt-in, Gaussian PSF, SNR-gated); validate on your own data before relying on it.
* ICC profiles on 16-bit TIFF are not applied (no precision-preserving conversion path); disclosed in the report.
* Previews/ROI tiles are rendered in a request thread pool (bounded, memory-mapped); all decoding/enhancement runs in the worker.
* Stacking: debayering is bilinear and resampling is bilinear (slight softening at 100 %; 2× drizzle is the sharper
  option with many frames). Registration is a similarity transform (no lens-distortion model). Frames from different
  cameras/filters are excluded, not merged. Small analysis tasks (for example background suggestions) wait while a stack
  runs because both share the single worker.
* AI tools: GraXpert models are CC BY-NC-SA 4.0 (non-commercial use). AI background extraction can darken the faintest
  outer halo of a frame-filling galaxy; AI star separation leaves very large saturated stars partly in the starless
  layer (they are added back unchanged). AI tools other than the three listed stay out of scope.
* Deferred by design: cubes, blind plate solving, absolute flux calibration, super-resolution, learned processing
  beyond the approved tools, installers, remote access. Approved in spec amendment 1.7 but **not yet implemented**
  (new features; the three existing AI tools above are implemented): header-WCS verification and hinted plate solving,
  built-in catalog colour, object annotations, a new AI sharpening tool, Star size and Starless/Stars layer exports.
* Swagger UI is disabled (it loads assets from a CDN); the OpenAPI schema is at `/api/v1/openapi.json`.
