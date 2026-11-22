# EasyAstroEnhance — Application Development Specification

Version 1.13 • November 22, 2026 • Prepared for Jaime Basilico

> **Amendment 1.13 (engine 1.7.2, stacker 1.1.0, recipe schema unchanged).** Stacked colour sub-frames are colour
> balanced to a neutral sky like the Seestar's own stacks (one recorded gain per channel, green 1; skippable in the
> stack dialog's Advanced). See §4 "Stacking", Subs pipeline.

> **Amendment 1.12 (engine 1.7.1, recipe schema unchanged).** AI sharpening no longer turns smooth, denoised areas into
> grain: its gate measures against the noise before any noise reduction, sharpens only fine structure that stands above
> that noise, and never makes a pixel darker than its neighbourhood was. See §4 "Amendment 1.12".

> **Amendment 1.11 (Edit export text and in-app help; no engine or recipe change).** **Edit export…** finds the image's
> sky position by itself when annotations need it (no trip to Advanced); captions get a font (four bundled OFL fonts),
> colour, optional dark box, and a position and size for the target name and the label separately; and a **Help**
> button opens a short how-to guide. See §4 "Amendment 1.11".

> **Amendment 1.10 (reversing steps; no engine or recipe change).** A user can take back what an enhancement did
> without reprocessing from scratch: **Remove a step** turns off one applied step of the current result (each step with
> its own switch or slider; the stretch and other core steps cannot be removed); **Undo / Redo** (also Ctrl+Z / Ctrl+Y)
> step back through settings changes, kept separately for each image; **Reset to defaults** returns to the Auto preset
> with every optional tool off; **Go back to this result** makes an earlier result the image's current one again; and
> **Delete…** removes a result after confirmation. Live preview shows the reversed settings at once. Outputs are
> unchanged, so `PIPELINE_VERSION` stays 1.7.0. See §4 "Amendment 1.10".

> **Amendment 1.8 (engine 1.6.0, recipe schema 9; implemented).** One-button polish and four output fixes.
> **Auto** becomes the default preset: it measures each image (bright core, faint extended signal, star density) and
> applies one built-in preset's look; the object's name is never used. Three automatic stages are added, each with an
> Advanced switch, a recorded reason when skipped and full disclosure: **cosmetic correction** of isolated coloured hot
> and cold pixels on linear stacks (broadband one-pixel spikes, which may be stars, are never touched), **star-fringe
> reduction** (only when bright stars have a measured blue/violet ring stronger than their surroundings) and
> **dual-band defaults** (star white balance and green removal are skipped for recognized H-alpha/OIII stacks, whose
> stars and teal OIII are not colour casts). A **Star color** Look slider boosts the existing colour of stars. Changed
> settings show as a **live preview** (not saved) built from a cached linear stage; presets can be compared as
> reduced-size quick looks; the panel opens in a **Simple** view; past settings can be restored; stacking folders can be
> browsed; and Edit export offers **Crop stacking edges**. Fidelity rules 3 and 8 are clarified. See §4 "Amendment 1.8".

> **Amendment 1.9 (engine 1.7.0, recipe schema 10, together with amendment 1.7).** Higher-end, still one-button:
> automatic **row/column banding** repair; a flexible **spline gradient** model for complex light pollution; finishing
> **large-scale structure** on stronger Contrast; classical **deconvolution** with a fitted Moffat PSF and TV
> regularization; a **Moon & planets** preset (surface display mode) chosen by Auto; **lucky-imaging video stacking** of
> Seestar RAW AVI recordings; **mosaic stacking** onto a canvas covering every panel; and **Import from Seestar** (a
> read-only MyWorks browser with one-click "add newest stack" / "stack sub-frames" / "stack video"). See §4
> "Amendment 1.9".

> **Amendment 1.7 (implemented in engine 1.7.0, recipe schema 10).**
> Four opt-in capabilities are added. Defaults and every built-in preset stay unchanged; each part is off until the
> user enables it, is skipped with a recorded reason when it cannot run, and is disclosed per run.
> **(A) Sky solution and built-in catalog colour:** verify a FITS header sky solution (WCS) against catalog stars, or
> solve offline from the header's pointing/scale hints when no valid WCS exists (no blind solving, no network); a pinned,
> downloadable star-colour catalog makes catalog colour a single **Accurate star colours** switch.
> **(B) Object annotations** on the separate Edit export copy only.
> **(C) AI sharpening** with the pinned Cosmic Clarity Sharpen models (MIT) as a fourth learned tool.
> **(D) Star size** (an explicit, bounded, display-only reduction of the AI-separated star layer) and **Starless / Stars
> layer exports** on request. Fidelity rules 1, 2, 3, 6 and 8 and §4 "Deferred" are amended. See §4 "Amendment 1.7".

> **Amendment 1.6 (engine 1.5.0, recipe schema 8).** **Star brightness** can explicitly omit the AI-separated
> stars in the enhanced display at 0%. **Edit export…** optionally reframes and labels a finished result as a
> separate sharing PNG/JPEG. Default enhancement preserves the usual star blend and source geometry. Neither
> feature changes the original or processed-linear data. See fidelity rules 3 and 8.

> **Amendment 1.5 (optional AI tools; revises decision D1).** At the user's request, three opt-in learned tools are
> added (engine 1.2.0, recipe schema 4): **AI background extraction** (GraXpert background model), **AI noise reduction**
> (GraXpert denoising model) and **AI star separation** (Cosmic Clarity Dark Star; the stars are added back by default). They
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
- Start with a conservative Natural preset. Advanced controls remain collapsed. *(Amended 1.8: the default preset is
  **Auto**, which picks one of the conservative built-in looks per image from measurements; the panel starts in the
  **Simple** view.)*
- Work from immutable originals; every adjustment starts from the source, not an earlier export.

## 2. Fidelity requirements

These are release requirements, not optional marketing promises:

1. Never call an image-generation service, diffusion model, generative fill, learned reconstruction, synthetic-star tool, super-resolution model or external image repository. *(Amended 1.5: the three opt-in AI tools of §4 "Version 1.3" — learned background extraction, denoising and star separation run locally on the image's own pixels — are the only permitted learned processing; they are off by default and disclosed per run. Text-to-image, diffusion, generative fill, super-resolution and reference images remain forbidden.)* *(Amended 1.7: opt-in **AI sharpening** with the pinned Cosmic Clarity Sharpen models of §4 "Amendment 1.7 (C)" is a fourth permitted learned tool under the same rules. It never changes image dimensions; super-resolution/upscaling models, including those published alongside it, remain forbidden.)*
2. Do not substitute reference photographs of the named object or use object identity to invent its appearance. *(Amended 1.7: numeric reference **catalogs** — star positions, magnitudes and colour indices, and deep-sky object positions, sizes and names — are permitted, opt-in local data. They may be used only to verify or derive a sky solution, to fit relative colour gains, and to place user-requested text annotations on a separate sharing copy. They never select a rendering style or change pixel values by object identity. A target name typed by the user may seed a solve with approximate coordinates; the solution must still be confirmed by matched stars.)*
3. Preserve field of view, dimensions, star coordinates, orientation and existing structures by default. Apply EXIF orientation once and document it. Do not crop, rotate, resize or remove stars automatically. A user may explicitly rotate, zoom/crop, pan and add text to a separate edited display export, leaving the original and regular exports untouched. *(Amended 1.7: on that separate edited export the user may also add object annotations, compass and scale bar overlays drawn from a verified or solved sky solution.)* *(Amended 1.8: Edit export may *suggest* a crop that excludes low-coverage stacking edges; it is applied only when the user clicks **Crop stacking edges**. Automatic cosmetic correction replaces only isolated one-pixel defects that cannot be real structure — a value in one colour channel far above its eight neighbours while the other channels are not, or a value far below all its neighbours — on faint background; one-pixel spikes present in every channel are kept because they may be undersampled stars.)*
4. Preserve originals byte-for-byte. Processing changes pixels; avoid claiming that every output pixel is an original measured value or that filtering guarantees preservation of all faint signal.
5. Keep edits reproducible with source SHA-256, pipeline version, algorithm settings, resolved per-file parameters and dependency versions.
6. Distinguish display enhancement from scientific calibration. Background neutralization and star-based white balance are not photometric color calibration; a sharper appearance is not additional measured resolution. Optional offline catalog color uses user-provided numerical RGB reference-star ratios on solved broadband FITS. This is relative color calibration, not reference-image processing or absolute flux calibration. *(Amended 1.7: the reference ratios may also come from the app's pinned built-in star-colour catalog, and the sky solution may come from a verified FITS header WCS or the app's offline hinted solve. The result is still relative color calibration through a documented, generic RGB passband approximation, not absolute flux calibration or camera-specific spectrophotometry.)*
7. Preserve burned-in telescope labels using explicit protected regions. Never reconstruct sky behind lettering.
8. No automatic star removal or morphological star-size reduction is performed. *(Amended 1.6: an explicit 0% Star brightness setting leaves out the AI-separated star layer in the enhanced display; any star signal the model missed may remain. The processed-linear data still contain the stars.)* *(Amended 1.7: an explicit **Star size** setting below 100% applies a bounded, centroid-preserving morphological reduction to the AI-separated star layer in the enhanced display only. On explicit request, **Starless** and **Stars** layer exports of a run that separated stars are allowed as separately labelled files. Neither is ever automatic or part of a built-in preset; the processed-linear FITS and regular exports keep all stars unless the user chose Star size or Star brightness.)* *(Amended 1.8: automatic **star-fringe reduction** only lowers the saturation of blue/violet/magenta hues in a narrow ring around bright stars, keeping luminance, and only when that ring's colour measurably exceeds a wider reference ring; **Star color** only raises the saturation of colour already present inside the star mask. Neither changes star size, position or brightness.)* *(Amended 1.3:)* Deconvolution is available only as an opt-in Advanced option on linear stacks (star-measured PSF, damped, SNR-gated, star cores excluded); the multiscale Detail stage is noise- and edge-gated and bounded. Both are disclosed per run.
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
  frames that fit the RAM budget; two-pass streaming otherwise). *(Amended — stack 1.1.0: colour sub-frames are then
  colour balanced like the Seestar's own stacks — one gain per channel, green 1, that makes the median sky of the dimmer
  half of the frame (4 × 4 block means) neutral, because raw camera colour is strongly tinted (a Seestar S30 sky through
  its IR-cut filter is ~1.4× brighter in red). It is skipped with a reason when the sky is not at least 5σ above zero in
  every channel or the gains fall outside 0.4–2.5, can be switched off in the stack dialog's Advanced section (camera
  colour kept), and is recorded in the stack report, `CBAL_R/G/B` header keywords and `HISTORY`. These are the
  bounded, recorded linear gains allowed by amendment 1.3; the enhancement's own neutralization and white balance still
  run afterwards.)*
- **2× drizzle (optional, subs only):** Bayer drizzle with a point kernel and bilinear weights of measured CFA samples only,
  rejection against the native statistics; output pixels no frame reached are filled from the upsampled native stack and
  the filled fraction is reported.
- **Sessions:** star registration at any scale, resampling onto the largest image, background matching, weights by
  integration time, kappa-sigma rejection from three images on.
- **Output:** float32 RGB (or mono) FITS in source units, `ROWORDER=TOP-DOWN`, `STACKCNT`, `LIVETIME`, `HISTORY`; pixels
  with no coverage are NaN (masked by the reader). The file becomes a new immutable original with state "linear stack".
  A stack report (frames used/rejected with reasons, calibration, registration, normalization, weights, rejection,
  timing, device) is stored with the stack.
- **Fidelity:** every output value is a weighted mean of measured, resampled pixel values (times the recorded per-channel
  colour-balance gain, when applied); nothing is synthesized. The
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
- **Star brightness (engine 1.5.0, recipe schema 8):** an opt-in multiplier (`ai.star_brightness`, 0.0–1.0) on
  the separated star contribution at display recomposition, after the gentler stretch. It requires successful
  AI star separation on a confirmed linear stack and leaves the processed-linear data unchanged. The default 1.0
  keeps the previous blend; 0.0 omits the separated layer. Existing saved settings are preserved. The run report
  records the factor used or why it was skipped.
- **Edit export… (engine 1.5.0):** a separate editor for a completed enhanced display. Preview and exports share
  the same rotation, zoom crop, pan and optional bottom-left caption. The target label is user-confirmed text,
  optionally filled from the selected FITS image's `OBJECT` field (with primary-header fallback). Render from the
  stored full-resolution 16-bit display, not the preview. Save a separate 16-bit PNG or sharing JPEG with edit
  settings and source run ID in file metadata, without copying original FITS headers or changing any existing file.
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

### Amendment 1.7 — sky solution, catalog colour, annotations, AI sharpening, star size and layer exports

Implemented in engine 1.7.0 with recipe schema 10, in one engine step together with amendment 1.9 (schema 3–9 recipes
and saved presets migrate with every new field off or neutral). Built-in presets never enable any of them. Each part is
disclosed in the processing report (requested, applied/skipped/inactive with a reason, parameters, timings) and, where
applicable, in FITS `HISTORY`.

*As built (engineering decisions recorded at implementation):*

- **Star catalog:** Gaia DR3 stars with G < 13.5 (about 11 million), built by `backend/tools/build_star_catalog.py`
  from the ESA Gaia archive (HEALPix-range queries split until none hits the anonymous 50 000-row cap) into the
  `EAESTARS` format of `app/processing/catalogs/stars.py`: 1° declination zones split into right-ascension cells no
  wider than 1°, brightest first, positions at J2016.0. Published as the data-only GitHub release `reference-data-1`
  (no application release); credit and CC BY-SA 3.0 IGO licence are shown in Settings → Reference data.
- **Object catalog:** OpenNGC `NGC.csv` and `addendum.csv` pinned at commit `be3cd6c`, CC BY-SA 4.0. Messier, NGC, IC
  and Caldwell names (Caldwell from OpenNGC's identifiers) resolve typed target names.
- **Solve:** header hints try the header pixel scale and also ½× and 2× (the Seestar S30 Pro header scale is off by a
  factor of two); verification counts the brightest 50 *detected* stars (detection already excludes most saturated
  stars; no separate saturation filter). Real Seestar stacks (M31, M42, M45, C 22) solve in about 2.5 s at 0.42–0.55 px
  RMS; their header WCS verifies at 0.73–1.34 px. The sky-solve endpoint is synchronous (it returns the solution, not
  a task ID) and runs in the worker with a 5-minute limit; with **Accurate star colours** on, a missing solution is
  computed automatically at enhancement time.
- **Colour transform:** BP−RP → effective temperature (dwarf sequence) → blackbody through Gaussian R/G/B passbands
  centred at 610/535/465 nm, normalized so G2V (BP−RP 0.82) is white; BP−RP 0–2.5 used. When more than 3× the minimum
  number of stars match, the fit uses the brighter half (at least 3× the minimum): faint stars' colours are mostly noise
  in short stacks. On real Seestar S30 IRCUT stacks the fitted gains agree across targets (R 0.76–0.81, B 1.15–1.17 for
  M 31, M 45 and a 4-frame C 22) and with field-star white balance on M 31 (within 0.03).
- **AI sharpening:** the four non-stellar radius models plus the stellar model; the non-stellar radius is half the
  measured median star FWHM, interpolated between the two nearest models.
- **Star size:** at the requested size the star layer is eroded by a flat disc (radius 1–4 px from half the median
  display FWHM of the separated stars) and each star's peak is restored by the ratio of local maxima before and after,
  never above the original layer. On a real M 31 stack the median star FWHM went from 5.9 px to 4.1 px at 70 % and
  2.8 px at 50 %.
- **Layer exports** are deferred exports (made on first download) listed under **More formats**: Starless and Stars
  PNG, Starless linear FITS and Stars linear FITS (processed-linear minus starless).

**(A) Sky solution and built-in catalog colour ("Accurate star colours")**

- **Sky solution per asset.** The solution is per-image data, like protected regions: stored with the asset and in each
  run report, never in a preset, never written into the original. Sources, in order:
  1. *Header WCS, verified.* A celestial WCS in the selected FITS HDU (ZWO Seestar stacks carry `RA---TAN-SIP`) is used
     only after verification: detected stars are matched to catalog stars projected through it. Initial engineering
     thresholds, to be tuned on real data and recorded: at least 12 unambiguous matches, RMS residual ≤ 1.5 px, and at
     least 50 % of the brightest 50 detected unsaturated stars matched. A header WCS that fails is reported and not used.
  2. *Offline hinted solve.* When no verified WCS exists, solve from hints: `RA`/`DEC` (or `OBJCTRA`/`OBJCTDEC`) and the
     pixel scale from `FOCALLEN` and `XPIXSZ` × `XBINNING`. EasyAstroEnhance stacks and channel mixes keep these hints.
     For files without hints (for example JPEGs) the user may type approximate centre coordinates and field width, or a
     target name resolved to coordinates through the bundled object catalog (fidelity rule 2).
     Detected stars are matched to catalog stars around the hint (search radius 1.5 × the field diagonal, scale ±15 %,
     any rotation, both parities) with the triangle-invariant + RANSAC matcher already used for stacking registration,
     then refined to a TAN projection (plus SIP order 2 when at least 60 matches support it and the residual improves).
     The same verification thresholds apply. No blind (hint-free) solving, no network service and no external solver
     executable are required.
  The solve runs in the worker as a cancellable analysis task, automatically once the catalog is installed and the
  asset is ready, or on request. The asset shows **Sky solution:** *from file (verified)*, *solved*, or *not available*
  with the reason. Processed-linear FITS exports may carry a solved WCS, marked `EAEWCS = 'solved'` with a `HISTORY` line;
  a verified header WCS is passed through unchanged.
- **Built-in reference data.** Two optional, pinned downloads managed like the AI models (fixed URL, size and SHA-256,
  stored under `<data>/reference-data`, removable in Settings), each with its licence, credit line and version recorded
  and shown:
  * *Star catalog:* positions, magnitude and colour index derived from Gaia DR3 by a documented, reproducible build
    script kept in the repository. Limit the magnitude so a typical Seestar field yields at least 50 usable stars at mid
    galactic latitudes while the download stays bounded (target ≤ 200 MB). Index it spatially so extracting one field
    is fast. Positions are used at the catalog epoch; the documented proper-motion error is negligible at Seestar pixel
    scales. Confirm the Gaia redistribution terms and credit (ESA/Gaia/DPAC, DR3 citation) before the first release.
  * *Deep-sky object catalog:* Messier/NGC/IC names, positions, sizes and position angles from an open catalog (for
    example OpenNGC), with its licence recorded. Used for annotations (B) and name-to-coordinate solve hints only.
- **Accurate star colours.** One switch (recipe `catalog_builtin`, default off), shown with the colour tools. For a
  linear, broadband RGB FITS with a verified or solved sky solution, the field's catalog stars are converted to
  reference `r/g` and `b/g` ratios through a documented, versioned transformation of the catalog colour index to a
  generic broadband RGB response, and then fed to the existing catalog-colour fit (robust WCS matching, gain bounds,
  disagreement checks). Require at least 20 matches for the built-in catalog. Dual-band, narrowband and channel-mix
  palettes stay ineligible, as for user catalogs. On any failure the bounded field-star white balance runs instead, with
  the reason. A user-imported CSV and the built-in catalog are mutually exclusive in one recipe. This is relative colour
  calibration through a generic passband approximation (fidelity rule 6), not camera-specific spectrophotometry.

**(B) Object annotations (Edit export… only)**

- Options in **Edit export…**, all off by default: **Label objects** (deep-sky objects whose catalog position falls inside
  the framed area, with a list to untick individual labels and an optional size/magnitude limit), **Compass (N/E)**
  and **Scale bar**. Available only with a verified or solved sky solution; otherwise disabled with the reason.
- Positions come from the sky solution transformed by the edit's rotation, crop and pan. Marks are thin ellipses
  (catalog size and position angle) or ticks plus text, drawn on the separate sharing copy after framing, like the
  existing caption. Regular exports, runs and originals are unchanged.
- File metadata records the annotation settings, the object catalog's SHA-256 and the labels drawn. Object identity
  places text only; it never changes pixel values (fidelity rule 2).

**(C) AI sharpening (fourth learned tool)**

- **Models:** Cosmic Clarity Sharpen (Seti Astro, Franklin Marek; MIT) from the project's GitHub releases:
  `deep_sharp_stellar_cnn_AI3_5s.onnx` (stars) and `deep_nonstellar_sharp_cnn_radius_{1,2,4,8}AI3_5s.onnx` (non-stellar
  detail). Record a fixed URL, size and SHA-256 for each file in the model registry; download only on request, as in
  amendment 1.5. The same release's super-resolution models are never listed, downloaded or used (fidelity rule 1).
- **Recipe:** `ai.sharpen` (default off), `ai.sharpen_amount` (0–1, default 0.5, non-stellar strength, the visible
  slider when on) and `ai.sharpen_stars` (0–1, default 0.5, Advanced; 0 skips the stellar model). The non-stellar
  radius model is chosen from the measured median star PSF radius and recorded.
- **Processing:** feed the models as their reference implementation does (tile size, overlap, normalization). Linear
  data use a temporary midtone stretch that is inverted exactly afterwards, as for star separation. Linear stacks:
  after noise reduction (classical or AI), inside the processed-linear stage, so the processed-linear FITS contains the
  sharpened values and names the models in `HISTORY`. Rendered images: after noise reduction. Blend the result by
  strength and by the deconvolution SNR gate (no sharpening of sky noise); saturated star cores pass through unchanged.
  When both AI sharpening and classical deconvolution are requested, AI sharpening runs and deconvolution is reported
  inactive. A missing or failing model skips the step with a reason; classical deconvolution then runs only if the user
  enabled it.
- **Disclosure:** as for the other AI tools (model id, file, version, SHA-256, licence, attribution, execution provider,
  timing, fallbacks, `learned_processing`). Report the sky noise before and after sharpening. "A sharper appearance is
  not additional measured resolution" stays in the scientific disclosure.

**(D) Star size and Starless / Stars layer exports**

- **Star size:** `ai.star_size` from 0.5 to 1.0 (shown as 50–100 %, default 100 % = unchanged), next to Star brightness.
  It requires successful AI star separation on a confirmed linear stack; otherwise it is reported as skipped with the
  reason. At display recomposition, after the gentler star stretch and before Star brightness, the display-domain star
  contribution is replaced by a strength-weighted blend of itself and a grey-scale morphological erosion. The
  structuring-element radius is chosen from the measured median star FWHM. Requirements: the star layer stays
  non-negative (no dark rings), star centroids move by at most 0.1 px on synthetic Gaussian stars, measured FWHM
  decreases monotonically with the setting and never increases, no new sources appear, and the starless layer and the
  processed-linear data are unchanged. The report records the setting, the structuring element and the median display
  star FWHM before and after.
- **Layer exports:** for a run in which AI star separation was applied, **More formats** offers, on request only and
  not in the default **Download all** set:
  * **Starless (display)** — the finished starless display before stars are added back, 16-bit PNG/TIFF;
  * **Stars only (display)** — the display star contribution as composited (after star stretch, Star size and Star
    brightness) on black, 16-bit PNG/TIFF;
  * **Starless linear FITS** and **Stars linear FITS** — the processed-linear split, `EAEKIND = 'starless-linear'` /
    `'stars-linear'`, `HISTORY` naming the separation model. Starless + stars equals the processed-linear array
    within float32 rounding.
  Each label states that the layers were made with learned star separation and that large or saturated stars may
  remain partly in the starless layer. The regular processed-linear FITS is never starless. Layers are stored with the
  run or re-rendered deterministically from it; their hashes are added to the report when first written.

### Amendment 1.8 — one-button polish and output fixes (engine 1.6.0, recipe schema 9)

Implemented. Schema 3–8 recipes and saved presets migrate with `auto_preset` off, `star_color` 0 and the two new
automatic stages on (they are measurement-gated and skip when not needed). `PIPELINE_VERSION` is 1.6.0.

**Auto preset (default).** The built-in **Auto** preset (`auto_preset: true`) is the default. Before processing, each
image is measured on a ~1 MP block-averaged copy shown with its frozen baseline display stretch: the share of the frame
with a smoothed star-free luminance above 0.75 (bright extended core), the share with extended signal more than 0.03
above the sky and that signal's median level, and the number of detected stars per megapixel. The rules, in order:
core share ≥ 0.2 % → **Bright core (HDR)**; extended share ≥ 7 % with median < 0.12 above the sky → **Faint detail**;
extended share < 0.5 % with ≥ 100 stars/MP → **Star field**; otherwise **Natural**. The chosen preset's Look and preset
Advanced values (core compression, star softening) then run exactly as if picked by hand; every other user setting
(automatic stages, tone, AI tools, colour tools) is kept. The report records the choice, the reasons in plain words and
the measurements; the run summary starts with "Auto: *preset* ·". The thresholds were calibrated on 22 real Seestar
targets (M31 and M42 → Bright core; NGC 7000, IC 1805, M33, M45, M101 and other nebulae and large galaxies → Faint
detail; C 22 IRCUT → Star field; M13, M51, NGC 281, Veil and a one-frame C 22 dual-band stack → Natural). Object names are never used (fidelity rule 2). With Auto
on, the Look sliders show the look Auto chose for the current image; moving a Look slider or an Advanced value turns
Auto off (Custom). Changing other settings keeps Auto.

**Automatic stages added** (Advanced → automatic stage switches; each skipped with a reason when it does not apply):

- **Repair hot and cold pixels** (`auto.cosmetic`, linear stacks). On the normalized linear data, before background
  and gradient work: a value is repaired with the median of its eight same-channel neighbours only if it exceeds that
  median by ≥ 8 σ of the channel's neighbour residual (or falls ≥ 8 σ below it), the most extreme neighbour carries less
  than 25 % of that excess (isolated), the neighbourhood lies within sky + 10 σ (faint background), nothing is
  saturated, invalid or protected, and — for hot pixels — the other two channels rise by less than 25 % of it in their
  own noise units (a coloured spike). Monochrome images get cold-pixel repair only. Reported: counts of coloured hot
  and cold pixels and values repaired.
- **Reduce star colour fringes** (`auto.halo_reduction`). Around stars whose display peak exceeds 0.6, a narrow ring
  (1–4 px outside the star mask) is compared with a reference ring (7–10 px). The step runs only with at least 10 such
  stars, a mean blue/violet/magenta excess of the narrow ring over the reference of at least 0.003, and a share of
  clearly coloured ring pixels at least 1.5 × the reference's. It then lowers the saturation of hues between −150° and
  −30° (blue to magenta) in the ring by up to 80 %, keeping luminance. Uniform nebulosity around stars cancels in the
  comparison, so reflection nebulae (M45) are left alone. Reported: the measurements and threshold.
- **Dual-band defaults** (no switch; follows the filter). For linear RGB stacks recognized as H-alpha/OIII dual-band
  (Seestar `LP`, `HaOIII`/`HOO` filter names, or the user's confirmation), star-based white balance and green removal
  are skipped with the reason: stars are not white through such a filter and green carries OIII signal. Background
  neutralization and gradient removal still run.

**Star color** (Look slider, 0–1, colour images only). Inside the soft star mask, saturation about each pixel's
luminance is raised by up to 1 + value (limited per pixel so no channel leaves [0, 1]); the sky and nebulae are not
touched and white saturated cores stay white. Built-in values: Vivid 0.3, Star field 0.5, others 0.

**Faster iteration (no output change).** Processing is split into a cached *linear stage* (reading, measurements, linear
clean-up, noise estimate, star masks) and a *display stage*. A run whose linear inputs (image, linear recipe fields,
backend and models) match a cached stage reuses it; the display stage then produces a result identical to a fresh run.
The worker keeps at most two stages within 20 % of system RAM; failed or GPU-fallback stages are never cached. The
report notes when the linear stage was reused.

- **Live preview.** With **Live preview** on (default), changing settings for an image that already has a result
  renders the new settings at full resolution (latest request wins; enhancement jobs are never interrupted) and shows
  it in the viewer labelled **Live preview (not saved)**. Nothing is stored as a run until the user clicks **Save this
  result** (Reprocess), which publishes exactly the previewed pixels. Previews live in the temporary folder and are
  removed with the image.
- **Preset quick looks.** **Preview presets on this image** renders each built-in preset on a ~1 MP block-averaged copy
  (CPU, AI tools omitted, ≤ 480 px thumbnails, labelled as a reduced-size quick look; Auto shows the preset it would
  choose). Clicking a thumbnail selects that preset.

**Interface.** The enhancement panel has **Simple** (preset, quick looks, Sky brightness, Stretch, Noise reduction,
live preview and Enhance; a line lists hidden settings that are on) and **All controls**; Simple is the default and
the choice is remembered. **Use these settings** in the result history restores the settings a result was made with
into the panel (nothing is reprocessed). **Stack frames…** gains **Browse…**: a read-only folder list (drives, common
folders, recently stacked folders and their sibling `…_sub` folders, FITS counts) — only directory listings are read.
**Edit export…** gains **Crop stacking edges**, which sets the framing to the largest centred window, at the image's
aspect ratio, inside the largest rectangle of the result free of invalid and low-coverage pixels (found on 8 × 8 pixel
blocks); disabled when there are no stacking edges or the window would need more than 4× zoom.

**Tests.** Cosmetic correction repairs coloured hot and cold pixels and never a broadband spike, bright structure,
protected pixels or a monochrome hot pixel; dual-band stacks skip white balance and green removal with reasons while
broadband stacks apply them; Star color changes only star pixels, keeps luminance and stays in range; fringe reduction
finds synthetic blue rings and keeps luminance, and reports nothing when the surroundings share the ring's colour; Auto
choices follow the measurement rules and keep other settings; the clean rectangle excludes edges; a cached linear stage
gives a display identical to a fresh run and is not reused when linear settings change; the live preview equals the
saved result; preset quick looks are cached and served only through the allow-listed file route; folder browsing is
read-only and token-protected. Browser tests cover the Simple panel, Auto's explanation, live preview and saving it,
restoring settings, quick looks and choosing a stacking folder by browsing.

### Amendment 1.9 — higher-end one-button capabilities (engine 1.7.0, recipe schema 10)

Implemented together with amendment 1.7. Every item is either measurement-gated (runs only when the image needs it,
otherwise skipped with the reason) or explicitly chosen; nothing adds content that was not recorded.

- **Row/column banding repair** (`auto.banding`, on; linear stacks, after the edge mask). Per channel, the mean of sky
  pixels (within 3 σ of the median) along each row and column is detrended by a 65 px running median. The profile's
  robust scatter must exceed 4× the scatter expected from noise alone (pixel noise × a measured spatial-correlation
  factor ÷ √pixels per row) and 5 % of the pixel noise; only then are the detrended offsets subtracted. Diagonal
  patterns are not handled. All five real Seestar stacks tested are left alone; synthetic read-out banding is removed.
- **Spline gradient model** (`advanced.gradient_model`: automatic / polynomial / spline). A thin-plate RBF surface
  through the sky boxes (evaluated on a 128 px grid) replaces the polynomial when chosen in Advanced, or automatically
  only when the polynomial's residual at the sky boxes exceeds 4× the noise expectation, at least 40 boxes exist and at
  least 80 % of the frame is empty sky — a flexible surface would otherwise follow faint nebulosity (on M 31, M 42 and
  M 45 it would have removed real signal, so the polynomial stays).
- **Large-scale structure** (no new control). When Contrast/Pop is above 0.3, a 64–256 px band (difference of Gaussians
  σ 32/128 px on a 1/8-size copy) of the star-free display luminance is added, gated at 5 σ of that band's sky scatter,
  with only a quarter of its negative lobe (the full lobe darkened M 31's outer disk and faint arms in review), capped
  at ±0.05 display units, scaled by (Contrast − 0.3) / 0.7 and by the clipping guardrail. Reported as
  `structure`.
- **Classical deconvolution upgrade** (`advanced.deconvolution`, still off by default). The PSF is a Moffat profile
  fitted to the stars (β bounded 1.2–10; kernel to 10⁻³ of the peak, radius ≤ 15 px); FWHM is also measured in a 3 × 3
  grid of zones and reported (diagnostic only — one PSF is used for the whole frame). Richardson–Lucy runs with total
  variation regularization (λ 0.002) and deringing that keeps values within the local minimum/maximum around stars, as a
  full-frame stage so tiled and full-frame results stay bit-identical.
- **Moon & planets** (built-in preset `moon-planets`; `advanced.surface_mode`, `advanced.fine_sharpen`). Surface mode
  sets the sky to black, does not lift midtones, lowers the white point (never below the bright-surface level) until the
  surface displays at 0.88, turns the star stretch off (a planet would be softened like a star) and — for the Moon only
  (bright disc ≥ 5 % of the frame) — balances colour so the median of the bright, unsaturated disc is neutral (gains
  0.5–2). Fine sharpening boosts the 1/2/4/8 px à-trous layers (gains 2.5/1.8/1.0/0.5 × amount) above 2 σ of the
  measured noise, capped at 0.15. The clipping guardrail ignores the deliberately black sky. **Auto** picks Moon &
  planets first when the image has fewer than 3 stars per megapixel and a bright core (≥ 0.05 %), or when the input is
  the app's own video stack (`EAESTACK = 'video'`: the Seestar records video only of the Moon, Sun and planets).
- **Lucky-imaging video stacking** (Stack frames… with a `.avi` path, or Import from Seestar → Stack video). Reads
  uncompressed 8/16-bit Seestar RAW AVI files (OpenDML continuation included) and the `.avi.txt` sidecar (Bayer pattern,
  object, date). Every frame is graded by the variance of the Laplacian of a 2 × 2-binned copy divided by its squared
  mean; frames dimmer than 70 % of the median are dropped; the sharpest 25 % (at least 20) are aligned to the sharpest by
  phase correlation with a sub-pixel peak (global translation only — no multi-point alignment), debayered and averaged.
  The report records frames used, the alignment and the share of the target's bright pixels at full scale; above 5 % it
  warns that the recording was over-exposed (detail there was never recorded). The result is a linear RGB FITS.
- **Mosaic stacking** (detected from Seestar `…_mosaic_…` sub-frame names or header pointings spread over more than
  0.1°; a checkbox in Stack frames… can override). The reference is the best frame of the central panel; frames that do
  not match it are matched to aligned frames of the nearest pointings and their transforms chained. Star count, star
  brightness and sky level are compared with the 9 frames pointing nearest (Seestar records about two frames per
  panel), but against at least 0.6 × the session's star count and brightness, so a region of the sky that is genuinely
  sparser is kept while a neighbourhood recorded through haze is still rejected. The
  output canvas is the union of all aligned frames (at most 6 frames' area); uncovered pixels are empty and reported;
  panels are levelled by the usual per-channel background offsets (no seam blending or per-panel gradient model).
  Real data: NGC 7000 (6 subs, 2 panels) → 1337 × 2150 in 5 s; IC 1805 (84 subs, 41 panels) → 52 frames used (the
  rest cloudy as the session ended), 2713 × 3113 in 50 s, no visible seams.
- **Import from Seestar.** Finds the MyWorks folder (remembered, or the parent of a recently stacked `…_sub` folder, or
  common locations on every drive), lists targets newest first from folder and file names only (`Stacked_…` /
  `DSO_Stacked_…` names give frames, exposure, filter and time; `Lunar`, `Solar`, `Planetary` folders list videos), and
  offers **Add newest stack** (the file is copied into the app like an upload; the original is only read), **Stack
  sub-frames… / Stack mosaic…** and **Stack video…** (the stack dialog opens pre-filled with automatic enhancement on).

**Fidelity notes.** A mosaic or video stack is an explicitly requested new image, like any stack; its field of view
is what was recorded (rule 3 applies to enhancement). Banding repair, the spline gradient model and surface colour
balance subtract or scale only smooth or one-dimensional backgrounds measured from the image itself. Fine sharpening and
large-scale structure amplify only structure measured above the noise.

**Tests** (`tests/unit/test_engine17.py`, `tests/unit/test_ai.py`): catalog round-trip and cones across RA 0 and the
pole; hinted solving of a synthetic field in both parities to < 5″ and < 0.5 px; header-WCS verification accepts the
true WCS and rejects a shifted one; the colour transform is monotonic with G2V white; banding is removed from
synthetic read-out offsets and clean noise is untouched; Star size keeps centroids (≤ 0.1 px) and peaks, shrinks the
half-maximum area and never brightens; layers recompose the display and keep the linear starless; AI sharpening with
identity models changes nothing and is disclosed; surface mode neutralizes a colour-cast Moon, keeps the sky black
and the disc unclipped with no star softening; a synthetic RAW AVI is read exactly and lucky stacking keeps the sharp
half and aligns it; a 4-panel synthetic mosaic covers every panel with chaining; the Seestar scan groups targets and
reads names only.

### Amendment 1.10 — reversing an enhancement step (no engine or recipe change)

Users asked for a way to take back an enhancement step. Results stay immutable; reversing works on the settings (which
create new results) and on which stored result is the image's current one. No processing output changes.

- **Remove a step.** Under a finished result, **Remove a step:** lists every step the run applied (or reduced) that has
  a switch or slider of its own, by the report's operation name, in the order it ran. Removing a step changes only the
  setting that turns it off — a switch goes off, a strength goes to 0 (Noise reduction, Contrast, Detail, Color, Star
  color, Fine sharpening, Hubble-style), Star brightness / Star size return to 100 %, Protect bright cores turns off
  bright-core (HDR) compression, Object Color resets, and Accurate star colours / a user catalog is cleared. Following
  the usual Auto rule, a Look or Advanced change switches the preset to Custom. Steps without their own setting (the
  stretch, large-scale structure, Moon surface colour balance) are not offered. A step already off in the panel shows as
  "(off)". Chips appear only for the image's current result and only while the image is not being processed; with Live
  preview on the result without that step is shown at once and **Save this result** stores it as a new run.
- **Undo / Redo.** Every settings change (sliders, switches, presets, Remove a step, Reset, Use these settings) is
  recorded per image (the selected image's id), up to 100 steps; a slider drag counts as one step (changes within 0.7 s
  merge). Ctrl/Cmd+Z undoes; Ctrl/Cmd+Shift+Z and Ctrl+Y redo — not while typing in a field or with a dialog open.
  Settings themselves stay shared by all images, as before; Auto's per-image look choice is not an undo step.
- **Reset to defaults** sets the built-in **Auto** recipe (all optional tools — AI, catalog colour, deconvolution,
  layer exports — off). It can be undone.
- **Current result.** Each image has a current result: the one chosen with **Go back to this result** in the result
  list, otherwise the newest. It is the result shown, downloaded and live-previewed against; going back also loads that
  run's settings into the panel. Re-enhancing with settings identical to an earlier run reuses that run and makes it
  current. Run numbers are never reused after a deletion.
- **Delete a result.** **Delete…** asks for confirmation, removes the run's record and files (never the original) and,
  if it was current, the next newest result becomes current. Not allowed while the image is queued or processing, or while any ZIP
  download is being built.
- **Retention.** Automatic clean-up never deletes an image's current result.

**API.** `PUT /assets/{id}/current-run` (`{run_id}`; 404 for another image's or an unknown run, 409 while the image is
busy) returns the asset with its new current result as `latest_run` (field name kept for compatibility).
`DELETE /runs/{id}` (409 while busy or zipping) returns `{deleted, current_run_id}`. The database gains
`assets.current_run_id` and `assets.last_serial` (added to existing databases on start).

**Fidelity.** Nothing new is computed and originals are untouched; removing a step only creates new settings, which are
processed and reported like any others.

**Tests.** Going back to an earlier result changes the asset's result and serial order; deleting the current result
falls back to the newest; run numbers are not reused; busy images are refused. Browser tests remove a step, undo and
redo it (buttons and keyboard), keep separate histories for two images, save the live preview, go back to an earlier
result, delete a result after confirming, and reset to defaults then undo.

### Amendment 1.11 — Edit export text, automatic sky position, in-app help (no engine or recipe change)

A user could not get annotations to work: they need the image's sky position, which was found only from All controls →
Advanced → Sky position or by Accurate star colours, and nothing in Edit export said so clearly.

- **Automatic sky position.** `POST /runs/{id}/edit-export/objects` returns `solve_needed: true` when no solution is
  stored for the image, the star catalog is installed and the image is ready. The dialog then calls
  `POST /assets/{id}/sky-solution` once (header WCS check, else a hinted solve from the header's pointing; a few seconds,
  shown as "Finding where this image points on the sky…") and refreshes the annotation options. A failed attempt is
  stored with the image like any solution and not retried; its reason is shown with the remedy (type the target's name
  under Advanced → Sky position). Without the star catalog the reason says to download it. Nothing in the image changes.
- **Caption style.** `EditExportIn` gains `text_style` (`font`: sans / serif / script / mono; `color` `#rrggbb`; `box`)
  and `target_place` / `label_place` (`position`: bottom-left / bottom-center / bottom-right / top-left / top-center /
  top-right; `size` 0.5–3 × the standard height of 4.5 % of the short edge). Captions sharing a position are stacked
  (target name first) and aligned to that side; a block shrinks as a whole until it fits, else `CAPTION_TOO_LARGE`.
  With the box, the text sits on the background darkened to 35 % (as before); without it, the text gets a dark outline
  (1/14 of its size). Blocks move clear of the compass and scale bar (the annotation overlay reports their areas) and
  of each other. The settings are recorded in the file's edit metadata. The label text and style are remembered in the
  browser for the next export; the target name is not.
- **Fonts.** Lato, PT Serif, Great Vibes and Space Mono (SIL Open Font License 1.1, unmodified) ship in
  `backend/app/fonts` with their licences and SHA-256 (`SOURCES.txt`). Pillow's built-in font lacked accented letters
  (é, ñ), ×, — and ′, so names such as "José" printed boxes; captions no longer use it, and the scale bar prints
  arcminutes as `'`.
- **Help.** A **Help** button in the top bar opens a how-to guide with short sections (quick start, changing the look,
  taking a step back, Seestar import and stacking, sky position / star colours / annotations, Edit export, AI tools,
  troubleshooting) and a link to the full guide on the project site.

**Tests.** Captions land at each of the six positions, take the chosen colour, box or outline and size, keep clear of
reserved areas, and refuse text that cannot fit; every caption font has accented letters; the edit-export API records
the style and rejects invalid colours and positions; the objects endpoint asks for a solve only once the star catalog is
installed and reports a stored failure with its remedy. Browser tests choose a font, colour, box, positions and sizes,
check that the label and style are remembered, and open Help. Checked on the real M 101 stack (2491 frames, header
pointing but no WCS): the dialog found the position by itself and drew 16 objects, the compass and the scale bar with
styled text.

### Amendment 1.12 — AI sharpening without grain (engine 1.7.1, recipe schema unchanged)

A user saw blotchy, speckled texture after zooming into IC 434 and M 101 enhanced with every AI tool on (AI sharpening
70–80 %). One setting at a time showed AI sharpening as the cause (Detail, classical or AI noise reduction made no
difference). Its gate compared brightness with the sky noise measured *after* noise reduction: AI noise reduction made
the sky about 2× cleaner per pixel, so faint nebula and galaxy glow counted as strong signal; and brightness alone cannot
tell a smooth bright area from detail — in IC 434's bright, smooth band the models added fine texture 4× the original
noise in that band (the denoised data had 0.6×). M 101's dust lanes also became strings of dark dots.

- **Noise reference.** Before AI sharpening, the luminance noise of the data before any noise reduction is measured
  (after cosmetic and banding repair): per pixel (σ 24 px Gaussian background removed, sigma-clipped) and in the 1–3 px
  band the models sharpen (difference of Gaussians σ 1 / 3, sigma-clipped).
- **Brightness gate.** As before (3 → 10 σ), but σ is the larger of the noise after and before noise reduction.
- **Detail gate.** The local RMS of the denoised luminance in the 1–3 px band (Gaussian σ 2 px) divided by the band
  noise before noise reduction: sharpening starts at 1.5× and is full from 4× (smoothstep, then a σ 1 px blur). The two
  gates multiply. Smooth areas, faint or bright, are left as noise reduction made them.
- **Deringing.** No sharpened pixel (per channel) may be darker than the darkest pixel of its 5 × 5 neighbourhood before
  sharpening — the same principle as the classical deconvolution's deringing. Peaks are not limited.
- **Report.** `snr_gate_noise`, `noise_before_denoise`, `detail_gate` (band, noise, thresholds), `share_sharpened` (mean
  gate over valid pixels) and `deringing`.
- Calibrated on the user's IC 434 (386 × 10 s, LP) and M 101 (2491 frames) stacks with their settings: the nebula band
  and galaxy glow are as smooth as without sharpening, the Horsehead's edge, spiral arms, core and stars are still
  sharpened (about 2 % of each frame), and the dark dots are gone. A lower threshold (1.0×) left speckle along the
  Horsehead's edge; a higher one (2.0×) removed nearly all sharpening of real structure.

**Fidelity.** Sharpening remains learned processing, disclosed as before; the change only restricts where it applies.
**Tests.** A synthetic stack denoised 5×: faint and bright smooth areas are not sharpened, a bright striped area is
fully sharpened, the engine 1.7.0 gate (no reference) sharpened all three, and a model that digs pits cannot go below
the 5 × 5 neighbourhood minimum.

### Deferred

Arbitrary cubes and multi-page stacks; ~~plate solving~~ blind (hint-free) plate solving *(amended 1.7: hinted solving
and header-WCS verification are in scope)*; absolute flux calibration; ~~star reduction/removal in exports~~
*(amended 1.7: explicit Star size and on-request layer exports are in scope; automatic star removal or reduction stays
excluded)*; additional learned processing beyond the four opt-in tools of amendments 1.5 and 1.7; super-resolution;
native installer; cloud hosting; accounts; remote mobile access; commercial billing.

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

*(Amended 1.3 — one-button Enhance.)* Preset menu: **Natural** (default), **Vivid**, **Faint detail**, **Bright core (HDR)**, **Star field**, **Seestar match**, **Custom**, and user-saved presets, each with a one-line description. Presets are rendering styles chosen by the user; nothing is inferred from the object's name. *(Amended 1.8: **Auto** is listed first and is the default; it chooses one of these styles per image from measurements, never from the name — see §4 "Amendment 1.8". The Look section adds a **Star color** slider (0–1) after Noise reduction, and the panel opens in a **Simple** view showing Sky brightness, Stretch and Noise reduction.)* Below the menu, a **Look** section has six sliders whose values the preset sets and that map to documented, recorded parameters:

| Slider | Range | Behavior |
|---|---|---|
| Background (shown as **Sky brightness**) | 0.04–0.25 | Display level of the median sky (MTF placement) |
| Stretch | −1…+1 | Shifts the auto-solved hyperbolic stretch factor by 0.75 decades per unit |
| Contrast / Pop | 0–1 | S-curve anchored at the sky and white (amplitude 0.8 × value, monotonic) |
| Color | 0–1 | Saturation 1 + 0.6 × value, protected below the sky noise and near white; unavailable for monochrome |
| Detail | 0–1 | À trous multiscale contrast, gated by per-scale noise and local edge energy, suppressed near star halos |
| Noise reduction | 0–1 | Wavelet gated shrinkage, amount 0.9 × value relative to the measured per-scale noise |
| Protect bright cores | on/off | Highlight-protecting stretch target and HDR core compression when a bright extended core is found |

The supervised **Manual sky regions** correction (constant / planar; labelled **Correct background from my sky samples** in the app) and **Preserve labels** remain as before. Advanced exposes switches for each automatic stage, the stretch on/off, opt-in deconvolution, exact values (stretch log D, b, highlight convergence, star softening, core compression, white-balance limit, gradient degree, green removal, denoise scales, detail scale, rendered midtone gain, manual background strength, deconvolution iterations), input state, protected regions and histogram diagnostics. *(The 1.2 table of switches with Gentle/Balanced/Strong buttons below is superseded.)*

*(Amended 1.7.)* None of these additions appear in the Look section, so the one-button path is unchanged.
**AI tools** gains **AI sharpening** (switch, Download, and a Sharpening strength slider when on; Star sharpening in
Advanced) and a **Star size** slider beside Star brightness, shown only when AI star separation is on for a linear
stack. The colour tools gain **Star colours: Field stars (automatic) / Accurate (catalog)**, with a status line
(catalog not installed → Download; sky solution from file, solved, or not available with the reason). Each image's
details show its **Sky solution** (centre, scale, rotation, matches, RMS) with **Solve now** and, for files without
hints, fields for approximate coordinates/field width or a target name. **Settings → Reference data** lists the star and
object catalogs with size, version, licence and credit, with Download and Remove. **Edit export…** gains **Label
objects**, **Compass (N/E)** and **Scale bar**. **More formats** lists the Starless/Stars exports only for runs that
separated stars.

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

*(Amended 1.7 — stage placement.)* Sky-solution verification or solving is an asset analysis task before the run;
it never changes pixels. In group A, catalog gains from **Accurate star colours** replace the field-star white balance
(same position), and **AI sharpening** runs after noise reduction, before the processed-linear array is saved, in place
of deconvolution when both are requested. **Star size** acts in group B at star recomposition, after the gentler star
stretch and before Star brightness. Layer exports read the stored separation results. Annotations are applied only in
Edit export.

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
| POST `/exports/{id}/cancel` | Stop building a ZIP; the partial file is removed |
| DELETE `/assets/{id}` | Remove app-owned data after explicit UI action; never external files |
| POST `/assets/{id}/sky-solution` | *(1.7)* Verify the header WCS or solve from hints (optional typed coordinates, field width or target name); waits for the worker and returns the solution summary |
| GET `/assets/{id}/sky-solution` | *(1.7)* Solution source, centre, scale, rotation, matches, RMS, or the reason none is available |
| GET `/reference-data`; POST `/reference-data/{id}/download`, `/cancel`; DELETE `/reference-data/{id}` | *(1.7)* List, download (pinned URL + SHA-256), cancel or remove the star and object catalogs (`{id}` may be a group: `stars`, `objects`) |
| POST `/runs/{id}/edit-export/objects` | *(1.7)* Catalogued objects inside an Edit export framing, and whether labels / compass are available |
| POST `/assets/import` | *(1.9)* Add images by local path (read-only source, copied like an upload) |
| POST `/stacks/seestar` | *(1.9)* Read-only summary of a Seestar MyWorks folder by target (remembered or found automatically) |
| POST/GET/DELETE `/assets/{id}/live-preview` | *(1.8)* Start (latest wins), poll or cancel a live preview of a recipe; nothing is saved |
| GET `/assets/{id}/live-preview/{live_id}` | *(1.8)* The live preview image (enhanced or fixed-mapping variant, optional ROI) |
| POST `/assets/{id}/preset-previews` | *(1.8)* Reduced-size quick-look thumbnails for up to 16 recipes |
| POST `/stacks/browse` | *(1.8)* Read-only folder listing for stacking (subfolders, FITS counts, recent folders) |
| PUT `/assets/{id}/current-run` | *(1.10)* Make one of the image's results its current result again |
| DELETE `/runs/{id}` | *(1.10)* Delete a result (app-owned run data only); the next newest becomes current if needed |
| POST `/runs/{id}/edit-export` | *(1.6; 1.11)* The framed sharing copy; *(1.11)* `text_style`, `target_place`, `label_place` |

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
- *(1.7 A)* A real Seestar header WCS verifies within the thresholds; a deliberately shifted or rotated WCS fails verification. Synthetic star fields with known WCS are solved from hints to sub-pixel RMS, including flipped parity and arbitrary rotation. Wrong hints, too few stars and a missing catalog fail with reasons. The original file is unchanged and no network access occurs. Built-in catalog colour recovers known synthetic channel gains, refuses dual-band/narrowband inputs, falls back to field-star white balance with a reason and cannot be combined with a user CSV. The catalog download rejects a corrupted file.
- *(1.7 B)* Annotation positions match synthetic WCS positions within 1 px after rotation, crop and pan; annotations appear only in the edited export; regular exports are byte-identical with and without annotations.
- *(1.7 C)* With synthetic ONNX models: exact tiling, the stretch round-trip, the SNR gate (sky unchanged), saturated-core pass-through, fallback when the model is missing, deconvolution reported inactive when both are requested, and no super-resolution model in the registry. Real-model tests check that dimensions are unchanged and the report and `HISTORY` disclose the model.
- *(1.7 D)* Star size: 100 % is identical to the current output; centroids move ≤ 0.1 px; FWHM is monotonic in the setting; the layer stays non-negative; the starless and processed-linear data are unchanged; the step is skipped without star separation. Layer exports: starless + stars equals processed-linear within float32 rounding; exports are offered only when separation ran; they are labelled and absent from the default ZIP.

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

*(Historical version 1 prompt. Where it differs from amendments 1.3–1.7 — for example on deconvolution, star
reduction and stacking — the amendments govern.)*

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

### Additional references for amendment 1.7

- [Cosmic Clarity](https://github.com/setiastro/cosmicclarity) (MIT): Sharpen stellar/non-stellar ONNX models and reference implementation; release assets under the `Windows` tag.
- [Gaia DR3](https://www.cosmos.esa.int/web/gaia/data-release-3): source catalog for star positions and colours; follow its credit and citation requirements.
- [OpenNGC](https://github.com/mattiaverga/OpenNGC): candidate open deep-sky object catalog for annotations and name hints; record its licence.
- [Calabretta & Greisen 2002, "Representations of celestial coordinates in FITS"](https://doi.org/10.1051/0004-6361:20021327) and the [SIP distortion convention](https://fits.gsfc.nasa.gov/registry/sip.html): WCS projection and distortion keywords.
- [Astropy WCS](https://docs.astropy.org/en/stable/wcs/): reading, fitting and writing celestial WCS.

### GPU implementation references

- [CuPy installation](https://docs.cupy.dev/en/stable/install.html): supported platforms and CUDA package selection; verify against the chosen locked version.
- [CuPy multidimensional image processing](https://docs.cupy.dev/en/stable/reference/scipy_ndimage.html): candidate accelerated image operations.
- [CuPy Gaussian filter](https://docs.cupy.dev/en/stable/reference/generated/cupyx.scipy.ndimage.gaussian_filter.html): align filter semantics with the CPU implementation.
- [CuPy memory management](https://docs.cupy.dev/en/stable/user_guide/memory.html): allocator pools and memory limits.
