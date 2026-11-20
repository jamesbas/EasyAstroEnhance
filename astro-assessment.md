# EasyAstroEnhance — Code Assessment and Recommendations

Assessment date: November 20, 2026 · Code assessed: `main` at `902810c` (engine **1.5.0**, recipe schema **8**)
Scope: efficiency, performance and functionality (usability, completeness, and higher-end capabilities that could be
added without breaking the "one button" experience). **No code was changed for this assessment.**

---

## 0. How this assessment was done

| Activity | Detail |
|---|---|
| Code read | All of `backend/app/processing` (pipeline, stretch, linear prep, denoise, wavelets, finishing, deconvolution, star protection, color, masks, tiling, backends, AI tools, readers, export, stacking), the service layer (`services/`, `api/`, `db.py`), and the React frontend (`frontend/src`). |
| Specs read | [astro-photo-enhancer-app-spec.md](astro-photo-enhancer-app-spec.md) (amendments 1.3–1.6), [docs/STATUS.md](docs/STATUS.md), [docs/benchmarks.md](docs/benchmarks.md), [README.md](README.md). |
| Tests run | `uv run --frozen pytest -q` in `backend/` → **274 passed, 0 failed** (6 min 1 s). |
| Profiling on real data | Your Seestar stack `M 31\Stacked_232_M 31_30.0s_IRCUT_20261108-210941.fit` (3840 × 2160 RGB, 8.3 MP), Natural preset, CPU and GPU (RTX 5070 Ti), with `cProfile` and the pipeline's own stage timings. Also a Seestar S30 **LP** stack (`C 22\Stacked_1_C 22_20.0s_LP_…fit`) to check dual-band defaults. All source files were read-only. |

Everything labelled **measured** below comes from these runs. Estimates are labelled as estimates.

---

## 1. Executive summary

EasyAstroEnhance is a **well-engineered, unusually principled** application. The processing core is pure and testable,
precision is preserved end to end, every operation is disclosed with a reason, originals are immutable, and the
algorithms are modern and correct (an auto-solved hyperbolic/GHS-style stretch with highlight convergence, à trous
wavelet denoising gated by per-scale measured noise, robust polynomial gradient removal, bounded star-based white
balance, star-aware HDR and detail). The stacking engine (calibration, grading, triangle/RANSAC registration, kappa-sigma
rejection, Bayer drizzle) and the optional AI tools are solid. Test coverage is strong.

The main weaknesses are not in image quality but in **speed of iteration** and **friction before the first click**:

1. **The GPU is barely used, and the CPU path is effectively single-threaded.** On the real 8.3 MP M31 stack the GPU
   run took **15.3 s, of which the GPU pixel work was 0.66 s**; the other ~14.6 s is single-threaded CPU analysis and
   statistics. The CPU-only run took **30.5 s** on a 24-thread machine.
2. **Nothing is reused between runs.** Moving a display-only slider (Color, Contrast, Background, Stretch, Detail…)
   re-reads the file, redetects stars, refits the gradient, redenoises, and rewrites every export format. That is why
   there is a "Settings changed → Reprocess" step instead of live feedback.
3. **A Seestar FITS cannot be enhanced in one click.** Each Seestar stack asks *two* intake questions ("Are these
   red, green and blue channels?" and "How was this image saved?"), with no recommended answer, even though the
   header clearly identifies a Seestar linear stack.
4. **Seestar LP (dual-band) stacks get broadband defaults.** Star-based white balance assumes white stars, which is
   not valid for an Hα/OIII filter. On the real LP stack the red gain hit the **0.80 clamp** (Hα suppressed by 20 %) and
   SCNR green removal also ran.
5. **The main panel is dense** for a "one button" product: presets, six sliders, AI tools, manual sky regions, labels,
   tone, colour tools, label tool and Advanced all share one scroll area, and presets cannot be previewed.

### Top 10 recommendations (by value ÷ effort)

| # | Recommendation | Area | Impact | Effort |
|---|---|---|---|---|
| 1 | Cache the linear-stage result (`proc`, star mask, statistics, AI starless layer) per asset; rerun only the display stage when only display sliders change (§2.3 **E5**) | Performance/UX | Very high: display-only change ~1–2 s on GPU instead of ~15 s (estimate) | Medium |
| 2 | Multithread the CPU pixel groups (parallel tiles) and replace the NumPy-level à trous smoother with `scipy.ndimage.correlate1d` (**E2**) | Performance | High: CPU group A+B is 16 s of 30 s | Low–Medium |
| 3 | Compute global statistics and decision previews on a binned/strided proxy (**E3**, **E4**) | Performance | High on GPU runs (~5–7 s of analysis) | Low |
| 4 | Recommended intake answers for Seestar and EAE-stacked FITS (**U1**) | Usability | High: removes 2 blocking clicks per file | Low |
| 5 | Dual-band-aware defaults for Seestar LP stacks (**F1**) | Correctness | High for nebula users | Low |
| 6 | "Preview presets" thumbnail strip (**U3**) and an **Auto** preset chosen from measurements (**H1**) | Usability / one-button | High | Medium (cheap once #1 exists) |
| 7 | Simple/Full panel modes; rename confusing controls (**U2**, **U7**) | Usability | Medium–High | Low |
| 8 | Write only the viewer arrays + JPEG eagerly; render PNG/TIFF/FITS on first download; add run retention (**E7**) | Performance/disk | Medium (~3 s per run, hundreds of MB per run) | Low–Medium |
| 9 | Local plate solving + catalog colour calibration with a bundled catalog, enabling one-click accurate colour and object annotations (**H2**, **H3**) | High-end feature | High | High (now in spec amendment 1.7) |
| 10 | Opt-in AI sharpening and star reduction using the already-integrated Cosmic Clarity runtime (**H4**, **H5**) | High-end feature | High (most-requested by Seestar users) | Medium (now in spec amendment 1.7) |

---

## 2. Efficiency and performance

### 2.1 Measured profile (real Seestar M31 stack, 3840 × 2160 RGB, Natural)

| Stage | CPU run (s) | GPU run (s) | Notes |
|---|---:|---:|---|
| Read FITS | 0.15 | 0.15 | |
| Baseline frame (`prepare_linear_frame`) | 0.51 | 0.51 | done once per asset in the app |
| Edge mask | 0.70 | 0.70 | CPU |
| Star detection | 1.44 | 1.43 | Python loop per component |
| Noise estimate | 1.25 | 1.26 | full-resolution masked Gaussians |
| Gradient model | 0.26 | 0.27 | |
| White balance | 0.78 | 0.79 | |
| Wavelet noise (per-scale σ) | 2.66 | 2.65 | |
| **Pixel group A** (gradient, neutralize, WB, denoise) | **6.66** | **0.26** | |
| Display preview (full-res stretch, used only for statistics) | 1.18 | 1.20 | |
| Detail noise | 0.49 | 0.49 | |
| **Pixel group B** (stretch, star blend, HDR, pop, detail, colour) | **9.48** | **0.40** | |
| Untimed analysis (sky stats ×2, stretch statistics, clipped stats, masks, defect search…) | ~5.6 | ~5.9 | not in `stage_timings` |
| **Pipeline total** | **30.5** | **15.3** | |
| Exports written by the worker afterwards: PNG16 1.23, comparison 0.64, JPEG 0.33, TIFF16 0.30, FITS 0.29, + 2 `.npy` + SHA-256 of each | ~3+ | ~3+ | |

`cProfile` (CPU run) hot spots: `wavelets._smooth_axis` **5.3 s self-time** in 260 calls; `masks.masked_gaussian`
3.6 s; `stretch.apply_stretch` 3.6 s (3 calls); `linear_prep.clipped_stats` 3.25 s (9 calls); `sky_stats` 2.3 s (2 calls);
`denoise._shrink` 1.8 s; `finishing.detail_boost` 2.0 s; `detect_stars` 1.6 s.

**Interpretation.** The GPU speeds the pixel groups up ~25× (16.1 s → 0.66 s), but end-to-end only 2× because ~95 %
of a GPU run is CPU analysis that is (a) single-threaded and (b) computed at full resolution. On the CPU path, all
work is effectively single-threaded on a 24-thread processor.

### 2.2 Findings

**E1 — Analysis dominates GPU runs.** Measured above: 14.6 s of 15.3 s. This matches [docs/STATUS.md](docs/STATUS.md)
("the rest is CPU analysis"). The documented 1.8–4× end-to-end GPU gain is bounded by this, not by the GPU.

**E2 — The CPU pixel path is single-threaded, and the wavelet smoother is slow.**
[`_smooth_axis`](backend/app/processing/wavelets.py) pads a full copy and accumulates five shifted, scaled
slices with NumPy temporaries for every scale and axis (260 calls, 5.3 s). NumPy element-wise operations do not use
multiple cores, and [`run_tiled`](backend/app/processing/tiling.py) processes tiles sequentially (and on a 64 GB
machine the whole frame is one tile).

**E3 — Robust statistics are recomputed repeatedly at full resolution.**
[`clipped_stats`](backend/app/processing/linear_prep.py) runs up to 6 iterations of `np.median` over up to 4 M
float64 samples and is called 9 times; [`sky_stats`](backend/app/processing/linear_prep.py) is computed twice on
almost the same data (gradient pre-check at `pipeline.py:497` and neutralization at `pipeline.py:514`). Callers
pass `values[mask]`, so a full-size boolean-indexed copy is made *before* [`strided`](backend/app/processing/diagnostics.py)
subsamples it.

**E4 — Full-resolution renders used only for decisions.** The "display preview" at
[pipeline.py:700](backend/app/processing/pipeline.py) stretches the whole image (1.2 s) only to measure bright-core
fraction, green excess and detail noise — all of which are statistics that a 2×2- or 4×4-binned proxy would give to
well within their thresholds. `estimate_noise` runs full-frame masked Gaussians (1.25 s) for a single σ.

**E5 — No reuse of intermediate results.** Each enhancement calls `load_image` + `run_pipeline` from scratch
([`handle_enhance`](backend/app/services/worker.py)). The cache key only reuses a run when the *entire* recipe is
identical. Yet the expensive linear stage depends only on a subset of the recipe (`auto.*`, `background`,
`look.noise`, `advanced` denoise/deconvolution/gradient/WB fields, `ai.background/denoise/stars`, regions), while the
most-used sliders (`look.background/stretch/contrast/color/detail/protect_cores`, `tone.*`, object colour,
Hubble strength, star brightness) affect only analysis 2 + pixel group B. AI star separation (6–11 s on GPU, minutes on
CPU) is also recomputed every time.

**E6 — The clipping guardrail reruns all of group B.** When new clipping exceeds 0.1 %
([pipeline.py:774](backend/app/processing/pipeline.py)), the whole display stage is repeated at half strength. On CPU
that is another ~9.5 s. Clipping could be predicted on a proxy first.

**E7 — Every run eagerly writes every format.** [`handle_enhance`](backend/app/services/worker.py) writes PNG
(16-bit), TIFF (16-bit, zlib), JPEG, comparison JPEG, FITS (float, with checksum), `display.npy`,
`display_fixed.npy`, and hashes each file — about 3 s and, for an 8 MP linear stack, on the order of 250–300 MB per run
(estimate: PNG16 + TIFF16 ≈ 2 × 50 MB, FITS float32 ≈ 100 MB, two uint16 `.npy` ≈ 100 MB). There is no
retention policy, so experimenting with sliders fills the disk quickly.

**E8 — Star detection uses a per-component Python loop.**
[`detect_stars`](backend/app/processing/star_protection.py) iterates over up to 20,000 components, creating an
`np.mgrid` per candidate for the annulus test. 1.4 s on M31; dense fields (M45, clusters, Milky Way) will be slower.
The white-balance photometry loop ([`measure_star_fluxes`](backend/app/processing/linear_prep.py)) runs three
`binary_dilation`s per star for up to 3,000 stars.

**E9 — Peak memory is higher than necessary.** `run_pipeline` keeps `work`, `baseline`, `base`, `prepped`,
`grad_map`, `proc`, `disp_src`, `y0` and two output buffers alive together (the measured peak is ~160 bytes per
channel-pixel, 7.2 GB at 21 MP). Freeing `base`/`prepped` after group A, avoiding `work - offsets` copies and building
the gradient map in float32 would lower it. This matters for CPU-only laptops (16 GB) more than for the target PC.

**E10 — Full-image previews decode the entire array.** [`previews.render`](backend/app/services/previews.py)
converts the whole memory-mapped uint16 array to uint8 via a uint32 temporary before a LANCZOS resize to 2048 px.
Pre-decimating (integer-stride or `reduce`) before the resize, or writing the 2048 px preview once at publish time,
would make first paint faster and lighter.

**E11 — Minor service-layer items.** Several `async def` routes call the synchronous SQLite layer directly
(for example [`create_job`](backend/app/api/jobs.py)), which blocks the event loop briefly; declaring them as plain
`def` lets FastAPI run them in its thread pool. The single shared SQLite connection is guarded by an `RLock`
([db.py](backend/app/db.py)) — fine for one user.

### 2.3 Recommendations

| ID | Recommendation | Expected effect (estimate) | Fidelity impact |
|---|---|---|---|
| **E2a** | Implement the à trous step with `scipy.ndimage.correlate1d` (a dilated "holey" B3 kernel, `mode="reflect"`) on the CPU backend; keep the `xp` version for CuPy. | 2–4× faster wavelets on CPU | None (same math; existing tile/full-frame parity tests guard it) |
| **E2b** | Run CPU tiles in a `ThreadPoolExecutor` (NumPy/SciPy release the GIL); always tile the CPU path to ~1–2 K px tiles so that cores are used. Outputs are disjoint, statistics are already global. | 4–8× on group A/B on a multi-core CPU | None (halo logic already guarantees identical results) |
| **E3** | Compute luminance once; compute sky, noise, stretch statistics and clipped stats from a deterministic strided or 2×2-binned proxy; use index-strided sampling *before* boolean masking; cache `sky_stats` between the gradient check and neutralization. | 3–5 s saved per run | Negligible (statistics already use a 4 M subsample) |
| **E4** | Make bright-core detection, green excess and detail-noise estimation read a proxy stretch (e.g. 1/4 scale, with the sigmas scaled accordingly). | ~1.5 s per run | Negligible; record proxy scale in the report |
| **E5** | **Two-level cache in the worker:** (1) *linear stage* keyed by source SHA-256 + engine version + the linear-relevant recipe subset + regions/background + backend → `proc`, star masks, stat masks, sky/noise statistics, AI starless/star layers (memory LRU plus `.npy` memmap on disk); (2) *display stage* recomputed on demand. Disclose "linear stage reused from cache (key …)" in the report. | Display-only slider change: ~1–2 s GPU, ~3–5 s CPU after E2 | None if the cache key is complete; reports stay reproducible |
| **E6** | Predict the guardrail on a 1/4-scale proxy of group B before the full run; fall back to the current rerun only if the proxy is inconclusive. | Avoids a second full group B on clipped images | None (final check on full-res is kept) |
| **E7** | Eagerly write only `display.npy` (viewer), `display_fixed.npy`, JPEG, report and summary; render PNG/TIFF/FITS/comparison on first request and cache them (or write them in a background thread pool after the run is published). Add a retention setting ("keep the last N runs per image" / size cap) with a visible disk-usage readout in Settings. | ~2–3 s per run; large disk savings | None (exports are deterministic from stored arrays + report) |
| **E8** | Vectorize star measurement: compute area, peak, bounding box, second moments and mean per label with `ndimage.sum/maximum/mean` and `np.bincount`; apply the annulus test only to survivors; reuse one set of dilations for WB photometry. | 1–3 s on dense fields | None |
| **E9** | Release intermediates early, keep float32 throughout, and reuse output buffers between guardrail attempts. | 20–30 % lower peak RAM | None |
| **E10** | Store a 2048 px preview JPEG at publish time; decimate before resampling for ROI misses. | Faster first paint | None |
| **E11** | Convert DB-only `async def` routes to `def`; move upload disk writes to a thread. | Snappier UI under load | None |
| **E12** | Add a performance regression test (synthetic 8 MP linear, CPU) to the suite with a generous bound, and rerun `tools/benchmark.py` for engine 1.5 (the table in [docs/benchmarks.md](docs/benchmarks.md) is from engine 1.0). | Prevents regressions | None |

**Combined target (estimate):** a fresh Natural run on an 8 MP Seestar stack in **~5 s on GPU** and **~8–10 s on CPU**;
a display-only slider change in **~1–2 s**, fast enough for debounced live updates (see **U4**).

---

## 3. Robustness and code quality

Strengths: strict Pydantic recipes with migration, atomic publish of runs (`.partial` → rename), cooperative cancellation
between stages/tiles, interrupted-job recovery, classified GPU OOM/device failures with tile shrinking and CPU fallback,
same-origin + per-start token security, read-only originals with SHA-256, and 274 passing tests.

| ID | Observation | Recommendation |
|---|---|---|
| Q1 | [`run_pipeline`](backend/app/processing/pipeline.py) is a ~580-line function that mixes analysis, planning, execution, the guardrail and reporting. | Split into `analyse_linear()`, `plan_group_a()`, `display_decisions()`, `run_display_with_guardrail()`, `build_report()` returning small dataclasses. This is also the natural seam for the E5 cache. Keep behaviour identical (no `PIPELINE_VERSION` bump needed if outputs are bit-identical). |
| Q2 | Not all analysis time is recorded in `stage_timings` (~6 s untimed in the measured run). | Time sky stats, stretch statistics and defect search so the report explains where the time went. |
| Q3 | Job-eligibility checks happen before the transaction that creates the job, so two concurrent requests can both pass. | Move the check inside the `BEGIN IMMEDIATE` block (low risk for one user, but cheap). |
| Q4 | Upload size limit is enforced while streaming to disk, after multipart parsing. | Enforce `Content-Length` early and configure the multipart parser limit. |
| Q5 | Frontend: `App.tsx` is a large coordinator; the API client trusts responses via `as T` casts. | Generate TypeScript types from the OpenAPI schema (already served at `/api/v1/openapi.json`) or validate with a schema library; extract a `useJobs`/`useAssets` store. |
| Q6 | Enhancement progress is a stage label only (stacking has a fraction). | Report a fraction from stage count + tile index; show an ETA based on previous runs of similar size. |

---

## 4. Functionality — usability

### 4.1 What works well

Drag-and-drop multi-file intake with per-file failure reporting; six clearly hinted look sliders that map to documented
parameters; presets with save/rename/duplicate; divider, side-by-side and blink compare with 100 % zoom and
full-resolution ROI tiles; clipping overlay; batch "Enhance all"; ZIP export; Edit export (rotate, crop, caption, target
name from `OBJECT`); per-run processing reports; stacking with a progress banner and cancel.

### 4.2 Findings and recommendations

**U1 — Seestar FITS need two answers before anything can happen (verified on a real file).** A Seestar stack is
`rgb_planes` without `CTYPE3`, so the reader marks the layout undocumented
([fits.py](backend/app/processing/readers/fits.py) `_classify`) and asks *"Are these red, green and blue channels?"*;
[`evaluate_intake`](backend/app/processing/readers/__init__.py) then asks *"How was this image saved?"* with no
recommended option ([`question_state`](backend/app/processing/readers/common.py)). EAE's own stacks are already
pre-answered as linear ([queue.py](backend/app/services/queue.py)), but Seestar files are not.
*Recommendation:* show a **Recommended** answer with its evidence (e.g. `INSTRUME = Seestar S30`, 3 planes,
`STACKCNT`, 16-bit integer data with a ~1,500 ADU pedestal → "Linear stack, RGB"), pre-select it, and offer
**"Use recommended answers for all similar files"**. Optionally a Settings switch "Trust Seestar headers" that answers
automatically and records the evidence in the report. This keeps the spec's "confirm the state" rule (one explicit
click) while removing the friction.

**U2 — The main panel is dense for a one-button product.** Presets, six sliders, three AI switches, Manual sky regions,
Preserve labels, four tone sliders, Object/Catalog/Hubble/Focus colour tools, the label-line tool and Advanced share one
scrolling panel ([EnhancementPanel.tsx](frontend/src/components/EnhancementPanel.tsx)).
*Recommendation:* a **Simple** view by default — preset cards, the big **Enhance** button, and three sliders
(Sky brightness, Strength = stretch, Noise reduction) — with **More controls** revealing the rest, grouped into
*Look*, *Tools* (sky regions, labels, colour tools), *AI* and *Advanced*. Remember the user's choice.

**U3 — Presets cannot be previewed.** Users must pick a preset blind and wait for a full run.
*Recommendation:* **Preview presets** renders all six presets (and saved ones) as a thumbnail strip at ~512 px. With
the E5 linear-stage cache this costs only six display-stage runs on a proxy (well under a few seconds total on GPU,
estimate). Clicking a thumbnail selects the preset and enhances at full resolution.

**U4 — No live feedback after moving a slider.** A "Settings changed → Reprocess" badge appears and the user waits
15–30 s. *Recommendation:* once E5 exists, automatically (debounced ~400 ms) re-render the display stage for
display-only changes; keep the explicit button for linear-stage changes (noise, gradient, AI, deconvolution) and label
those controls with a small "slower" hint.

**U5 — Run history is a compare selector only.** *Recommendation:* add **Use these settings** on any past run
(restores its recipe — effectively undo/redo across runs), **Favourite** to mark the keeper, and short auto-names such
as "Vivid · Color 0.6 · 14:32".

**U6 — Terminology.** The *Background* slider (sky brightness) is easily confused with *Manual sky regions* and
*Neutralize the background*; *Keep stars small* (Advanced) actually means "gentler stretch inside the star mask" and its
own hint says it never shrinks stars ([recipe.ts](frontend/src/lib/recipe.ts)). *Recommendation:* rename to
**Sky brightness**, **Correct background from my sky samples**, **Gentler stretch on stars**; replace
"Fixed mapping" in the viewer with "Original stretch".

**U7 — Stacking requires pasting a folder path.** *Recommendation:* a folder picker (a small backend endpoint listing
drives/folders, restricted to read-only browsing) plus **Recent Seestar folders**: detect `MyWorks` and list `*_sub`
folders with frame counts and dates.

**U8 — Accessibility and keyboard.** Labels, live regions and dialog semantics are present, but drawing tools are
pointer-only, the hidden file input relies on its visible trigger, and only B/0/1 shortcuts exist.
*Recommendation:* keyboard alternatives for region drawing (arrow keys + Enter), shortcuts for Enhance (`E`),
next/previous image, and a shortcuts help (`?`).

**U9 — Long ZIP exports cannot be cancelled** (polls up to ~7 min in
[ExportMenu.tsx](frontend/src/components/ExportMenu.tsx)). Add Cancel and a progress fraction.

**U10 — Crop of stacking borders is manual.** The pipeline already measures low-coverage edges
([`edge_mask`](backend/app/processing/linear_prep.py)). *Recommendation:* in **Edit export…**, a one-click
**Crop stacking edges** that proposes the largest clean rectangle (user-initiated, so it satisfies fidelity rule 3).

---

## 5. Functionality — completeness for astrophotography enhancement

### 5.1 Capability map

| Workflow step | Status | Notes |
|---|---|---|
| Stacking subs (calibration, grading, registration, rejection) | ✅ | Strong. Bilinear debayer/resample (documented). |
| Multi-night stacking of stacks | ✅ | |
| 2× Bayer drizzle | ✅ | |
| Mosaic stacking (Seestar mosaic mode) | ❌ | Frames from different fields are excluded. |
| Comet stacking | ❌ | Niche. |
| Cosmetic correction (hot/cold/coloured single pixels) | ⚠️ | In stacking only; the single-stack enhance path only *protects* cold defects from denoising. |
| Banding / walking-noise reduction | ❌ | Common in undithered smart-telescope stacks. |
| Gradient / light-pollution removal | ✅ | Polynomial ≤ degree 3 + AI (GraXpert). No classical spline/RBF option. |
| Background neutralization | ✅ | |
| Colour calibration | ⚠️ | Star-based WB ✅; catalog calibration requires a user-made CSV — not one-button. Seestar stacks carry a WCS; EAE stacks do not, and nothing verifies or solves one. |
| Deconvolution / sharpening | ⚠️ | Opt-in Richardson–Lucy with Gaussian PSF, marked experimental. |
| Noise reduction | ✅ | Wavelet + AI. |
| Stretch | ✅ | Excellent: auto-solved hyperbolic stretch, highlight convergence, focus stretch. |
| HDR / core compression | ✅ | |
| Local contrast / structure | ✅ | Up to 64 px scale; no larger-scale structure enhancement. |
| Star stretch control / star brightness | ✅ | AI star separation with Star brightness (engine 1.5). |
| Star reduction (size) | ❌ | Not implemented; approved as opt-in **Star size** in spec amendment 1.7 (D). |
| Star colour enhancement | ❌ | Saturation is protected near white, so stars stay pale. |
| Chromatic halo / blue-purple fringe reduction | ❌ | |
| Narrowband palettes | ✅ | Hubble-style HOO from one LP stack; channel combine (RGB/LRGB/HOO/SHO/Ha-RGB). |
| Dual-band-aware defaults | ⚠️ | See **F1**. |
| Crop / rotate / caption | ✅ | Edit export. |
| Object annotation | ❌ | Not implemented; approved in spec amendment 1.7 (B). |
| Starless / stars layer export | ❌ | Not implemented; approved as on-request exports in spec amendment 1.7 (D). |
| Solar / lunar / planetary | ❌ | The Seestar shoots the Sun and Moon; no dedicated mode. |
| Batch processing | ✅ | Same recipe applied to many files. |
| Watch folder / import from telescope | ❌ | |

### 5.2 Functional findings

**F1 — Dual-band (Seestar LP) stacks get broadband defaults (verified).** `narrowband` is only true for EAE channel-mix
files (`EAEMIX`), and the filter is only inspected when Hubble-style or catalog colour is requested
([pipeline.py:400–401](backend/app/processing/pipeline.py)). On the real `C 22 … LP` stack the default Natural run
applied star white balance with factors **[0.80, 1.00, 1.03]** — the red gain at its clamp, i.e. the star-colour
assumption wanted to cut Hα by more than 20 % — and applied SCNR because a green excess of 0.0127 was measured. Through
an Hα/OIII filter, stars are not white, and average-neutral SCNR also pulls down OIII teal.
*Recommendation:* always classify the filter with the existing
[`hubble_input`](backend/app/processing/object_color.py); for dual-band inputs, skip star WB (or replace it with a
dual-band-specific balance, e.g. equalising the Hα and OIII sky-subtracted signal medians within a bounded range) and
skip or soften SCNR, with reasons in the report. This changes outputs, so bump `PIPELINE_VERSION` and visually review on
M42/C 22 LP stacks.

**F2 — Colour calibration is not one-button.** Catalog colour needs a hand-made CSV of linear RGB ratios. Seestar stacks
already carry a sky solution (`CTYPE1 = RA---TAN-SIP` with `CRVAL`/`CD` keywords, verified on the M31 and C 22 files),
but EasyAstroEnhance's own stacks and channel mixes keep only the `RA`/`DEC`/`FOCALLEN`/`XPIXSZ` hints, not a WCS.
In practice, users will only ever get star-based WB. See **H2**.

**F3 — Deconvolution is limited.** A single circular Gaussian PSF is a poor model for real star profiles (Moffat-like
wings), and the result is marked experimental. See **H4**.

**F4 — No cosmetic correction for single stacks.** Hot pixels that survive the Seestar's on-device stack (2–3 px
coloured specks) are too small for star detection (minimum area 3 px) and get stretched and saturated with everything
else. See **H7**.

---

## 6. Higher-end functions that keep "one button" simplicity

Each item is designed as either an automatic, measured decision behind Enhance or a single opt-in switch, disclosed in
the report like the existing stages. Items marked **(amendment)** conflict with the current spec text and need a
spec amendment in the style of 1.5/1.6; none of them introduce generative content, reference images or object-name-based
processing.

> **Update (November 20, 2026):** H2, H3, H4 (b), H5 and H15 are now specified in spec amendment 1.7 (parts A–D).
> The **(amendment)** notes below describe the spec as it stood at assessment time.

| ID | Feature | How it stays one-button | Fidelity / spec notes | Effort |
|---|---|---|---|---|
| **H1** | **Auto preset ("Smart Enhance")** — choose preset parameters from measurements: bright-core fraction (HDR), star density and extended-signal fraction (star field vs galaxy vs nebula), SNR (noise strength, stretch depth), filter (dual-band). | Default preset is *Auto*; the report says "Auto chose *Faint detail* because …". | Uses image statistics only, never the `OBJECT` name (rule 2). | Medium |
| **H2** | **Sky solution + catalog colour calibration.** Verify the Seestar header WCS against catalog stars; for EAE stacks and other files without one, solve offline from the `RA`/`DEC`/`FOCALLEN`/`XPIXSZ` hints, reusing the stacking triangle matcher. Ship a pinned, downloadable Gaia-derived colour catalog and feed the existing [`catalog_color`](backend/app/processing/catalog_color.py) path automatically. | One switch: **Accurate star colours**; falls back to star WB with a reason. | Numeric catalog data, not images (compatible with rule 2). Now specified in spec amendment 1.7 (A). | High |
| **H3** | **Object annotations in Edit export** — label Messier/NGC/IC objects and bright stars from the WCS (H2) on the separate sharing copy; optional north/east arrows and scale bar. | One checkbox in Edit export. | Overlay on a separate sharing copy only, like the existing caption (rule 3). Needs H2. | Medium |
| **H4** | **Sharpening.** (a) Classical: Richardson–Lucy with a measured **Moffat** PSF, 3×3 spatially varying PSF zones, total-variation regularization, deringing near stars — promote from "experimental". (b) **AI sharpening** with Cosmic Clarity *Sharpen* (MIT, same author and ONNX runtime path as the already integrated Dark Star), stellar and non-stellar strengths tied to the Detail slider. | One switch **Sharpen** (classical by default, AI if enabled). | (a) within amendment 1.3. (b) **(amendment)**: the spec currently excludes AI sharpening/deconvolution. Disclose model, SHA-256 and licence like the existing AI tools. | Medium |
| **H5** | **Star reduction (opt-in).** With AI star separation already producing a stars layer, apply a bounded morphological size reduction (or a reduced-scale re-stretch) to that layer before recombination. | A **Star size** slider shown next to Star brightness, default 100 %. | **(amendment)**: rule 8 forbids star-size reduction; amendment 1.6 already set the precedent for an explicit, disclosed, display-only star control. | Low–Medium |
| **H6** | **Star colour.** Saturate the separated star layer (or the star mask region) independently with a gamut-safe boost so stars are not washed white. | Automatic small boost in Vivid/Star field; a slider in More controls. | Saturation of existing colour; display-only. | Low |
| **H7** | **Cosmetic correction for single stacks** — detect isolated 1–3 px outliers per channel (sigma above a local median, not matching the PSF), replace with the same-colour local median; report the count. | Automatic stage, skipped with a reason when none are found. | Same method the stacking path already uses; replaced pixels are disclosed (like stacking's defect repair). | Low |
| **H8** | **Banding / walking-noise reduction** — row/column median-offset correction on linear data (Siril-style), gated by measured banding amplitude; a directional destriping in the wavelet domain for diagonal walking noise. | Automatic, skipped when no banding is measured. | Classical, linear, reversible offsets. | Medium |
| **H9** | **Classical spline/RBF gradient model** on an automatic sky grid (GraXpert's classical mode) as a middle ground between polynomial ≤3 and AI; plus independent per-channel planes (already listed as deferred). | Chosen automatically when the polynomial residual is large; Advanced override. | Classical, smooth model; same disclosure as today. | Medium |
| **H10** | **Large-scale structure** — a gated multiscale boost at 64–256 px (galaxy arms, nebula filaments) or noise-gated CLAHE on luminance. | Folded into the Contrast/Pop slider at higher values. | Bounded, monotonic per scale; disclosed. | Low–Medium |
| **H11** | **Halo / fringe reduction** — reduce blue/purple halos around bright stars by desaturating hues in a radial band around star masks. | Automatic when measured. | Display-only desaturation of existing colour. | Low |
| **H12** | **"Import from Seestar" one-click pipeline** — find `MyWorks` (local copy or the telescope's network share), group by target, show the newest stack and sub folders, and offer **Stack & Enhance** with the Auto preset. | The entire night becomes one click. | No processing change; read-only sources. | Medium |
| **H13** | **Moon/Sun mode** — a rendered-image preset with wavelet sharpening tuned for lunar/solar detail (Registax-style), limb-aware clipping guard, optional false-colour for H-α solar. Later: lucky-imaging stacking from Seestar planetary/solar videos. | One preset. | Classical. | Medium (video stacking: High) |
| **H14** | **Mosaic stacking** for Seestar mosaic mode (registration to a common WCS/canvas, seam-free background matching). | Detected automatically when frames cover different fields. | Classical; uncovered pixels stay NaN (as today). | High |
| **H15** | **Starless and stars layer exports** for users who continue in other tools. | Two extra items under More formats when star separation ran. | **(amendment)**: the spec lists star removal in final exports as deferred. | Low |

---

## 7. Suggested roadmap

**Phase 1 — quick wins (no output changes, no spec changes)**
E2a/E2b (CPU threading + faster wavelets), E3/E4 (proxy statistics), E7 (lazy exports + retention), E10, E11, Q2,
U1 (recommended intake answers), U6 (renames), U9. Rerun `tools/benchmark.py` and update [docs/benchmarks.md](docs/benchmarks.md).

> **Phase 1 status (November 20, 2026): done.** Pipeline outputs and every measured parameter are bit-for-bit
> unchanged (checked on real M31 IRCUT, M42 LP and JPEG files, CPU and GPU), so no `PIPELINE_VERSION` bump.
> Real M31 stack: CPU 30.6 s → 13.4 s, GPU 15.3 s → 9.9 s. Synthetic benchmark: 2.2–2.6× faster on CPU, 1.5–1.9× on GPU
> (see [docs/benchmarks.md](docs/benchmarks.md)). Backend 280 tests and Playwright 26 tests pass.
>
> * **E2a:** the à trous smoother accumulates in place and pads only the boundary bands (2.4× faster, identical values).
> * **E2b:** CPU pixel groups run on 8 threads over tiles (`EASYASTRO_CPU_THREADS` caps it). This exposed a latent bug:
>   tile halos used the *largest* chained filter footprint instead of the *sum*, so forced tiling (low RAM/VRAM) left
>   seam pixels up to 1e-7 different. Halos now add up, and tiled = full-frame exactly (new regression test).
> * **E3/E4, changed approach:** instead of proxy (downsampled) statistics, which would have changed measured values
>   slightly, statistics are made faster *exactly*: per-channel sky statistics, wavelet-noise sample tiles and the
>   decision preview run in parallel, and the noise estimate overlaps the gradient/color analysis. Proxy statistics
>   remain a phase 2 option that would need a `PIPELINE_VERSION` bump.
> * **E7:** exports and their SHA-256 are written in parallel; the 16-bit display TIFF is made on first download from
>   the stored display values (identical pixels; its hash is added to the run then); Settings → Storage shows disk use
>   and can keep only the newest N results per image (default: keep all; the current result is never removed).
>   PNG stays eager (primary download and publish validation).
> * **E10:** measured at ~0.2 s and dominated by JPEG encoding; only the full-size temporary was removed (same pixels).
> * **E11:** 34 await-free `async` routes became plain routes (thread pool); uploads are copied and hashed off the event loop.
> * **Q2:** sky/stretch statistics, defect search, bright-core and green-cast checks are now in `stage_timings`.
> * **U1:** header evidence (Seestar `INSTRUME`, `STACKCNT`/`NCOMBINE`, `BAYERPAT`, EAE keywords) gives a *Recommended*
>   answer with its reason; **Use recommended answers for all N files** confirms them in one click. Nothing is inferred
>   from pixel statistics, and the user still confirms.
> * **U6:** *Sky brightness*, *Correct background from my sky samples*, *Gentler stretch on stars*, *Original stretch*.
> * **U9:** Download all shows a progress bar and can be cancelled.

**Phase 2 — fast iteration and one-button polish**
E5 (linear-stage cache, built on Q1's refactor) → U4 (live display updates) → U3 (preset preview strip) → H1 (Auto
preset). Also U2 (Simple/Full panel), U5 (restore settings), U7 (folder picker), U10 (crop stacking edges).
Output-changing fixes in this phase, each with a `PIPELINE_VERSION` bump and visual review on your M31/M42/M45/C 22
stacks: **F1** (dual-band defaults), **H7** (cosmetic correction), H6, H11.

> **Phase 2 status (November 20, 2026): done — engine 1.6.0, recipe schema 9, spec amendment 1.8.** Backend 294 tests
> and Playwright 28 tests pass (new: `tests/unit/test_engine16.py`, preset-preview and folder-browse API tests,
> `frontend/tests/phase2.spec.ts`, browse step in `stacking.spec.ts`). CPU/GPU parity checked on real M31 IRCUT and
> C 22 LP stacks (same decisions; display difference ≤ 4.8e-4).
>
> * **Q1 + E5:** the pipeline is split into `prepare_linear_stage` and `finish_display`; the worker caches up to two
>   linear stages (≤ 20 % of RAM; never after a GPU fallback). Display-only change on the real M31 stack: **1.8 s GPU /
>   4.0 s CPU**, bit-identical to a fresh run. The refactor itself was verified bit-for-bit against engine 1.5 outputs.
> * **U4:** **Live preview** (default on) renders changed settings at full resolution, latest request wins, shown as
>   *Live preview (not saved)*; **Save this result** publishes exactly those pixels without recomputing.
> * **U3:** **Preview presets on this image** — quick looks of every built-in preset on a ~1 MP copy (cached; AI tools
>   omitted; labelled as reduced size); click to select.
> * **H1:** **Auto** is the default preset. Rules on four measurements (bright-core share, extended-signal share and
>   level, stars per MP), calibrated on 22 real targets; the choice and reasons appear above the sliders and in the
>   report. Moving a Look slider switches to Custom; other changes keep Auto.
> * **U2:** **Simple** (default, remembered) shows the preset, quick looks, Sky brightness, Stretch and Noise reduction,
>   plus a line naming hidden settings that are on; **All controls** shows everything.
> * **U5:** **Use these settings** beside the result history. **U7:** **Browse…** in Stack frames (read-only listing,
>   FITS counts, recent and sibling `…_sub` folders). **U10:** **Crop stacking edges** in Edit export (largest clean
>   window at the image's aspect ratio; on C 22 LP it keeps 98.4 % of the frame).
> * **F1:** recognized dual-band stacks skip star white balance and SCNR with the reason (neutralization and gradient
>   removal still run).
> * **H7, changed approach:** on real stacks every uncoloured isolated spike turned out to be a star centre, so only
>   *coloured* one-channel hot pixels and cold pixels on faint background are repaired (8 σ, isolated); monochrome images
>   get cold-pixel repair only.
> * **H6:** **Star color** Look slider (Vivid 0.3, Star field 0.5, others 0). **H11:** fringe reduction compares a
>   narrow ring around bright stars with a wider reference ring, so uniform nebulosity (M45) is left alone; on M31, M42,
>   C 22 LP/IR it is applied and deliberately subtle. Review sheets: `docs/visual-review/engine-1.6/` (git-ignored).
> * **Cost:** linear runs are ~1.4 s slower at 8.3 MP (cosmetic search and fringe check; see
>   [docs/benchmarks.md](docs/benchmarks.md)); rendered runs are unchanged. The cosmetic neighbour median could be
>   limited to candidate pixels in a later pass.

**Phase 3 — higher-end capabilities (spec amendment 1.7 now covers H2–H5 and H15)**
H2 + H3 (plate solve, accurate colour, annotations), H4 (classical sharpening upgrade, then optional AI sharpening),
H5 + H15 (star size, layer exports), H8/H9/H10 (banding, RBF gradients, large-scale structure), H12 (Seestar import),
then H13/H14 (Moon/Sun, mosaics).

> **Phase 3 status (November 20, 2026): done — engine 1.7.0, recipe schema 10, spec amendments 1.7 (implemented) and
> 1.9 (new: H8–H14).** Backend 311 tests and Playwright 32 tests pass (new: `tests/unit/test_engine17.py`,
> `tests/integration/test_reference_data_api.py`, layer and AI-sharpening tests in `test_ai.py`,
> `frontend/tests/phase3.spec.ts`). Everything below was checked on your real stacks in `D:\Seestar\MyWorks`.
>
> * **H2 sky solution:** offline, hinted (header pointing/scale, a typed name or coordinates; no blind solving), with
>   header-WCS verification. Star catalog: Gaia DR3 to G 13.5 (11.2 M stars, 135 MB), built reproducibly by
>   `backend/tools/build_star_catalog.py`, to be published as the data-only release `reference-data-1`; object catalog
>   OpenNGC. M 31, M 42, M 45 and C 22 solve in about 2 s at 0.4–0.55 px RMS. **H3:** **Accurate star colours** (one
>   switch) fits colour gains to the Gaia colours of the stars in the frame — consistent across your IRCUT targets and
>   with field-star white balance on M 31; Edit export gains **Label objects / Compass / Scale bar**.
> * **H4:** classical deconvolution now fits a Moffat PSF with TV regularization and deringing (one PSF per frame; zone
>   FWHM reported only); **AI sharpening** with the pinned Cosmic Clarity Sharpen models, SNR-gated (sky noise unchanged).
> * **H5 + H15:** **Star size** (M 31 median star FWHM 5.9 → 4.1 px at 70 %), centroid- and peak-preserving, display only;
>   **Starless / Stars** PNG and linear FITS layer exports on request. (H15 was not implemented before: star removal
>   existed only as the 0 % Star brightness display.)
> * **H8:** row/column banding repair, measurement-gated (left alone on all five real stacks). **H9:** a thin-plate spline
>   gradient model, automatic only on mostly empty fields (on M 31/M 42/M 45 it would have eaten nebulosity) or chosen in
>   Advanced. **H10:** large-scale structure on Contrast > 0.3 (Vivid), with a reduced negative lobe after review showed
>   the plain band darkening M 31's outer disk.
> * **H12:** **Import from Seestar** — finds MyWorks, lists targets newest first, **Add newest stack** in one click,
>   **Stack sub-frames / mosaic / video** pre-filled with automatic enhancement.
> * **H13:** **Moon & planets** preset (surface display mode, Moon disc colour balance, fine sharpening), chosen by Auto
>   for bright, starless discs and every video stack; **lucky-imaging stacking of RAW AVI videos** (lunar: 1495 frames →
>   374 used in 26 s). Your Jupiter recordings are over-exposed (42 % of the disc at full scale); the stack report now
>   says so — lower the gain when recording planets.
> * **H14:** **mosaic stacking** onto a canvas covering every panel, with chained registration and grading against
>   nearby pointings (Seestar mosaics have ~2 frames per panel): IC 1805 → 2713 × 3113, NGC 7000 → 1337 × 2150.
> * **Cost:** linear runs are ~1.2 s slower at 8.3 MP (banding check, large-scale band); optional tools cost time only
>   when on ([docs/benchmarks.md](docs/benchmarks.md)).
> * **Not done / limits:** blind solving, multi-point video alignment, MP4/SER video, mosaic seam blending, diagonal
>   banding, spatially varying deconvolution PSF.

---

## 8. Overall rating

| Dimension | Rating | Summary |
|---|---|---|
| Image-processing quality and correctness | ★★★★½ | Modern, measured, well-disclosed algorithms; one real default issue on dual-band data (F1). |
| Fidelity and reproducibility | ★★★★★ | Immutable originals, complete reports, versioned recipes, atomic publish. |
| Test coverage | ★★★★½ | 274 backend tests plus Playwright; add a performance regression check. |
| Performance on GPU | ★★★ | GPU kernels are fast but account for only ~4 % of the run; CPU analysis dominates. |
| Performance on CPU | ★★½ | Single-threaded on multi-core machines; ~30 s per 8 MP Natural run. |
| Iteration speed (UX) | ★★½ | Full rerun and full export set for every slider change. |
| One-button usability | ★★★ | Excellent defaults once a file is ready; two intake questions per Seestar FITS and a dense panel reduce it. |
| Feature completeness vs typical hobby workflows | ★★★½ | Covers the core pipeline; missing plate-solved colour, star reduction, sharpening beyond experimental RL, annotations and solar/lunar. |
