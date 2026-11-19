# EasyAstroEnhance — Application Development Specification

Version 1.5 • November 15, 2026 • Prepared for Jaime Basilico

> **Amendment 1.5 (optional AI tools; revises decision D1).** At the user's request, three opt-in learned tools are
> added (engine 1.2.0, recipe schema 4): **AI background extraction** (GraXpert background model), **AI noise reduction**
> (GraXpert denoising model) and **AI star separation** (Cosmic Clarity Dark Star; the stars are always added back). They
> are image-to-image restoration networks run locally through ONNX Runtime (DirectML GPU on Windows, CPU fallback) — no
> prompts, no reference images, no text-to-image generation, no cloud. All are off by default and in every built-in
> preset; each replaces one classical step, is skipped with a reason (classical step used) when its model is missing or
> cannot run, and is disclosed per run with the model file, version, SHA-256, licence and execution provider. Models
> are pinned (fixed URL + SHA-256) and downloaded only when the user asks. Fidelity rules 1 and 8 are amended; see §4
> "Version 1.3 — optional AI tools".

> **Amendment 1.4 (stacking).** At the user's request the app can now stack: raw sub-frames from a folder (for example a
> Seestar `…_sub` folder) with optional darks/flats/bias/dark-flats, and already stacked images of one target from several
> nights. Stacking is a separate, explicit action ("Stack frames…"); it creates a new linear FITS image in the app and
> enhances it only when the user ticked **Enhance automatically when stacking finishes** (default off, so settings can be
> adjusted first). See §4 "Version 1.2 — stacking". Sections 1, 4 and 6 are amended; superseded text is marked.

> **Amendment 1.3 (engine 1.1, one-button Enhance).** Adopts the decisions D1–D4 of [improve-enhance.md](improve-enhance.md) §2.5:
> D1 — learned/AI processing stays excluded; D2 — an opt-in, SNR-gated deconvolution and a noise/edge-gated multiscale
> "Detail" stage are allowed (star removal and star-size reduction stay disabled); D3 — background neutralization, low-order
> gradient removal and a bounded star-based white balance run automatically, skip with a reason and can be switched off;
> D4 — ZWO Seestar FITS keep their stored (top-down) row order so results match the telescope's JPG. Sections 2, 3, 4, 6 and 8
> are amended accordingly; superseded text is marked.

## 1. Product outcome

Build a small local application that enhances real telescope photographs through conventional numerical image processing. The primary user owns a ZWO Seestar S30 and photographs galaxies and nebulae. The ordinary flow is: add one or more files, choose enhancements, click Enhance, compare before and after, download results. Support JPEG, TIFF and stacked FITS. Processing must derive exclusively from the uploaded pixels.

This is a specification for implementation in Visual Studio Code with GitHub Copilot. It is not an already implemented application. No ChatGPT subscription, model inference, API key or paid astronomy software is required; an NVIDIA GPU is optional and used for acceleration when compatible. No GPU is required to run the proposed app. Internet is required for initial dependency installation, not for ordinary operation.

### Defaults and assumptions

- Windows 11 is the primary development and user platform; keep the Python core portable.
- Run a Python service on localhost and open the UI in the user's browser.
- Single user, local disk, sequential batch processing. Prefer optional NVIDIA GPU acceleration for eligible workloads, with a complete CPU fallback. Primary GPU target: the user’s NVIDIA GeForce RTX 5070 Ti with 16 GB VRAM; verify installed device capabilities at runtime.
- Each uploaded image is processed independently. Selecting ten exposures does not stack them. *(Amended 1.4: stacking is a separate "Stack frames…" action on a folder.)*
- The Seestar already performs stacking and produces FITS. Treat the telescope-produced integrated/stacked RGB or monochrome image as the primary FITS input; ~~do not add a stacking workflow~~ *(amended 1.4: an optional stacking workflow exists, see §4)*. The preferred FITS input is an integrated/stacked RGB or monochrome image. Individual raw exposures, CFA mosaics and ambiguous multidimensional data receive explanatory intake guidance.
- Start with a conservative Natural preset. Advanced controls remain collapsed.
- Work from immutable originals; every adjustment starts from the source, not an earlier export.

## 2. Fidelity requirements

These are release requirements, not optional marketing promises:

1. Never call an image-generation service, diffusion model, generative fill, learned reconstruction, synthetic-star tool, super-resolution model or external image repository. *(Amended 1.5: the three opt-in AI tools of §4 "Version 1.3" — learned background extraction, denoising and star separation run locally on the image's own pixels — are the only permitted learned processing; they are off by default and disclosed per run. Text-to-image, diffusion, generative fill, super-resolution and reference images remain forbidden.)*
2. Do not substitute reference photographs of the named object or use object identity to invent its appearance.
3. Preserve field of view, dimensions, star coordinates, orientation and existing structures. Apply EXIF orientation once and document it. Do not crop, rotate, resize or remove stars automatically.
4. Preserve originals byte-for-byte. Processing changes pixels; avoid claiming that every output pixel is an original measured value or that filtering guarantees preservation of all faint signal.
5. Keep edits reproducible with source SHA-256, pipeline version, algorithm settings, resolved per-file parameters and dependency versions.
6. Distinguish display enhancement from scientific calibration. Background neutralization and star-based white balance are not photometric color calibration; a sharper appearance is not additional measured resolution. Optional offline catalog color uses user-provided numerical RGB reference-star ratios on solved broadband FITS. This is relative color calibration, not reference-image processing or absolute flux calibration.
7. Preserve burned-in telescope labels using explicit protected regions. Never reconstruct sky behind lettering.
8. Star removal and star-size reduction stay disabled. *(Amended 1.5: AI star separation splits stars from the background only so each is processed appropriately; the stars are always added back and no output is starless.)* *(Amended 1.3:)* Deconvolution is available only as an opt-in Advanced option on linear stacks (star-measured PSF, damped, SNR-gated, star cores excluded); the multiscale Detail stage is noise- and edge-gated and bounded. Both are disclosed per run.
9. Report applied, reduced and skipped operations per image. Never silently claim success for an unsupported operation.

## 3. Current skill audit and migration boundary

The existing `enhance-astrophotos` skill and its `scripts/enhance.py` were reviewed for this specification. The skill describes fidelity rules and multiple input types, but the actual helper accepts only Pillow RGB images rendered as 8-bit arrays. Its demonstrated use was the user's M33 JPEG. FITS and high-bit-depth TIFF processing have not been validated by that helper.

The helper performs:

- EXIF orientation and RGB input validation.
- Optional constant background correction using median estimates from configured sky rectangles.
- Luminance noise estimation and gentle residual suppression using Gaussian filtering.
- Chroma smoothing, a rational midtone curve, and restrained saturation.
- Preservation of a configured bottom caption strip.
- PNG, side-by-side JPEG and JSON outputs.

It is a prototype baseline, not a production engine or a PixInsight implementation. Do not shell out to it behind every UI action. Refactor the concepts into typed, testable functions; build independent precision-preserving readers and pipelines. Specifically improve parameter validation, sky selection, source-versus-output clipping reporting, arbitrary region protection, monochrome handling, high-precision I/O, error handling and cancellation. Do not copy M33 sky coordinates or its caption boundary into defaults.

The following formulas document the baseline without requiring access to the installed skill:

```python
# x: display-referred float RGB in [0,1], selected science pixels only
# For each valid sky patch: take the median RGB of its dimmer 65% pixels.
# bg: channel-wise median of patch estimates, at least 3 user-confirmed patches.
y = x - background_strength * (bg - pedestal)
L = y @ [0.2126, 0.7152, 0.0722]
r = L - gaussian_filter(L, sigma=0.8)
sigma_n = median(abs(r - median(r))) / 0.67449
gate = exp(-(r / (2.5 * max(sigma_n, 1/1024))) ** 2)
L_denoised = L - denoise_strength * gate * r
# Blend chroma with Gaussian-smoothed chroma using the same gentle gate.
L_mapped = gain * L_denoised / (1 + (gain - 1) * L_denoised)
# Reconstruct RGB by a luminance ratio; apply protected saturation last.
```

These constants apply to the rendered baseline only. They are not valid physical noise estimates for arbitrary linear FITS. Handle zero denominators, negative channels, out-of-range results and invalid pixels deliberately. Avoid intermediate clipping; record clipping before final display export. Do not normalize each channel separately. *(Amended 1.3: per-channel sky **offsets** to one shared pedestal and bounded, recorded white-balance **gains** are allowed as explicit linear operations; the shared normalization itself remains one scale for all channels.)*

## 4. Scope and delivery stages

### Complete version 1

- Multiple JPEG/JPG, TIFF/TIF and FIT/FITS/FTS uploads.
- RGB and monochrome; high precision preserved for supported TIFF/FITS.
- Individual and batch enhancement selection.
- Gentle denoising, controlled stretching, direct brightness/shadows/highlights/black-point controls, restrained local contrast, existing-color boost, optional supervised constant or spatial background correction, and star protection during stretching.
- User-created presets with safe per-image resolution and versioned settings.
- Optional NVIDIA GPU processing, Auto/GPU/CPU execution settings, visible processing-device status and reliable CPU fallback.
- Before/after comparison, synchronized zoom/pan, blink and split view.
- Individual exports and Download All ZIP.
- Local history, reproducible processing report, reprocessing and cancel.
- Friendly intake resolution for unknown FITS state/HDU/channel layout.

### Version 1.1 — one-button Enhance (amendment 1.3)

- Built-in presets by desired output: Natural, Vivid, Faint detail, Bright core (HDR), Star field, Seestar match.
- Six main sliders (Background, Stretch, Contrast/Pop, Color, Detail, Noise reduction) plus **Protect bright cores**.
- Automatic stages for linear stacks: low-coverage edge masking, low-order gradient model, background neutralization, bounded field-star white balance, multiscale wavelet denoise, auto-solved hyperbolic stretch with highlight convergence, gentler star stretch, HDR core compression and green removal when detected. Each runs or is skipped with a recorded reason and can be switched off in Advanced.
- Opt-in Richardson–Lucy deconvolution (Advanced).

### Version 1.2 — stacking (amendment 1.4)

- **Input:** an absolute folder path typed or pasted by the user; folders are scanned non-recursively and only read. FITS
  frames are classified by `IMAGETYP` (or the file-name prefix) into lights, darks, flats, bias and dark-flats; separate
  calibration folders may be given. Raw CFA/mono sub-frames are stacked ("subs"); if the folder holds only stacked RGB
  images they are combined ("sessions", several nights). Mixed sizes/filters/patterns are reported and excluded, never
  silently merged.
- **Subs pipeline:** median master frames → dark (or bias) subtraction → flat division (master flat normalized per Bayer
  site so colour balance is unchanged) → cosmetic correction of fixed defective pixels (found on the master dark, or on a
  temporal median of lights; replaced by same-colour neighbours; counted) → frame measurement on a 2 × 2 super-pixel proxy
  (stars, FWHM, elongation, transparency, background, noise) → frame grading (Off/Lenient/Standard/Strict; each rejection
  has a reason) → star registration (triangle invariants + RANSAC similarity: rotation, scale, shift, which covers alt-az
  field rotation) → bilinear debayer → additive per-channel background normalization → bilinear resampling onto the
  reference frame → noise-weighted (1/σ²) mean with iterative kappa-sigma rejection (exact, median-centred, for up to 40
  frames that fit the RAM budget; two-pass streaming otherwise).
- **2× drizzle (optional, subs only):** Bayer drizzle with a point kernel and bilinear weights of measured CFA samples only,
  rejection against the native statistics; output pixels no frame reached are filled from the upsampled native stack and
  the filled fraction is reported.
- **Sessions:** star registration at any scale, resampling onto the largest image, background matching, weights by
  integration time, kappa-sigma rejection from three images on.
- **Output:** float32 RGB (or mono) FITS in source units, `ROWORDER=TOP-DOWN`, `STACKCNT`, `LIVETIME`, `HISTORY`; pixels
  with no coverage are NaN (masked by the reader). The file becomes a new immutable original with state "linear stack".
  A stack report (frames used/rejected with reasons, calibration, registration, normalization, weights, rejection,
  timing, device) is stored with the stack.
- **Fidelity:** every output value is a weighted mean of measured, resampled pixel values; nothing is synthesized. The
  only interpolation is bilinear debayering/resampling (and the disclosed drizzle hole filling).
- **Scheduling:** stacks share the single worker with enhancement jobs (oldest first), report progress, can be cancelled
  and retried, are marked interrupted after a restart, and are removed by Clear local history. Debayering and
    resampling may use the NVIDIA GPU (CuPy) with the CPU as the reference implementation.
- **Enhancement after stacking:** only when the user ticked "Enhance automatically when stacking finishes" (default off);
  the recipe/preset at that moment is snapshotted into the stack.

### Version 1.3 — optional AI tools (amendment 1.5)

- **Recipe:** `ai = {background, denoise, stars}`, all `false` by default and in every built-in preset (selecting a
  built-in preset keeps the user's AI switches; saved presets carry their own). Schema 3 recipes and saved presets are
  migrated automatically with the AI tools off.
- **AI background extraction (linear stacks):** GraXpert background model 1.0.1, fed exactly as in GraXpert (frame shrunk
  to 256 px, median/MAD normalization); the predicted background is blurred, enlarged and subtracted zero-median per
  channel in place of the polynomial gradient model. Not used with a confirmed manual background.
- **AI noise reduction (linear and rendered):** GraXpert denoising model 3.0.2 (256 px tiles, stride 128, star cores
  above 250 MAD pass through unchanged), strength = the Noise reduction slider, in place of the wavelet denoise. If the
  model cannot run, the wavelet denoise runs instead. Because AI smoothing flattens the sky far more than its true noise
  drops, the stretch solver treats AI-denoised data as at most 2x cleaner than before (about what full-strength wavelet
  denoise measures), so the result is cleaner at a comparable stretch rather than over-stretched.
- **AI star separation (linear stacks):** Cosmic Clarity Dark Star v2.1c (colour) / v2.1 (mono) under a temporary,
  exactly inverted midtone stretch, with the large-scale background above the sky level taken out before inference (so
  a bright galaxy bulge is not mistaken for a star) and any star-layer structure wider than a star returned to the
  starless layer. `starless + stars` equals the input exactly. Display finishing (stretch, HDR, pop, detail, saturation)
  is applied to the starless image; the stars are added back with the display brightness the stretch gives them,
  blended toward the gentler star stretch. The processed-linear FITS is never starless.
- **Models:** downloaded on request into `<data>/ai-models` from fixed URLs (an identical file in a local GraXpert
  installation is copied instead), verified by size and SHA-256, removable in Settings. GraXpert models are
  CC BY-NC-SA 4.0 (non-commercial use); Dark Star is MIT. The cache key of a run includes which model files were used.
- **Disclosure:** each AI operation in the report records model id, file, version, SHA-256, licence, attribution,
  execution provider, timing and fallbacks; `learned_processing` lists them; the scientific disclosure states that those
  values were predicted by trained networks; processed FITS HISTORY names the model files.
- **Known limits:** background extraction can darken the faintest outer halo of a frame-filling galaxy; denoising can
  soften the faintest structure at full strength; star separation leaves very large saturated stars partly in the
  starless image (they are added back unchanged).

### Engine 1.3.0 — optional color workflow

- Keep the one-button defaults and immutable source workflow. Migrate recipe schemas 3/4 to schema 5 with the new settings neutral.
- Object Color is a bounded display-only saturation adjustment by hue, guarded by sky signal, star, protection and highlight masks. Use an opt-in thumbnail/mask preview. Disclose skipped protection and clipping guardrail outcomes.
- Catalog color uses celestial WCS from the chosen FITS HDU, never an upload or a network lookup. Validate and hash the local catalog, fit gains from unambiguous unsaturated reference-star matches, and report fallback. Disable broadband color correction for the app's intentional filter mixes.
- Focused stretch is an opt-in, sky-anchored asinh curve on linear data; record the resolved pivot, curve strength and protections.
- Channel mixes create a separate linear FITS with explicit input roles, gain, WCS alignment and source hashes. Preserve the reference grid and invalid overlap; do not generate missing signal. Unsolved inputs must be explicitly prealigned. No star replacement or starless output is introduced.
- Engine 1.3.1 / recipe schema 6: a separate single-click Hubble-style action for recognized or explicitly confirmed H-alpha/OIII linear color FITS. Default Enhance and existing presets remain unchanged. The optional strength blends gold/teal according to sky-subtracted red and green/blue signal, with star, sky and highlight protection and no inferred sulfur channel. The processed-linear export is unchanged; the display recipe, mask inputs and any skipped operation are recorded. Known broadband data cannot be confirmed as dual-band.

### Deferred

Arbitrary cubes and multi-page stacks; plate solving; absolute flux calibration; star reduction/removal in exports;
additional learned processing beyond the three opt-in tools; native installer; cloud hosting; accounts; remote
mobile access; commercial billing.

Deliver an initial JPEG vertical slice first, but do not call the full version 1 complete until real TIFF and stacked FITS fixtures pass validation. Staged development is not permission to omit the requested formats.

## 5. Recommended architecture

| Component | Choice | Reason |
|---|---|---|
| Interface | React + TypeScript + Vite | Responsive upload queue and synchronized image comparison |
| Styling | Plain CSS or Tailwind; accessible primitives | Keep controls simple and consistent |
| API | FastAPI + Pydantic | Typed requests, upload handling and generated API docs |
| Processing | Python; NumPy/SciPy CPU backend and optional CuPy/cupyx GPU backend | Equivalent conventional algorithms with accelerated eligible array operations |
| Raster I/O | Pillow/ImageCms, tifffile + imagecodecs | JPEG/color management and high-bit-depth TIFF |
| FITS I/O | Astropy | HDUs, image arrays, scaling, headers and WCS |
| Optional later denoiser | scikit-image | Classical wavelet filtering after baseline validation |
| Queue | Durable SQLite jobs + one worker process | Avoid blocking API and exhausting RAM |
| Tests | pytest + Playwright | Numerical and end-to-end UI verification |
| Distribution initially | PowerShell setup/start scripts | Familiar Windows workflow without Docker |

Use a supported Python release compatible with all dependencies; Python 3.12 is a conservative starting candidate, not a locked requirement. Choose mutually compatible versions at implementation time, lock Python and npm dependencies, and record them in exports. Do not blindly install development documentation versions. No Redis or cloud database is necessary. CUDA/CuPy are optional dependencies: CPU-only installation must remain fully functional. GPU-enabled installation requires a compatible NVIDIA driver, CUDA runtime/toolchain components and CuPy build verified together on the target PC.

Serve the production frontend from FastAPI under the same origin. In development Vite proxies `/api` to FastAPI. Bind to `127.0.0.1`; reject unexpected Host and Origin values. Require an ephemeral session token for mutations and validate same-origin requests, since a local API must not accept arbitrary websites' requests. Keep the token out of logs and persistent URLs. Do not expose this local design publicly without a separate security and hosting design.

### Optional NVIDIA acceleration — version 1 requirement

Implement a backend interface for supported array operations, with NumPy/SciPy on CPU and CuPy/cupyx on NVIDIA CUDA. The GPU accelerates mathematical image processing; it does not introduce AI models, learned filters or image generation. Use identical algorithm definitions, dtypes, boundary modes, kernel truncation and scale conventions on both backends. Do not assume every SciPy function has a compatible CuPy equivalent.

| Operation | Execution policy |
|---|---|
| Gaussian filtering, denoising residuals, chroma smoothing | GPU eligible after equivalence tests |
| Tone curves, saturation, mask blending, gradient evaluation | GPU eligible; group stages to amortize transfers |
| Local-contrast filtering and supported star-mask operations | GPU eligible after parity and seam tests |
| FITS/TIFF/JPEG decode, headers, color profiles and encoding | CPU/disk |
| Small sky-sample statistics, robust planar fit and job coordination | CPU by default; avoid needless transfer overhead |
| Unsupported operations or precision-critical paths | CPU with explicit stage/backend reporting |

Lazy-import CuPy only in the worker; never prevent CPU startup because CUDA is absent or broken. Initialize CUDA inside the spawned processing worker, not a parent process that might be forked. Probe driver/runtime compatibility, device name, available memory and compute capability; then execute a small allocation, filter and synchronized numeric result check. Device discovery alone is insufficient. If probing fails, Auto selects CPU and shows a short setup note.

Provide **Processing device: Auto / NVIDIA GPU / CPU** in application settings. Auto is the default and chooses GPU for eligible sufficiently large workloads when compatibility, memory and validated algorithm support permit. Use measured crossover sizes; small previews may be faster on CPU. NVIDIA GPU requests acceleration for eligible stages, with explicit notes and CPU fallback on recoverable GPU unavailability or memory failure; it never implies every stage runs on GPU. CPU bypasses CUDA. Show the resolved label **Processing: NVIDIA GPU**, **Processing: CPU**, or **Processing: GPU + CPU** while work runs, plus the fallback reason when applicable.

Treat hardware selection as an application execution preference, separate from aesthetic presets. Record requested and actual backend per stage, device, driver/runtime/CuPy versions, transfers, fallback cause and timing in each report. Add actual backend/precision to cache keys; retain the same source/recipe lineage. Do not claim GPU improves image quality or promise a speedup before end-to-end benchmarking.

Install and lock GPU dependencies separately from the CPU dependency set. Use the official CuPy Windows installation guidance to select a supported Python/CuPy/CUDA combination compatible with the installed RTX 5070 Ti driver and architecture. Do not blindly pin a CUDA wheel by GPU name or install multiple conflicting CuPy variants. Supply an optional `setup-gpu.ps1` and **Check GPU setup** diagnostic, with a working CPU-only alternative. No automatic driver installation or system-wide CUDA changes. A full CUDA toolkit may or may not be needed depending on the selected package/runtime strategy; document the verified setup rather than claiming a universal installation command.

Minimize host/device round trips. Transfer a supported science array/masks once per contiguous GPU stage group, retain intermediates on-device, and transfer final data or small diagnostics back as needed. Explicitly synchronize before timing and before treating a stage as successful, since GPU work is asynchronous. Keep robust global statistics independent of tile boundaries.

### Suggested repository

```text
astro-photo-enhancer/
  README.md
  astro-photo-enhancer-app-spec.md
  backend/
    pyproject.toml
    dependency-lock-file
    app/
      main.py
      api/{assets,jobs,exports,settings}.py
      models/{assets,recipes,jobs,reports}.py
      services/{storage,queue,previews,exports}.py
      processing/
        readers/{jpeg,tiff,fits}.py
        pipeline.py
        background.py
        denoise.py
        tone.py
        color.py
        masks.py
      gradients.py
      local_contrast.py
      star_protection.py
        diagnostics.py
      backends/{base,numpy_backend,cupy_backend}.py
    tests/{unit,integration,fixtures}/
  frontend/
    package.json
    package-lock.json
    src/
      components/{UploadPanel,ImageQueue,EnhancementPanel,CompareViewer,ExportMenu}.tsx
      api/
      types/
    tests/
  scripts/{setup.ps1,start.ps1,test.ps1}
  .github/copilot-instructions.md
```

Runtime data belongs outside source control in a configurable app-data directory: immutable originals, metadata, preview caches, run outputs and SQLite database. Ignore all astronomical images and local paths in Git by default. Provide fixture licensing/permission notes if sample photographs are distributed.

## 6. User interface specification

### Single main workspace

Use a dark neutral background, restrained blue accent, generous spacing and readable labels. Do not put a decorative space photograph behind the viewer; it interferes with evaluating contrast. Default layout on desktop: narrow queue on the left, large viewer in the center, compact enhancement panel on the right. The layout stacks on smaller windows. All essential controls support keyboard access and visible focus.

### Empty state

Title: **EasyAstroEnhance**

Description: **Bring out the detail in your telescope photos.**

Large drop zone: **Drop photos here or Choose files**

Helper: **JPEG, TIFF, FITS • Multiple files supported • Processed on this computer**

No login, object-name question, telescope-model question or API setup. Show supported format names, not implementation details.

### Intake and queue

Each file card shows thumbnail, filename, dimensions, RGB/monochrome, file type and status. A FITS thumbnail is a display rendering, not the raw linear array painted nearly black. Statuses: Inspecting, Ready, Needs input, Queued, Processing, Complete, Complete with notes, Failed, Cancelled, Interrupted. An error on one file must not stop the rest of the batch.

Automatically choose the only supported image HDU; if several exist, show a short selector with HDU name, dimensions and preview. For unknown data state show one exceptional prompt: **How was this image saved?** Options: **Linear stack**, **Already processed**, **I'm not sure**. Explain the consequence briefly; “I'm not sure” permits an explicitly labeled preview but blocks full processing until state is confirmed. Do not silently infer linearity from a dark histogram.

Single CFA/raw frames display: **This file needs debayering or stacking first. Export a stacked RGB or monochrome image and add it here.** Keep other supported files ready. *(Amended 1.4: raw frames are stacked with **Stack frames…** — top bar or the start screen — which opens a dialog: folder path, Scan (summary of frames, exposure, calibration found, files not used), output size Native/2× drizzle, an Advanced section (frame quality filter, trail rejection), optional calibration folders, and the **Enhance automatically when stacking finishes** checkbox, default off. A banner shows progress with Cancel.)*

### Enhancement panel

*(Amended 1.3 — one-button Enhance.)* Preset menu: **Natural** (default), **Vivid**, **Faint detail**, **Bright core (HDR)**, **Star field**, **Seestar match**, **Custom**, and user-saved presets, each with a one-line description. Presets are rendering styles chosen by the user; nothing is inferred from the object's name. Below the menu, a **Look** section has six sliders whose values the preset sets and that map to documented, recorded parameters:

| Slider | Range | Behavior |
|---|---|---|
| Background | 0.04–0.25 | Display level of the median sky (MTF placement) |
| Stretch | −1…+1 | Shifts the auto-solved hyperbolic stretch factor by 0.75 decades per unit |
| Contrast / Pop | 0–1 | S-curve anchored at the sky and white (amplitude 0.8 × value, monotonic) |
| Color | 0–1 | Saturation 1 + 0.6 × value, protected below the sky noise and near white; unavailable for monochrome |
| Detail | 0–1 | À trous multiscale contrast, gated by per-scale noise and local edge energy, suppressed near star halos |
| Noise reduction | 0–1 | Wavelet gated shrinkage, amount 0.9 × value relative to the measured per-scale noise |
| Protect bright cores | on/off | Highlight-protecting stretch target and HDR core compression when a bright extended core is found |

The supervised **Manual sky regions** correction (constant / planar) and **Preserve labels** remain as before. Advanced exposes switches for each automatic stage, the stretch on/off, opt-in deconvolution, exact values (stretch log D, b, highlight convergence, star softening, core compression, white-balance limit, gradient degree, green removal, denoise scales, detail scale, rendered midtone gain, manual background strength, deconvolution iterations), input state, protected regions and histogram diagnostics. *(The 1.2 table of switches with Gentle/Balanced/Strong buttons below is superseded.)*

<details><summary>Superseded 1.2 text</summary>

Preset menu: **Natural** (default), **Brighter detail**, **Custom**, and user-saved presets. Add **Save preset** beside the preset menu. Both named presets use conservative denoising. Brighter detail increases tone gain modestly; it does not promise additional resolution.

| User control | Default | Behavior |
|---|---|---|
| Reduce noise | On, Gentle | Luminance and chroma cleanup with structure protection |
| Bring out faint detail | On, Gentle | Controlled midtone stretch; linear data gets a separate stretch path |
| Enhance existing colors | On, Gentle when RGB | Modest saturation; unavailable for monochrome |
| Balance background | Off | Constant correction after at least 3 confirmed sky regions; optional supervised planar gradient correction after at least 6 well-distributed confirmed regions |
| Protect stars | On, Gentle | Limits additional brightening of confidently identified compact stars during stretch |
| Local contrast | Off | Gentle, noise-aware enhancement of existing medium-scale structure |
| Preserve labels | On when a region is confirmed | Exclude a bottom band or arbitrary rectangles from processing |

</details>

Expose an optional **Tone controls** disclosure directly under the main enhancement switches. Include Brightness, Shadows, Highlights and Black point, each with a labeled slider, numeric value, zero/default marker and Reset. Brightness must support both lightening and darkening. Keep black-point movement tightly bounded, show a histogram and clipping overlay when adjusted, and allow instant Reset tone. Start all manual offsets at zero; the selected preset supplies the base stretch. Manual values are offsets from that base, not an additional automatic stretch. Monochrome supports all tone controls.

Inside background settings, offer **Overall balance** and **Uneven sky (gradient)**. Explain the difference briefly. Show sky sample overlays, a proposed correction preview and **Apply correction** / **Skip**. Require confirmation of the spatial model before enabling it for a run. If samples do not support a reliable plane, retain the constant option or skip; never silently substitute a more aggressive model.

Saved presets store enhancement intent, bounded manual tone offsets and engine/schema version in SQLite. Provide create, rename, duplicate and delete. Never store sky rectangles, label regions, per-image normalization, star masks, FITS HDU choices or fitted gradient coefficients in a reusable preset. Selecting a preset that requests background correction marks that operation pending until each new image has confirmed regions/model. Snapshot presets into each run; later edits cannot change past results. Reject incompatible presets with migration guidance.

Use three strength buttons (Gentle / Balanced / Strong) rather than raw numeric fields in the main UI. *(Amended 1.3: the main UI uses the bounded Look sliders above; strength buttons remain only for manual sky-region correction.)* Strong is still bounded and must run clipping checks. Advanced can expose exact values, input state, protected regions and histogram diagnostics. Never let “Apply to all” copy sky or caption coordinates across unrelated images. A shared recipe shares intent; masks and derived parameters belong to each asset.

Natural starting candidates for the rendered path: denoise 0.30, rational gain 1.25, saturation 1.08. Brighter detail: 0.40, 1.45, 1.12. These are proposed tuning values, not proven universal presets. Validate on multiple targets before locking defaults. Background strength defaults to 0.5 only after confirmed sky patches. The sky pedestal is selected per image to avoid black clipping; there is no universal fixed value.

For low-friction use, background balancing remains optional. The app may suggest candidate sky regions, but these are heuristic suggestions requiring user confirmation. Dark corners alone are insufficient evidence of empty sky. Show **Skip background balancing** prominently when a galaxy/nebula fills the frame.

For captions, propose a footer boundary only when a detector is confident; offer a single draggable line to confirm. Otherwise show **Does this image contain a label?** as a small optional action. Arbitrary protected rectangles remain available in Advanced. Text detection must run locally if implemented and must not fabricate pixels.

Primary action: **Enhance selected**; secondary action: **Enhance all ready images**. Make batch scope explicit. Editing settings after completion marks the result **Settings changed** and enables Reprocess. It never modifies the existing run.

### Before/after viewer

- Default draggable comparison divider; side-by-side and blink alternatives.
- Label sides **Original view** and **Enhanced**. For FITS add **Original shown with a display stretch**.
- Shared zoom and pan; Fit and 100% buttons; a keyboard-accessible divider.
- Identical geometry, interpolation and color management for both sides.
- For rendered sources, show original display values without independent automatic equalization.
- For linear FITS, derive a display-only baseline from the source once and freeze it. Never auto-stretch each side independently during comparison. Enhanced display uses its explicitly recorded tone transform. Provide an optional fixed-mapping diagnostic comparison for inspecting processing before tone adjustment; label this clearly.
- Preview up to 2,048 pixels on the long edge; support full-resolution ROI tiles for 100% inspection. Label downsampled previews. Avoid loading huge arrays into browser memory.
- Processing progress uses named steps; do not invent exact percentages where progress cannot be measured.
- Show a compact result note such as **Noise reduced · Midtones brightened · Background balancing skipped**.

### Exports

Primary **Download PNG**; secondary **More formats** and **Download all**. Defaults: full-resolution sRGB PNG plus processing report. Offer 16-bit TIFF for high-quality display output, optional JPEG quality 95 for sharing, and processed float FITS for FITS inputs. Provide a share-sized comparison JPEG as an optional export. Do not accidentally embed a downsampled preview as the master export.

ZIP contains a folder per image/run with collision-safe names and a batch summary. Example: `M33__a1b2c3d4__run-002/enhanced.png`, `processing.json`, `processing-summary.txt`, optional `enhanced-display.tif`, `processed-linear.fits`, `comparison.jpg`. A FITS input's derived FITS is explicitly labeled linear or display-processed according to actual operations.

## 7. File decoding and canonical data model

### Supported matrix

| Input | Version 1 support | Required handling |
|---|---|---|
| JPEG/JPG | 8-bit RGB and grayscale | EXIF transpose once, embedded ICC to sRGB, preserve source |
| TIFF/TIF | Single image grayscale/RGB; uint8/uint16/float32 | tifffile, inspect samples/axes/photometric tags; preserve range |
| FIT/FITS/FTS | 2-D mono and documented 3-channel stacks | Astropy, HDU selection, scale once, explicit state |
| CFA, arbitrary cubes, multipage TIFF | Intake only | Explain and request supported export; never guess axes |

Unsupported CMYK/palette/complex arrays receive an explicit supported-conversion path or an explanation. Do not silently cast them to 8-bit RGB. Alpha may be retained as a mask if implemented; otherwise reject it explicitly. Nonfinite pixels remain masked, do not become dark stars. Preserve their FITS mask on output; use documented black/transparent display treatment with invalid counts.

Canonical object: `ImageData(pixels, channel_layout, domain, units, valid_mask, protected_mask, metadata, source_hash, orientation_transform, normalization)`. Pixel arrays are H×W for mono or H×W×3 for RGB. Use float32 work buffers normally and float64 for statistics/fits; retain float64 where reducing source precision would be material. Maintain reversible shared-channel scale/offset separately from actual source units. Never divide arbitrary FITS values by 255 or independently scale RGB channels to their percentiles.

Astropy normally applies BSCALE/BZERO when accessing scaled image data. Use one documented strategy: accept physical-value scaling on read, copy the source header before data access, and never apply scaling a second time. Record original scaling. On float export remove stale integer scaling/BLANK cards and update structural cards/checksums through Astropy. Preserve appropriate observing metadata and WCS; annotate changed photometry/units and provenance. Do not preserve invalid DATAMIN/DATAMAX or misleading BUNIT values unchanged. Save original headers separately for traceability.

Select axes from supported layout and metadata. Do not assume every shape starting with 3 is RGB. File-specific decisions must be confirmed when ambiguous. WCS and visual display orientation must remain consistent on export; do not flip source arrays just to match a browser convention. *(Amended 1.3: FITS rows are treated as bottom-up unless `ROWORDER` says otherwise; ZWO Seestar files (CREATOR/INSTRUME/TELESCOP containing "Seestar") without `ROWORDER` are stored top-down and are kept as stored, which matches the telescope's own JPG; export restores the stored order either way.)*

## 8. Processing pipeline

### Common stages

1. Inspect and validate input; hash source; resolve state, channels and masks.
2. Compute baseline diagnostics from valid, unprotected pixels.
3. Build an immutable resolved recipe and allocate worker memory.
4. Execute applicable pipeline below, with stage-level diagnostics and cancellation checks.
5. Restore protected source regions in the same display domain; validate geometry and pixels.
6. Generate full-resolution exports, previews, provenance and optional comparison.
7. Atomically finalize run; publish results only after validation succeeds.

### Rendered JPEG/TIFF path

Operate on a documented display-referred sRGB representation. Start by reproducing the existing helper's conservative filter and tone concepts; do not describe display-domain luminance weights as physical radiometry. Perform optional constant or planar sky correction, gentle luminance/chroma denoising, the preset tone curve with manual tonal offsets and star protection, optional restrained local contrast, saturation and gamut handling. For high-bit TIFF retain float precision and quantize only on chosen export.

Use edge-aware masks around bright compact sources to reduce filtering there. Support chroma smoothing without smearing color across star boundaries. Blend filter results with the original according to selected strength. Handle zero/negative luminance safely; do not blindly multiply RGB by huge ratios. Mask protected regions out of statistical estimation and local filtering neighborhoods; otherwise caption edges can bleed into nearby sky. A no-operations recipe must reproduce decoded display pixels exactly in lossless export.

### Linear FITS/TIFF path

Inspect state before enabling this path. Preserve signed/float data and apply only a documented shared normalization for processing. Optional confirmed constant or planar sky subtraction precedes display stretch. Denoise gently in the linear domain with a data-scale-aware noise estimate from validated regions or robust masked high-frequency residuals. Resampling and stacking correlate noise, so a MAD estimate is approximate, not a calibrated signal-to-noise measurement.

Start with conservative residual shrinkage using relative noise thresholds; evaluate classical wavelet soft thresholding later behind a named engine version. Do not use the rendered path's fixed 1/1024 noise floor on physical FITS units. Treat Gaussian-noise assumptions as approximations; do not claim a universal Poisson noise model.

Separate a processed linear array from the aesthetic display renderer. A luminance-based asinh renderer is an initial candidate:

```text
u = shared_normalize(processed_linear)
L = luminance(u)                  # or u for mono
s = max(L - display_black, 0)
t = asinh(k*s) / asinh(k*display_white_span)
RGB_display = guarded_luminance_ratio(u, L, t)
```

Specify and record the shared scale, display black, white span and k; choose them robustly from valid science pixels, not caption/star cores. This display operation intentionally changes tonal relationships; do not apply its clipping to the saved processed-linear FITS. Final gamut mapping must preserve hue as far as practical rather than independently clipping channels excessively. Apply manual tone offsets, star-protected tone blending and optional local contrast in the display renderer after linear denoising. Saturation applies only to the display RGB result, not to linear science-like export by default. Save the processed-linear FITS before all display-only operations and record the separation explicitly.

Monochrome stays monochrome. Unknown/narrowband channel mappings are preserved and disclosed; no automatic Hubble palette. No automatic photometric calibration is included.

*(Amended 1.3 — engine 1.1 linear path.)* The linear path runs two pixel groups. **Group A** (saved as processed-linear): supervised background (if confirmed) → automatic low-order gradient model (robust polynomial, degree ≤ 3, fitted to sigma-clipped sky boxes away from stars and extended signal; skipped with a reason when samples are insufficient, poorly distributed or the gradient is negligible) → background neutralization (per-channel sky from the dimmer 75 % of the frame, offset to one shared pedestal of 3σ) → bounded white balance from isolated, unsaturated field stars (gains limited to 1/1.25–1.25 by default, skipped when fewer than 15 stars or inconsistent colors) → optional deconvolution → à trous wavelet noise reduction. **Group B** (display only): hyperbolic luminance stretch `Ls = (asinh(D·L+b) − asinh(b)) / (asinh(D+b) − asinh(b))` with highlight convergence `rgb = Ls·(r(1−Ls^p) + Ls^p)` and color confidence near the sky; the white point is the data maximum; D is auto-solved so the 99.9th percentile of star-free signal lands at 0.88 (0.96 without core protection); an MTF then places the median sky exactly at the Background level with a floor 5σ below the sky. The frozen baseline ("Original") is a linked autostretch (median − 2.8σ shadows, sky at 0.15). Low-coverage borders are excluded from every statistic and never cropped. *(The asinh renderer above describes engine 1.0.)*

### Background correction requirements

Version 1 supports constant background neutralization and an optional supervised first-order spatial correction. Require at least three non-overlapping confirmed patches for the constant model. For the planar model require at least six confirmed, widely distributed, non-collinear patches spanning both axes, with adequate valid pixels and low star contamination. Six is an initial engineering minimum, not proof of reliable sky. Validate coordinates, spatial coverage, sample counts and finite statistics server-side. Exclude stars, captions and invalid regions from estimates.

Use robust patch medians and fit only a plane `a + b*x + c*y` in normalized coordinates, using robust regression and uncertainty/residual checks. No high-order polynomials, automatic learned background replacement or object-dependent models. For RGB, estimate a shared spatial sky-brightness trend plus constant channel offsets first; enable independent channel planes only after separate validation of color gradients. Subtract the gradient relative to a recorded reference sky level, then optionally apply constant neutralization; do not subtract the constant twice. Keep physical negative values in linear working data rather than clamping them. Model sampling precedes stretching on linear inputs.

Show sample positions, model preview and residual statistics. Flag inadequate coverage, outliers, ill-conditioned fits and evidence of extended signal. Require user confirmation and allow samples to be excluded. Automatic checks cannot prove a patch is empty sky. For frame-filling nebulosity or inconsistent samples, skip spatial correction. Persist the model and confirmation per asset/run; never transfer them through presets or Apply to all. High-order gradients and correction without credible sky remain deferred.

*(Amended 1.3.)* The supervised flow above remains for manual control. In addition, the automatic stages of engine 1.1 (neutralization, low-order gradient, white balance) run without confirmation on linear stacks because each validates its own samples, records its model and skips with a reason when the sky is not credible; they are switched off individually in Advanced and are skipped when a confirmed manual correction is used.

### Direct tonal controls

Implement a documented, monotonic base tone mapping with bounded adjustments. Brightness may begin as display-domain exposure scaling `2**EV`, with a proposed range of -1 to +1 EV. Shadows/highlights use smooth monotonic curve adjustments with fixed control-point order, not hard pixel thresholds; choose and document bounded ranges during visual tuning. Reject curve settings that reverse brightness order. Black point changes the display floor only; never erase negative or faint physical values in the processed-linear FITS. Do not advertise independent tone sliders while ignoring their values in the backend.

Compose settings into one resolved tone transform, avoiding accidental double stretching. Apply star protection to the difference between original-display and transformed luminance. Brightness darkening remains effective; protection primarily attenuates positive tone changes around bright star cores. Record all curves/parameters and their order. Neutral manual offsets introduce no extra transform. Reuse the existing clipping checks for every adjustment.

### Star protection during stretching

Build a soft mask from compact, confidently detected stellar sources using local background/noise estimates, size/shape checks and feathered dilation. Do not equate every bright pixel with a star: exclude broad cores, nebular knots and uncertain compact features from automatic star-specific treatment. If detection is unreliable, skip star-specific protection and disclose that the general highlight roll-off still applies. Expose the mask overlay in Advanced and allow protection to be disabled.

Blend the added tone boost down within confirmed star masks. This is selective stretching, not star subtraction, shrinking, reconstruction or replacement. Preserve star positions and avoid dark rings or abrupt mask edges. Keep this stage off the processed-linear FITS. Resolve masks per input and record mask construction settings. If the tone stage is disabled, protection has no effect and is reported as inactive.

### Restrained local contrast

Keep off in both initial presets; offer an optional Gentle control. Start with a coarse-scale luminance base/detail decomposition and a bounded boost to existing medium-scale residuals, blended by signal confidence. Use edge-aware smoothing and noise gating; avoid boosting the finest noisy scales. Record filter scale in full-resolution pixels, strength and gating settings. Preview downsampling must not change the effective processing scale. Preserve chroma through guarded luminance reconstruction; do not claim recovered resolution or call it deconvolution.

Suppress or skip the boost in noise-dominated sky, invalid/protected areas and near bright stellar halos. Check faint outskirts, galaxy cores and sharp transitions for ringing, halos, black clipping and amplified mottling. Reduce strength or revert this step when it degrades the image. Include overlap sufficient for the largest filter footprint in any tiled implementation. This is display-only processing for linear sources.

### Protection, clipping and rollback

Count input and output zero/max channel values for display data; separately report negative physical FITS values without calling them clipping. Measure new clipping using pixel transitions, not only a difference in total counts. Exclude invalid and protected pixels from statistics. A proposed guardrail is new display black clipping above 0.1% of eligible pixels: reduce subtraction/stretch once and rerun; if still exceeded, flag review and retain the conservative fallback. Treat this threshold as a configurable aesthetic safeguard, not an astronomical correctness theorem. Use an equivalent check for newly clipped highlights.

Reject nonfinite numeric results. Restore protected rendered pixels exactly for lossless PNG/TIFF at the same bit depth; JPEG re-encoding cannot guarantee byte/pixel equality. For linear sources, protected pixels remain untouched in the linear output and use the source's baseline display rendering in comparison/output. Inform the user that this can produce a boundary; offer to adjust the band rather than fabricate a smooth sky transition.

## 9. API and state contracts

All endpoints below are local, versioned `/api/v1`. Use generated IDs rather than filenames as identifiers.

| Endpoint | Function |
|---|---|
| GET `/compute` | Return detected devices, probe status and supported stage backends |
| PATCH `/settings/compute` | Save Auto/GPU/CPU preference and bounded memory policy |
| POST `/assets` | Stream multipart uploads; return per-file asset IDs/statuses |
| GET `/assets/{id}` | Inspection, capabilities, metadata, unresolved questions |
| PATCH `/assets/{id}/interpretation` | Confirm HDU, layout, linear/rendered state and regions |
| GET `/assets/{id}/preview` | Baseline preview, optional bounded ROI/scale |
| GET/POST `/presets` | List or create user presets |
| PATCH/DELETE `/presets/{id}` | Rename/update or delete a saved preset |
| POST `/jobs` | Create batch from asset IDs and recipe intent; return 202/job ID |
| GET `/jobs/{id}` | Per-file stage, status, notes and result run IDs |
| POST `/jobs/{id}/cancel` | Request cancellation without deleting originals |
| GET `/runs/{id}` | Applied recipe, diagnostics and export descriptors |
| GET `/runs/{id}/preview` | Enhanced preview/ROI |
| GET `/runs/{id}/exports/{kind}` | Stream full-resolution artifact |
| POST `/exports/batch` | Build ZIP for selected completed run IDs |
| GET `/exports/{id}` | ZIP progress or download descriptor |
| DELETE `/assets/{id}` | Remove app-owned data after explicit UI action; never external files |

Poll active jobs approximately once per second; back off in background tabs. No WebSocket is needed initially. Recipe changes create new runs. Immutable recipe snapshots avoid races when controls change during processing. Retries should be idempotent using a client request key; repeat button clicks must not duplicate expensive work. Cache keys include source hash, engine/dependency version, canonical recipe and per-file masks.

Example intent (schema illustration; all numeric ranges validated by backend):

```json
{
  "request_key": "client-generated-uuid",
  "asset_ids": ["asset-generated-uuid"],
  "recipe": {
    "schema_version": 2,
    "preset": "natural",
    "denoise": {"enabled": true, "strength": "gentle"},
    "tone": {"enabled": true, "strength": "gentle", "brightness_ev": 0, "shadows": 0, "highlights": 0, "black_point": 0},
    "star_protection": {"enabled": true, "strength": "gentle"},
    "local_contrast": {"enabled": false, "strength": "gentle"},
    "color": {"enabled": true, "strength": "gentle"},
    "background": {"enabled": false, "method": "constant"},
    "protect_regions": true
  }
}
```

Worker resolves actual parameters independently per asset. Processing reports contain requested and applied recipes, skipped steps/reasons, source hash, source state and HDU, normalization, regions, dimensions, clipping transitions, noise estimate and its limitations, timestamps, duration, dependency versions, engine version and export hashes. Include confirmed background model coefficients/reference/residuals, star-mask settings, manual tone values, local-contrast settings and preset snapshot in each report. No-operations run is an explicit supported case. Errors have stable codes, readable messages and an optional developer detail; never show a traceback as the main message.

Job states: queued → running → succeeded / succeeded_with_notes / failed / cancelled. A restarted server marks previously running jobs interrupted; offer manual retry. Persist each per-file result as it completes. Cancellation is cooperative between stages; large operations may finish before stopping. Never expose partial files as successful exports.

## 10. Resource handling and local storage

Initial configurable limits: 20 files per batch, 512 MiB per file, 100 megapixels per image. These are proposed limits to benchmark, not performance promises. Stream uploads to disk; inspect headers before decoding huge arrays. Enforce both compressed byte limits and decoded pixel/memory limits.

Estimate peak buffers before processing; default one image at a time and cap the worker at a configurable fraction of available RAM. A 100-megapixel RGB float32 buffer alone is approximately 1.2 GB; several simultaneous copies can exceed memory even when input files are small. Use bounded temporary arrays and preview pyramids; implement tiled filters with overlap if needed and test for seams. A full-resolution asinh transform can be chunked, but global statistics must be resolved once, not independently per tile.

GPU memory management: estimate live buffers and temporary filter workspace before allocation, using free VRAM rather than the nominal 16 GB. Start with an adjustable budget no larger than 70% of currently free VRAM and maintain a reserve for the OS/browser/other GPU apps. Process one image at a time on GPU. Avoid accidental float64 full-frame copies; never reduce a source’s required precision solely to force GPU execution. Use CPU for precision-sensitive paths when necessary. Bound CuPy memory-pool caching and release idle buffers between images or on cancellation/failure.

On GPU out-of-memory, release app-owned buffers, then retry once with a validated smaller tile strategy when available, otherwise rerun the affected contiguous stage group on CPU from a clean checkpoint. Do not continue from partial results or apply a transform twice. Disable repeated GPU attempts for the remainder of that job after device/runtime failure. Catch only classified recoverable execution failures; do not hide algorithm bugs through unconditional fallback. Failed results must never enter caches. Tiled Gaussian/local-contrast operations require full filter overlap; connected-component star analysis must be performed globally or have validated reconciliation. Display a brief fallback note while preserving successful batch items.

Use a worker process with explicit startup/shutdown and Windows-safe process creation. Keep SQLite writes in the coordinator and exchange bounded status messages. CPU jobs must not run directly in FastAPI request handlers or rely on in-process BackgroundTasks as a durable queue.

Sanitize names, block path traversal and archive bombs, validate file signatures, allowlist export kinds and serve only files resolved from app IDs. Check disk space before work, use temporary outputs with atomic rename, and never overwrite an original. Keep user image bytes and sensitive FITS GPS/observer metadata out of application logs. Preserve full original metadata locally; provide **Remove location/observer details from shared exports** enabled by default for display exports. A full-metadata FITS export is explicit. Provide a clear **Clear local history** action showing what app-owned files it removes; no automatic source deletion.

## 11. Tests and acceptance criteria

### Required numerical and I/O tests

- Source bytes and SHA-256 remain unchanged after processing and export.
- CPU-only startup/import and processing succeed with CuPy absent; failed CUDA probe, unavailable GPU and out-of-memory scenarios fall back predictably with truthful status.
- CPU/GPU parity fixtures cover denoising, tone, color, local contrast, masks and gradient evaluation. Compare float arrays with initial normalized tolerance atol=1e-5/rtol=1e-4, then separately inspect display differences, mask topology and clipping decisions; tune justified per-operation tolerances rather than widening them to hide errors. Require exact geometry/protected pixels and equivalent accepted feature settings. No bitwise CPU/GPU identity promise.
- CPU/GPU runs, tiled/full-frame runs, and retries have no seams, repeated transforms or source mutations. Cancel/restart cleanup does not leak device buffers. Test fallback from a GPU stage group against a CPU-only reference.
- Mark GPU tests skipped when no CUDA device is available; do not claim verified GPU support from CPU-only CI. Require a real RTX 5070 Ti validation pass before claiming support for the target PC.
- No-operations RGB/grayscale PNG matches decoded, orientation-corrected source pixels exactly.
- uint16 TIFF round-trip preserves values; float FITS read/write preserves values within declared numeric tolerance.
- Scaled FITS with BSCALE/BZERO is applied exactly once; negative/NaN values and mask semantics are retained.
- Explicit RGB plane layouts, monochrome, ambiguous axes and multiple HDUs take correct intake paths.
- Unknown linearity never receives an unconfirmed permanent stretch.
- Protected rendered regions remain identical in lossless output and do not contaminate sky/noise estimates.
- No sky, invalid sky rectangles, fewer than three samples and inconsistent patches skip/reject correction safely.
- Monochrome color controls are disabled and omitted with a clear report.
- Repeated processing with the same locked environment/settings is deterministic within documented floating-point tolerance.
- Source clipping and new clipping are separately reported; synthetic faint-source fixtures verify no gross flux loss/position shifts caused by a selected conservative filter.
- Tone tests verify neutral offsets, effective lightening/darkening, monotonic curves, repeatable ordering and clipping guards.
- Synthetic known planes plus extended faint objects test gradient recovery on valid samples and refusal with insufficient coverage/contaminated samples. Verify no double subtraction and retained linear negatives.
- Star-protection tests check smooth masking and reduced additional core brightening without position/size reduction, while broad galaxy cores remain outside star masks.
- Local-contrast tests check neutral/off identity, full-resolution scale consistency, sky-noise gating, halos and tiled-filter seams.
- Saved presets survive restart, validate schema/ranges, exclude per-image data and cannot mutate prior run snapshots.
- Synthetic Gaussian stars and ramps detect halo/ringing, smearing, channel shifts and tile seams. Synthetic fixtures are tests only, never user output content.

### Required UI and batch tests

- Upload JPEG + uint16 TIFF + supported stacked FITS in one batch, select controls, finish, compare and download all.
- A corrupt file fails individually while valid files complete.
- Full-resolution export dimensions equal source science dimensions; preview sizes never leak into master exports.
- Viewer pan/zoom/divider align both sides; FITS baseline is frozen and labeled.
- Changing settings marks results stale; rerun reads original and creates a new immutable run.
- Cancel, refresh and server restart have predictable states and preserve originals/completed outputs.
- Identical filenames do not overwrite results. Duplicate clicks do not duplicate jobs.
- Oversized uploads, unsupported CFA, disk-full and invalid region errors are readable and recoverable.
- Keyboard-only upload/settings/comparison/download workflow works.
- Tone Reset, preset save/rename/delete, star-mask preview, and background sample/model confirmation work end to end. Apply to all never copies per-image masks or gradient fits.
- The processed-linear FITS excludes tone, local contrast, saturation and star-protected stretching; display exports include the selected operations.

### Visual release review

Review at least: the user's M33 JPEG, a real Seestar stacked RGB FITS, a monochrome FITS, high-bit TIFF, a frame-filling nebula, a sparse star field, an already stretched image and a stack with a visible sky gradient. Review tone controls, star protection and local contrast independently before combined presets. These real fixtures must be provided/authorized; do not imply they have already been tested. Inspect full frame and matched 100% crops of faint arms, dark sky, bright stars and labels. Check that reduced noise has not erased convincing faint structure or made broad JPEG mottling more distracting. Export a comparison and report for each review.

Aesthetic acceptance is the user's judgment. Provide Natural and Brighter detail examples and tune defaults after feedback; do not score improvement solely by lowered noise. No release claim of FITS support until an actual stacked FITS has passed the full path.

### Performance targets to measure

On the target PC, aim for an initial preview within 3 seconds after decoding a typical ~3 MP JPEG and full processing within 15 seconds. These are UX targets, not verified benchmarks. Record hardware, file size, dimensions, peak RAM and stage timing. Large FITS files may take longer; keep the UI responsive and cancellable. Benchmark CPU versus GPU on the target RTX 5070 Ti using representative JPEG, uint16 TIFF and stacked FITS sizes. Report cold-start/kernel-compilation time, warm processing, transfer cost, decode/encode and total elapsed time, peak VRAM and RAM. Compare quality separately from speed. Derive Auto thresholds from these measurements; no fixed acceleration factor is promised.

## 12. Implementation plan for Copilot

1. **Scaffold and contracts:** Create backend/frontend, typed schemas, local launch scripts, minimal upload queue and same-origin service. Implement immutable storage and basic file validation. Gate: upload a JPEG and show its real thumbnail.
2. **Rendered vertical slice:** Refactor the documented baseline into functions. Implement tone controls and Reset, star-protected stretching, optional local contrast, saved presets, run state, PNG/report exports and synchronized comparison. Gate: process a real JPEG end to end; no-op and label tests pass.
3. **Precision and astronomy intake:** Add tifffile/Astropy, input-state/HDU handling, masks, linear renderer and precision-preserving exports. Gate: real uint16 TIFF and stacked FITS round trips and processing tests pass.
4. **Batch and resilience:** Add durable jobs, one worker, per-file settings resolution, cancellation, retry, ZIP and restart recovery. Gate: mixed-format batch with corrupt file and duplicate names succeeds predictably.
5. **Quality and polish:** Confirmed sky selection and planar gradient preview/approval, protected regions, clipping safeguards, full-resolution ROI comparison, accessibility, resource limits and visual review. Gate: release checklist passes on varied targets.
6. **GPU acceleration and handoff:** Add and validate the optional CuPy backend, runtime probing, device controls/status, memory budgeting, fallback, parity tests and target-device benchmarks. Gate: real GPU execution and CPU-only/failure-path checks pass; do not label an untested backend supported. Supply separate CPU/GPU setup instructions. README with Windows setup/run instructions, dependency locks, troubleshooting, test commands, processing-method disclosure and known limitations. Optionally add a desktop shortcut later.

Do not build empty/mock processing endpoints and present them as working enhancement. Use real pixels from the first vertical slice. Do not add an LLM agent or remote model to make enhancement choices; deterministic presets and validated per-image measurements are sufficient.

### Paste this into GitHub Copilot Chat

> Read `astro-photo-enhancer-app-spec.md` completely. Build the local Windows-first EasyAstroEnhance specified there using React/TypeScript and FastAPI/Python. Treat the fidelity requirements as mandatory. Implement in the six milestones, starting with a real JPEG upload-to-enhancement-to-comparison vertical slice. Keep the processing core independent of HTTP and UI. Add TIFF and stacked FITS through precision-preserving readers and a separate linear pipeline; never route them through an 8-bit conversion. Use no generative imaging, learned reconstruction, external reference images, cloud APIs or paid software. For each milestone, implement the code, run the required relevant checks and report working behavior and remaining limitations. Do not mark FITS support complete without a real FITS end-to-end test. Ask for a representative stacked FITS when needed; use clearly labeled synthetic FITS only for unit tests. Include direct brightness/shadows/highlights/black-point controls, optional gentle local contrast, star protection during stretching, supervised constant/planar background correction and reusable presets. Implement optional NVIDIA/CuPy acceleration for eligible stages with Auto/GPU/CPU settings, truthful backend status, bounded VRAM, classified CPU fallback and CPU/GPU equivalence tests. Verify on the RTX 5070 Ti before claiming target GPU support. Keep deconvolution, star reduction/removal and stacking deferred; the telescope supplies stacked FITS. Keep the main interface to upload, select enhancements, enhance, compare and download. Include exact setup/start/test commands and lock dependencies. Do not silently drop any acceptance criterion or introduce additional infrastructure without justification.

### Suggested `.github/copilot-instructions.md` content

- Follow this specification and its processing fidelity contract.
- Keep originals immutable and never add celestial content.
- Use typed API models and small pure processing functions.
- Preserve precision, channel interpretation, masks, metadata lineage and input-state distinctions.
- Keep main controls simple; hide algorithm parameters in Advanced.
- Write meaningful I/O, numerical and workflow tests; use real images for visual review.
- Record all applied operations and skipped steps; disclose unsupported inputs.
- Include every version 1 control in backend recipes, processing reports and acceptance tests; never ship a decorative slider.
- Keep presets free of per-image regions, masks and fitted models.
- Do not change output algorithms silently; increment pipeline versions.

## 13. Technical references

Documentation reviewed November 12, 2026. These support library selection and implementation details; the architecture, thresholds and presets above are proposed engineering choices. Check APIs against the locked versions during implementation.

- [Astropy FITS image data](https://docs.astropy.org/en/stable/io/fits/usage/image.html): scaling, storage and image-array behavior.
- [Astropy FITS handling](https://docs.astropy.org/en/stable/io/fits/): HDUs, headers, reading and writing.
- [tifffile project documentation](https://pypi.org/project/tifffile/): integer/float TIFF and image metadata support.
- [FastAPI uploaded files](https://fastapi.tiangolo.com/tutorial/request-files/): multipart uploads and UploadFile handling.
- [scikit-image restoration API](https://scikit-image.org/docs/stable/api/skimage.restoration.html): classical denoising and noise-estimation interfaces and assumptions.
- [scikit-image wavelet denoising example](https://scikit-image.org/docs/stable/auto_examples/filters/plot_denoise_wavelet.html): optional future classical denoising baseline.

The app implements common astronomical image-processing concepts independently. It does not execute PixInsight or claim equivalent algorithms, capabilities or output quality.

### Additional references for version 1.1

- [Siril background extraction](https://siril.readthedocs.io/en/stable/processing/background.html): sampled spatial background modeling. The app's restricted planar implementation above is an independent proposed design.
- [Siril StarNet workflow](https://siril.readthedocs.io/en/stable/processing/stars/starnet.html): context for deferred star separation/recomposition. StarNet is not a version 1 dependency.
- [RC Astro deconvolution technical manual](https://www.rc-astro.com/blurxterminator-technical-manual/): context for deferring blur restoration; no RC Astro integration or algorithm equivalence is proposed.

### GPU implementation references

- [CuPy installation](https://docs.cupy.dev/en/stable/install.html): supported platforms and CUDA package selection; verify against the chosen locked version.
- [CuPy multidimensional image processing](https://docs.cupy.dev/en/stable/reference/scipy_ndimage.html): candidate accelerated image operations.
- [CuPy Gaussian filter](https://docs.cupy.dev/en/stable/reference/generated/cupyx.scipy.ndimage.gaussian_filter.html): align filter semantics with the CPU implementation.
- [CuPy memory management](https://docs.cupy.dev/en/stable/user_guide/memory.html): allocator pools and memory limits.
