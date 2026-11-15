# Improving EasyAstroEnhance for Seestar FITS

*Research notes, 15 November 2026. Engine reviewed: `PIPELINE_VERSION` 1.0.0.*

> **Status: implemented in engine 1.1.0 (recipe schema 3).** Every Section 8 item (P0, P1, P2) and decisions D1–D4 (as
> recommended) are in the app. See [Section 12](#12-implementation-status-engine-110) for what was built, the measured
> results on your M31, M45 and M42 stacks, and where the behavior differs from this plan.

## 1. Summary

**Goal:** one simple app that brings the key capabilities of the free Seestar workflows (Siril, GraXpert, VeraLux, AstroWizard, GIMP) behind a single **Enhance** button. It should produce outstanding detail and true colour, with output presets and optional tweaks. Section 2 is the product plan; the rest of the report is the evidence behind it.

Seestar stacked FITS files processed with EasyAstroEnhance (EAE) 1.0.0 looked worse than the JPG the Seestar makes by itself. We measured three of your stacks (M45, two M31) and reviewed the free tools Seestar owners recommend. The cause is mostly in how EAE renders linear data, not a missing "AI" step. Every finding below can be fixed with classical, deterministic processing that fits the fidelity contract.

| # | Finding (measured on your files) | Effect you saw |
|---|---|---|
| 1 | **The image is flipped.** Seestar FITS store row 0 at the top and have no `ROWORDER` keyword. EAE assumes bottom-up and flips them. Correlation with the Seestar JPG is 0.98 without the flip and 0.48–0.50 with it. | Output is upside-down and mirrored compared with the Seestar JPG. |
| 2 | **No neutral background.** Background neutralization is off by default and needs manual sky patches. The display black point comes from Rec.709 luminance, which is dominated by green, so blue and red sky sits below it. | Green, teal or cyan sky. Faint blue signal (M45 reflection nebula, M31 outer arms) is suppressed. Stars turn orange. |
| 3 | **Crushed black.** The black point is `sky − 1σ`. | 11.9–14.3 % of baseline channel values become pure black, against 0.04–0.23 % in the Seestar JPG. |
| 4 | **White point too low.** The white point is the 99.5th percentile of non-star luminance, about 340 ADU above the sky in data that runs up to 65,535. | 0.7–1.1 % of channel values clip to white: blown galaxy cores, white blobs around Pleiades stars. |
| 5 | **Background too dark.** | Sky median sits at 0.03–0.08, against 0.15 in the Seestar JPG. Typical targets are 0.12–0.25. |
| 6 | **Guardrail always fires.** Because of 3 and 4, it trips on every Seestar run. It halves stretch, saturation and contrast, then still flags "needs review". | Every run reports "Midtones brightened (reduced to limit clipping)" and colour "reduced". Effective saturation was 1.04. |
| 7 | **Star protection artifacts.** It works on a stretch that is already clipped. | Bright stars and the M31 core show flat grey discs or darker rings. |
| 8 | **Weak denoising.** It only works at a fine scale (σ 0.8 px luminance, 2 px chroma). | Low-frequency colour mottling and blotchy sky remain at the higher stretch the data needs. |

A classical prototype fixed findings 2–7. It used per-channel sky neutralization with a shared pedestal, a white point at sensor saturation, a VeraLux-style hyperbolic luminance stretch that fades highlights to white, an MTF to a 0.15 background, and protected saturation. Results on your M31 data are in the table below. Section 7 has the full numbers.

| Your M31 stack | Sky RGB median | Pure-black channel values | Clipped-white channel values |
|---|---|---|---|
| Seestar JPG (232 × 30 s) | 0.149 / 0.149 / 0.145 | 0.04 % | 0.006 % |
| EAE 1.0.0 Natural | 0.061 / 0.084 / 0.086 | 11.65 % | 0.90 % |
| **Classical prototype** | **0.156 / 0.151 / 0.149** | **0.21 %** | **0.004 %** |

The prototype matches the Seestar's tonal balance and keeps the M31 core. It also uses no learned processing. What remains after that is the "make it pop" finishing step: curves, saturation and multiscale contrast. The tools people use cover that step. Section 2 shows how all of these capabilities fit behind one Enhance button, and Section 8 lists the engineering work.

---

## 2. The goal: free-tool capabilities behind one Enhance button

**Target experience:**
1. Add a Seestar FITS.
2. Pick a look (preset).
3. Click **Enhance**.
4. Get an image with the object's real detail and colour, at least as good as a careful Siril/GraXpert/AstroWizard session.
5. Optionally fine-tune with a few plain-language sliders. Expert parameters stay under Advanced.

AstroWizard proves this is feasible: its nine steps are mostly one-click defaults, and users who stay on its "golden path" get good results. EAE can go further by **automating the decisions those tools leave to the user**. All parameters are chosen from measured image statistics and recorded in the processing report.

### 2.1 Capability map: free tools → EAE

| Capability (where users get it today) | EAE equivalent (classical) | Automatic in one-button? | Priority | Spec impact |
|---|---|---|---|---|
| Correct orientation (Siril `mirrorx` for Seestar) | Seestar row-order rule in the FITS reader | Yes | P0 | Bug fix |
| Gradient / light-pollution removal (GraXpert RBF, Siril background extraction, AstroWizard step 3, VeraLux Nox) | Grid-sampled sky with outlier rejection; low-order polynomial or smoothed RBF; abort when samples hit extended signal | Yes, with automatic skip | P1 | Amend §4 and §8 (automatic and higher-order gradients) |
| Background neutralization (Siril, AstroWizard 4a) | Per-channel sky offset to a shared pedestal | Yes | P0 | Amend §8 (currently supervised only) |
| Colour calibration (Siril SPCC/PCC, AstroWizard "true colours from stars") | Bounded white balance from field stars; skip with a reason when unreliable. SPCC is not planned (needs a plate solve and the Gaia catalogue). | Yes, bounded | P1 | Amend §2.6 wording (statistical, not photometric) |
| Remove green (Siril SCNR, AstroWizard Green-Be-Gone) | SCNR average neutral, lightness preserved | Yes, only when green excess is detected | P1 | None |
| Stretch (GHS, VeraLux HyperMetric Stretch, Siril autostretch, AstroWizard Stretch Wizard) | HMS/GHS luminance hyperbolic stretch with highlight convergence, auto-solved so nothing new clips, then an MTF to the preset's background level | Yes | P0 | Update §8 renderer text |
| Highlight / core protection (GHS HP, HDRMultiscaleTransform, masked core processing) | White point at saturation + highlight convergence; HDR multiscale core compression behind a lightness mask | Yes, when a bright extended core is detected | P0 / P2 | None |
| Curves, "Dynamic Pop", Darker Sky (AstroWizard step 8, GIMP, Photoshop) | Monotonic S-curve anchored at the sky level; sky-darkening control | Yes, by preset | P1 | None (existing tone controls) |
| Saturation / "Make it Pop" (AstroWizard, Siril `satu`, VeraLux Vectra) | Chroma boost above the background noise, faded near white, hue-preserving | Yes, by preset | P1 | Widen range |
| Noise reduction (GraXpert AI, NoiseXTerminator, Seestar AI Denoise) | Multiscale wavelet thresholding on linear data, stronger on chroma (Silentium-style) | Yes, strength from measured SNR | P1 (largest visible gap) | None (spec already names wavelets) |
| Sharpen / deconvolve (AstroWizard high-pass, AstroSharp, BlurXTerminator, GraXpert AI) | Richardson–Lucy with a star-fitted Moffat PSF, or high-pass with halo guard, gated by SNR | Only above an SNR threshold | P2 | Amend §2.8 (sharpening/deconvolution disabled in v1) |
| Local contrast (PixInsight LHE, VeraLux Revela) | À trous multiscale contrast with noise gate and star mask | Yes, by preset | P2 | None |
| Stars vs nebula handled separately (StarNet + recomposition) | Classical star mask → separate, gentler star stretch blended back. Never star removal or replacement. | Yes, by preset | P2 | None if no star removal or reduction |
| Edge-artifact crop (AstroWizard step 2) | Detect low-coverage edges and exclude them from statistics. No automatic crop (spec §2.3); optional manual crop. | Statistics only | P1 | Optional manual crop needs spec text |
| Stacking subs (StackingWizard, Siril, DSS) | ~~Out of scope: the Seestar stack is the input~~ Now built in: **Stack frames…** (§13) | — | — | Done (spec 1.4) |
| AI denoise, star removal, sharpening (StarNet, RC Astro, AstroSharp, Cosmic Clarity, GraXpert AI) | Not adopted: learned reconstruction violates fidelity rule 1. The classical rows above replace them. | — | — | See decision D1 |

### 2.2 What happens when you press Enhance

Each stage measures the image, chooses its own parameters, and either runs or skips with a recorded reason.

1. **Read and orient**, with the Seestar row-order rule.
2. **Measure:**
   - per-channel sky level and noise;
   - star list and star mask;
   - extent of extended signal;
   - low-coverage edges;
   - saturation level;
   - bright-core detection;
   - green excess.
3. **Linear clean-up:**
   - gradient model (skipped if the sky samples are not credible);
   - background neutralization to a shared pedestal;
   - bounded white balance from field stars (skipped if unreliable);
   - multiscale denoise, scaled to the measured SNR.
4. **Stretch.** Auto-solve the hyperbolic stretch factor D so the faint signal is lifted and nothing new clips; this is the same idea as VeraLux's "Calculate optimal Log D". Highlights converge to white. An MTF puts the sky at the preset's background level.
5. **Finish:**
   - SCNR if green excess remains;
   - the preset's S-curve and sky darkening;
   - protected saturation;
   - multiscale local contrast;
   - HDR core compression if a bright extended core was detected;
   - gentler star stretch.
6. **Check.** The clipping guardrail runs against the new frame. Source-saturated pixels are exempt.

Every automatic decision comes from **image statistics only**. Never use the `OBJECT` header or the target's name to decide how it should look (fidelity rule 2). Presets are user choices about *rendering style*, not about what the object looks like.

### 2.3 Presets by desired output

| Preset | For | Sky level | Stretch | Colour | Detail / contrast | Noise | Core / HDR |
|---|---|---|---|---|---|---|---|
| **Natural** (default) | Faithful, balanced result close to a careful Siril finish | 0.12 | Auto D, moderate | Saturation 1.15, gentle S-curve | Off / light | Auto, medium | Highlight convergence only |
| **Vivid** | The AstroWizard "Dynamic Pop" look the thread liked | 0.10 (darker sky) | Auto D | Saturation 1.35, stronger S-curve | Medium | Auto, medium | Auto |
| **Faint detail** | Dim nebulae, galaxy outer arms, short integrations | 0.15–0.18 | Auto D, deeper (b higher) | Saturation 1.25 | Light | Auto, strong | Auto |
| **Bright core (HDR)** | M42, M31 and other high-dynamic-range targets | 0.12 | Auto D, strong highlight protection | Saturation 1.2 | Medium, multiscale | Auto, medium | HDR compression on |
| **Star field** | Clusters and star-rich fields such as M45 | 0.10 | Gentle | Star colour preserved, white balance skipped if unreliable | Off | Auto, light | Highlight convergence |
| **Seestar match** | Side-by-side reference with the Seestar JPG | 0.15 | Linked STF-style | Saturation 1.1 | Off | Auto, light | Highlight convergence |

User-created presets keep today's rule: they store **intent** (levels, strengths, toggles), never per-image regions, masks, white-balance factors or fitted models.

### 2.4 Simple controls (main panel) and Advanced

The main panel has six sliders, each mapping to one documented parameter set:

| Slider | Controls |
|---|---|
| **Background** (darker ↔ brighter) | Target sky level and black floor |
| **Stretch** (gentle ↔ deep) | Stretch factor D and local intensity b, relative to the auto-solved value |
| **Contrast / Pop** | S-curve amplitude |
| **Colour** | Saturation amount; green removal follows automatically |
| **Detail** | Multiscale local contrast; sharpening only if approved (D2) |
| **Noise reduction** | Wavelet threshold scale relative to measured noise |

There is also one **Protect bright cores** toggle (HDR compression and highlight protection).

**Advanced** (collapsed, unchanged rule) exposes the expert parameters:

| Area | Parameters |
|---|---|
| Stretch | GHS D, b, SP, LP, HP; MTF midtone |
| Colour | White-balance factors, star-reference status, neutralization offsets; SCNR method and amount |
| Gradient | Samples, model, smoothing |
| Denoise | Wavelet layers and thresholds |
| Masks | Star-mask overlay; core-mask overlay |
| Processing | Device selection |

### 2.5 Decisions needed from you

| ID | Decision | Recommendation |
|---|---|---|
| D1 | **AI tools.** The biggest gap between free workflows and a classical engine is AI denoise (GraXpert, NoiseXTerminator, Seestar AI) and, to a lesser degree, AI sharpening and star removal. Your spec forbids learned reconstruction. | Keep the rule. Wavelet denoise plus a correct stretch covers most of the gap. Revisit only if visual review on your stacks shows it is not enough. |
| D2 | **Sharpening and deconvolution** are disabled in version 1 (§2.8). | Allow an SNR-gated "Detail" stage (RL deconvolution or high-pass with halo guard), validated for ringing. Keep star removal and star-size reduction disabled. |
| D3 | **Automatic background neutralization, gradient removal and white balance** are currently supervised or excluded (§4, §8). One-button needs them automatic. | Make them automatic with automatic skip, disclosure, and manual override. |
| D4 | **Default orientation.** Match the Seestar JPG (rows as stored), or the FITS convention. | Match the Seestar JPG, since that is what you compare against. |

Each decision needs a spec amendment and a `PIPELINE_VERSION` bump before implementation.

---

## 3. What the Facebook thread says

Source: the Seestar (Official ZWO Group) post *"Uggggh. Was so excited to try the post processing workflow for the first time…"* (9 November 2026, 93 comments).

The poster processed M42 (Orion Nebula) from an S50 Pro through StackingWizard and AstroWizard, with GraXpert and a free star remover, over four hours. The result looked worse than the Seestar's automatic image. The on-scope image had "a blown out core and is generally a little overcooked", but it had more punch.

**Consensus in the 75 visible comments and replies:**

- Almost everyone judged the **externally processed image better**. It had more detail and the core was not blown out. The on-scope image "looks artificial", "cooked".
- The external image was **under-finished**, not wrong. The usual fixes:
  - stretch more, with GHS or hyperbolic stretch;
  - add a gentle S-curve and slightly more saturation;
  - darken the background;
  - work the red and blue curves separately.
- **M42 is a high-dynamic-range target.** Keep the Trapezium core unblown while revealing the faint wings. Mask the core and process it separately, or use highlight protection.
- **Do not over-saturate.** Nebulae are much less colourful than people expect.
- **Integration time matters.** One commenter claimed under 10 hours is a waste. That is an exaggeration, but it reflects how much SNR limits stretch and colour.
- **Save every sub and process externally** once you are comfortable.

**Tools mentioned in the thread:**

| Tool | Cost | Classical or ML |
|---|---|---|
| StackingWizard / AstroWizard (Lukomatico) | Free | Mixed: classical core, optional ML plug-ins |
| GraXpert | Free | Classical background (RBF, spline, kriging) **and** ML (AI background, denoise, deconvolution) |
| "Free star remover" = StarNet2 | Free | ML |
| Siril | Free | Classical |
| VeraLux scripts for Siril | Free | Classical |
| GHS (generalized hyperbolic stretch) | Free (Siril, AstroWizard, PixInsight) | Classical |
| AstroSharp | Free | ML (probable) |
| RC Astro BlurXTerminator / NoiseXTerminator / StarXTerminator | Paid | ML |
| PixInsight | Paid | Classical core, ML plug-ins |
| GIMP, Affinity (now free), Photoshop, Lightroom / Camera Raw | Free / paid | General-purpose editors |
| Seestar app "AI Enhance" | Free | ML (undocumented) |
| DSS (DeepSkyStacker) | Free | Classical stacking |
| "Photon Rookie" YouTube tutorials | Free | — |

---

## 4. How each tool processes images

### 4.1 Seestar on-device output (your FITS and JPG)

- `Stacked_*.fit` and `DSO_Stacked_*.fit` are already **debayered, field-rotation-corrected, stacked, linear 16-bit RGB**:
  - three planes stored as `int16` with `BZERO=32768`;
  - `BAYERPAT='GRBG'` is still in the header but no longer applies;
  - there is no `CTYPE3` and no `ROWORDER`.
- Measured on your files:

  | Stack | Pedestal floor (ADU) | Sky (ADU) | σ per channel (ADU) |
  |---|---|---|---|
  | S30 Pro 4K: M31 232 × 30 s, M45 458 × 20 s | 1,536–1,552 | 1,580–1,670 | 9–31 |
  | 1080p DSO stack, M31 416 × 20 s | — | 453–465 | 4–6 |

  Star cores reach 65,535. The useful nebula and galaxy signal is only a few hundred ADU above sky.
- The sky has an uneven colour balance:
  - M45: green sky sits 1.2–1.4× above red and blue relative to the pedestal.
  - M31 232: R 1,632, G 1,659, B 1,667 ADU.
  - This happens because the data is not white-balanced.
- **Row order is top-down.** Siril's official Seestar script ends with `mirrorx_single` for this reason.
- The **Seestar JPG** is auto white-balanced, auto-stretched, and probably AI-denoised. Its sky median is about 0.15 with almost no clipping.
- ZWO documents the AI Enhance and AI Denoise controls (Star Reduction, Brightness, Contrast, Saturation, Denoise) but not their algorithms.

### 4.2 StackingWizard (Lukomatico)

- Stacks Seestar `Light_*.fit` subs. Hot pixels are repaired without darks, using moving stars as reference.
- Can measure vignetting from the "walk" when there are no flats, and removes each frame's own sky tilt or bowl.
- **Debayer** defaults to bilinear. VNG was tried and reverted because it raised noise and caused maze artifacts.
- **Registration** matches stars against a growing canvas. Optional 2× drizzle with an adaptive drop size.
- **Frame grading** uses sky glow, noise, star count, star size and trailing. Satellite trails are masked.
- **Integration** is a weighted per-pixel vote with Normal, Gentle or Strict outlier rejection. The exact maths is not published.

This is not relevant to EAE, which deliberately does not stack.

### 4.3 AstroWizard (Lukomatico): nine steps, in deliberate linear-first order

| # | Step | Method | Classical or ML |
|---|---|---|---|
| 1 | Load & inspect | Reads WCS and integration time. Warns if already stretched. | — |
| 2 | Crop | Artifact crop of 2.5–10 % of the edges. | — |
| 3 | Remove gradient | Built-in auto sky sampling and model (subtract for light pollution, divide for vignetting), or GraXpert. | Classical (GraXpert AI optional) |
| 4 | Balance colour | **Background neutralization**, then **"true colours from the stars"** (Gaia star colour calibration from the plate solution), then a magenta-star fix. | Classical |
| 5 | Sharpen | High-pass (≈0.2 / 0.4 / 0.7, radius 1.5 px) with a halo guard, or BlurXTerminator. | Classical (BXT is ML) |
| 6 | Reduce noise | GraXpert AI denoise or NoiseXTerminator, **before** the stretch. | ML |
| 7 | Stretch | "Stretch Wizard"; **GHS** dial with SP, LP, HP, D, b; Classic (factor 150 / 600); Deep (sky target ≈ 13 %). | Classical |
| 8 | Final polish | Curves (L, RGB, saturation, colour families). "Colour spells", including **Dynamic Pop**, a gentle finishing S-curve. Masked Saturation and "Make it Pop". Darker / Lighter Sky. Green-Be-Gone. Star removal (StarNet2) and screen recombination. | Mostly classical (StarNet is ML) |
| 9 | Export | — | — |

In the thread, users who liked their AstroWizard results said most of the work was in step 8: a Dynamic Pop curve, then the red and blue curves tuned separately.

### 4.4 Siril, all classical

| Function | Algorithm and defaults |
|---|---|
| **Background extraction** | Grid samples (20 per line). Samples rejected where brighter than `median + 1.0·MAD`. Model is a polynomial (degree 1–4) or an RBF thin-plate spline `φ(r)=r² log r` with smoothing 0.5. Subtract for additive gradients, divide for multiplicative ones. |
| **Colour** | *Background neutralization*: per-channel medians of sky equalized. *White balance*: coefficients from a bright-object reference. PCC and SPCC: star photometry against Gaia; SPCC uses sensor and filter curves. Both need a plate solve and a catalogue. |
| **Autostretch (STF)** | Shadows `c0 = mean_c(median_c − 2.8·MAD_c·1.4826)`. Midtone `m = MTF(target=0.25, median − c0)`. Output `MTF(m, (x−c0)/(1−c0))` with `MTF(m,x) = (m−1)x / ((2m−1)x − m)`. **Linked** mode keeps colour balance. |
| **Asinh stretch** | `(x−BP)·asinh(S·x)/(x·asinh(S))`, S = 1–1000. Applied to luminance and multiplied back into RGB, which preserves colour. Clip mode `rgbblend`. |
| **GHS** | Parameters D, b, SP, LP, HP (equations in Section 9.1). Colour and luminance modes preserve hue. Guidance: put SP just left of the histogram peak, b ≥ 6, increase D in small steps, lower HP to protect stars. |
| **SCNR / Remove Green** | Average neutral: `G′ = min(G, (R+B)/2)`. Lightness preserved. Applied after colour balance on stretched data. |
| **Saturation** | `satu amount bg_factor`: only pixels above `(median + σ)·bg_factor` are boosted. |
| **Deconvolution** | Richardson–Lucy, regularized by TV or a Hessian term, on **linear** data. The PSF comes from a Moffat fit to stars, or blind estimation. |
| **À trous wavelets** | B3-spline layers with per-layer weights, for sharpening and denoising. |
| **Star recomposition** | Starless and stars-only images, stretched separately, then screen-blended: `1 − (1−a)(1−b)`. |

### 4.5 GraXpert

- **Classical background** (RBF, spline, kriging):
  - Each sample is a sigma-clipped median over a box.
  - The model is computed at reduced resolution, then upscaled.
  - Correction is `img − bg + mean(bg)` or `img / bg · mean(img)`.
- **AI background**: an ONNX network sees a 256 × 256 thumbnail normalized by `(x − median)/MAD × 0.04` and predicts a smooth background.
- **AI denoise**: a 256 px tiled ONNX network. Pixels above a threshold pass through unchanged. Blend strength defaults to 0.5.
- **AI deconvolution**: stellar and object models.
- **Not usable in EAE:** the AI background, denoise and deconvolution are learned reconstruction (fidelity rule 1). The classical sample/RBF approach is usable.

### 4.6 VeraLux suite for Siril (classical; HyperMetric Stretch read from source)

**HyperMetric Stretch (HMS) v1.5.2.** This is the most directly useful reference for EAE:

1. **Anchor.** Find the luminance histogram peak (smoothed). The anchor is the last bin to its left whose count is below 6 % of the peak.
2. **Anchored luminance.** `L_a = Σ wᵢ·max(Cᵢ − anchor, 0)`. Weights are Rec.709 by default; sensor-specific weights are optional.
3. **Colour ratios.** `rᵢ = (Cᵢ − anchor) / L_a`.
4. **Stretch.** `L_s = [asinh(D·L_a + b) − asinh(b)] / [asinh(D + b) − asinh(b)]`, with D = 10^logD (default 100) and b = 6.
5. **Highlight convergence.** `k = L_s^3.5`, then `out = L_s·(r(1−k) + k)`. Dim pixels keep their colour; bright cores fade to white instead of turning into saturated colour blobs.
6. **Ready-to-use finish.**
   - Black floor at `median − 2.7σ`.
   - Linear scale to 0.98 using the 99th-percentile ceiling.
   - An MTF so the **median luminance equals 0.20**.
   - A soft clip above 0.98.
   - It warns if more than 0.1 % of pixels clip.

**Other VeraLux scripts:**

| Script | Method |
|---|---|
| **Silentium** | Linear-phase denoising: undecimated (stationary) db2 wavelets with a signal-probability gate. No denoising where signal is detected. |
| **Revela** | À trous micro-contrast with a MAD noise gate and a star energy mask against "raccoon eyes". |
| **Nox** | Gradient removal with a smooth "elastic membrane" fit on a coarse grid, protecting stars and nebulae. |
| **StarComposer** | Separate star stretch and composite. |
| **Vectra** | LCH hue-vector colour grading, luminance locked. |
| **Curves** | Akima-spline curves in L\*, LCH chroma or HSV saturation. |

### 4.7 ML tools (out of scope for EAE)

The following are neural networks and would violate fidelity rule 1 (learned reconstruction):

- **StarNet / StarNet2:** pix2pix-style encoder–decoder.
- **Cosmic Clarity:** PyTorch CNN.
- **RC Astro BlurXTerminator, NoiseXTerminator, StarXTerminator:** ML-powered.
- **AstroSharp:** described by reviewers as AI sharpening and denoising, with dark-ring artifacts on bright backgrounds.
- **GraXpert AI** features.
- **Seestar AI Enhance / AI Denoise.**

For each, EAE should use the classical counterpart instead (Section 2.1 capability map, Section 8 work items).

### 4.8 PixInsight classical tools (secondary sources; primary docs unreachable)

| Tool | What it does |
|---|---|
| **STF / HistogramTransformation** | Same MTF as Siril. |
| **ArcsinhStretch** | Colour-preserving luminance asinh. Siril's `asinh` is a port. |
| **HDRMultiscaleTransform** | À trous dynamic-range compression for M42 and galaxy cores, applied through a lightness mask. |
| **LocalHistogramEqualization** | CLAHE-like local contrast. |
| **MaskedStretch** | Iterative stretch, target background about 0.125. |
| **SCNR** | Same formulas as Siril. |

### 4.9 Photon Rookie free workflow (Siril → GraXpert → GIMP → AstroSharp)

1. In Siril: stack, Remove Green Noise, plate solve, then **SPCC** (Seestar profile with the LP filter or no filter).
2. **StarNet** split into starless and stars (linear).
3. **GraXpert** on the starless image: background extraction (smoothing 0.5), denoise 0.5–0.7.
4. **GHS** on the starless image in small repeated passes, then a linear black-point shift **with 0 % clipping**.
5. **GHS** on the stars (factor ≈ 7.5).
6. **GIMP:** saturation, exposure, shadows/highlights to tame cores, light sharpening.
7. **AstroSharp** on both layers. He says it helps only with very high SNR.
8. Siril **star recomposition**, crop, save.

### 4.10 The common classical pipeline behind all of these

1. **Linear phase:** crop edge artifacts → gradient model (subtract) → **background neutralization** → **colour calibration** (star or catalogue based) → [deconvolution] → [denoise].
2. **Stretch:** a colour-preserving hyperbolic stretch (GHS, asinh, HMS) or a linked MTF. Black point at the histogram foot (about median − 2.8 σ), background at 0.12–0.25, highlights protected (HP, rolloff, or white at saturation).
3. **Non-linear phase:** SCNR → curves (gentle S, darker sky) → background-protected saturation → multiscale local contrast and HDR core compression → [star recombination].

---

## 5. How EAE 1.0.0 renders linear FITS today

Code path: [pipeline.py](backend/app/processing/pipeline.py), [linear.py](backend/app/processing/linear.py), [color.py](backend/app/processing/color.py), [readers/fits.py](backend/app/processing/readers/fits.py).

1. **Read and orient.** [readers/fits.py](backend/app/processing/readers/fits.py) (line 224) flips rows unless `ROWORDER = 'TOP-DOWN'`.
2. **Shared normalization.** `u = x / scale`, offset 0, with `scale` = the 99.5th percentile of all channels ([linear.py](backend/app/processing/linear.py), line 54).
3. **Frame selection** (`derive_frame`):
   - `black = sky_L − 1σ`, on Rec.709 luminance (line 71).
   - `span` = the 99.5th percentile of non-star `L − black` (line 62).
4. **Display.** `t = asinh(k·s)/asinh(k)` with `s = (L − black)/span`.
   - Baseline k = 8. Natural k ≈ 20, Brighter k ≈ 45, Strong k ≈ 90, all before the guardrail halves them.
   - RGB is rebuilt as `t · (u − black)/(L − black)`, blended toward neutral within 3σ of black.
5. **Background** neutralization and planar correction exist, but are off by default and need confirmed sky patches ([recipe.py](backend/app/processing/recipe.py), line 45).
6. **Denoise:** gated residual shrinkage at σ 0.8 px (luminance) and 2 px (chroma), linear domain ([denoise.py](backend/app/processing/denoise.py)).
7. **Star protection:** reduces the *positive* tone delta where `star × excess` is high ([pipeline.py](backend/app/processing/pipeline.py), line 217).
8. **Saturation:** 1.08 / 1.12 / 1.20, then halved by the guardrail.
9. **Guardrail:** new black or white clipping above 0.1 % halves all strengths once, then flags review (lines 41 and 380).

## 6. Root-cause analysis on your data

### 6.1 Orientation (Finding 1)

Both M31 stacks match the Seestar JPG at correlation 0.982 and 0.975 when read as stored (row 0 at top). They match at only 0.496 and 0.48 when flipped, which is what EAE does.

The app therefore shows Seestar images **vertically mirrored**. This is a reflection, not a rotation, so it is also mirrored against the real sky. The FITS standard assumes bottom-up rows, but ZWO writes top-down without saying so. Siril's Seestar script works around this with `mirrorx_single`.

**Fix:** treat `CREATOR`/`INSTRUME` containing "Seestar" as top-down. Record the rule in the orientation note, and keep the export round-trip consistent.

### 6.2 Colour cast and suppressed blue (Findings 2–3)

The display black point is one luminance value, `sky_L − 1σ_L`. Rec.709 weights are 72 % green, so `sky_L` is close to the green sky.

On M45:
- The blue sky is 1,580 ADU and the green sky 1,602 ADU. The luminance black is about 1,590.
- Blue pixels at sky level therefore get a **negative** ratio, which is clipped to 0. The faint blue reflection nebulosity near sky level is pushed toward green or black.
- Stars render orange or yellow even though the Pleiades are hot B-type stars.

On M31 232, the red sky sits 27–35 ADU below green and blue, which gives the teal/cyan halo visible around the galaxy.

Placing black only 1σ below sky also makes about 16 % of sky pixels pure black (the Gaussian tail). That explains the 11.9–14.3 % of pure-black channel values in the baseline and the speckled, crushed background.

### 6.3 Highlights and the guardrail (Findings 4–6)

| Stack | Sky (ADU) | Display white (ADU) | Data max (ADU) |
|---|---|---|---|
| M45 | ≈ 1,600 | 1,930 | 65,535 |
| M31 232 | ≈ 1,659 | ≈ 2,500 | 65,535 |

Everything brighter than the display white saturates. Only the asinh's mild shoulder below it helps. So:

- The M31 core and the bright M45 halos become white discs.
- The baseline already clips 0.7–0.74 % of channel values to white.
- Any further stretch adds more new white and black clipping than the 0.1 % guardrail allows.

Report for M45 Natural, first pass: new black 0.37 %, new white 0.20 %. The guardrail then halved k (20 → 14) and saturation (1.08 → 1.04), and the run *still* ended as `needs_review`. The same happened in all five M45 runs and both M31 runs. This is why "Enhanced" looks barely different from, or worse than, the baseline.

### 6.4 Star protection rings (Finding 7)

Protection scales down the positive tone delta inside star masks. The baseline is already clipped at the core, while the enhanced curve is brighter in the wings. Protected cores therefore come out *dimmer than their own surroundings*, which shows up as grey discs and rings around M45's bright stars and a dark hole in the M31 core. The root fix is to stop clipping cores in the first place (Findings 3–4), not to tune the mask.

### 6.5 Noise and gradients (Finding 8)

**Noise.** Seestar stacks carry correlated, low-frequency chroma noise. A Seestar-appropriate stretch needs an MTF midtone of about 0.002–0.06, which is far stronger than EAE's current k, and noise at 4–30 px scales then becomes visible. EAE's fine-scale shrinkage cannot reach those scales. Popular workflows use AI denoise here; the classical answer is multiscale wavelet thresholding.

**Gradients.** These were small in the three stacks measured: corner-to-corner sky varied by less than 10 ADU. Light-polluted sessions, moonlight and alt-az edge vignetting will be worse, and the planar-only, manual model will not cover them.

---

## 7. Prototype evidence (classical only, not committed)

**Chain** (about 120 lines of NumPy/SciPy; a session scratch script, not in the repo):

1. Robust per-channel sky (iterative 3σ-clipped median) is subtracted, then a **shared pedestal** of 3·max σ is added. Sky becomes neutral and stays positive, so luminance ratios are not biased by noise.
2. Optional **bounded white balance from unsaturated field stars**: local-maximum detection, flux minus a local annulus, median ratio to G, clamped to ±25 %.
3. **White point = sensor saturation** (65,535 − sky), not a percentile.
4. **HMS-style luminance stretch**, `D = 10^2.6`, `b = 6`, with highlight convergence `k = L_s^3.5`.
5. **Linked MTF**: floor at median − 2.8σ, median luminance → 0.15.
6. Hue-preserving fit, then saturation ×1.3, faded out in the background and near white.

**Results:**

| File | Render | Sky RGB median | Pure-black ch. | White ch. | p99.9 Y |
|---|---|---|---|---|---|
| M31, 232 × 30 s (S30 Pro 4K) | Seestar JPG | .149 / .149 / .145 | 0.04 % | 0.006 % | 0.90 |
| | EAE baseline | .033 / .048 / .049 | 11.93 % | 0.74 % | 1.00 |
| | EAE Natural | .061 / .084 / .086 | 11.65 % | 0.90 % | 1.00 |
| | Prototype | .156 / .151 / .149 | 0.21 % | 0.004 % | 0.89 |
| M31, 416 × 20 s (1080p) | Seestar JPG | .149 / .141 / .141 | 0.23 % | 0.009 % | 0.91 |
| | EAE baseline | .027 / .040 / .041 | 13.33 % | 0.72 % | 1.00 |
| | EAE Natural | .061 / .082 / .083 | 12.66 % | 1.13 % | 1.00 |
| | Prototype | .154 / .156 / .149 | 1.86 % | 0.000 % | 0.91 |

**Visual assessment.** On M31 the prototype looks like the Seestar JPG:
- neutral grey sky;
- unblown core;
- visible dust lanes and M110;
- slightly warmer and with more contrast than the Seestar JPG;
- no teal halo and no core ring.

It is still a bit flat, which is the step-8 "pop" (S-curve plus saturation) that the thread recommends.

**Lessons from M45 about white balance:**
- A white reference from the brightest 10 % of pixels picked up the blue nebula and **removed** its blue (R×1.61, G×1.65, B×1).
- A naive star reference picked up the hot blue cluster members and **over-blued** the image (B×1.74).

White balance must therefore:
1. use only unsaturated **field** stars, away from extended signal, with a robust statistic;
2. be **bounded**, then fall back to "neutralize background only" and disclose it;
3. not be presented as photometric calibration.

Saturated star cores must converge to white. Rescaling saturated cores by their max channel produced blue-dot stars.

---

## 8. Recommendations

Rules that apply to every item:
- Each change alters output, so **increment `PIPELINE_VERSION`** in [recipe.py](backend/app/processing/recipe.py) (line 12).
- Add the new parameters to the recipe, report and acceptance tests.
- Nothing below uses learned, generative or reference-image processing.

Items marked **Spec** need an amendment to [astro-photo-enhancer-app-spec.md](astro-photo-enhancer-app-spec.md) first, because the current text forbids or defers them.

### P0 – fix what makes Seestar output worse (engine 1.1)

1. **Seestar row order.**
   - Detect `CREATOR`/`INSTRUME` ~ "Seestar" with no `ROWORDER`, and keep rows as stored.
   - Note the rule in `orientation_transform`, and keep export symmetric.
   - Test: the stacked FIT render correlates above 0.9 with the companion Seestar JPG.
2. **Automatic per-channel background neutralization in the linear path** (Spec §8: background is currently supervised-only).
   - Estimate per-channel sky by iterative σ-clipped median over valid, non-star, unprotected pixels.
   - Subtract it and add one shared pedestal.
   - This is an **offset** per channel, not a per-channel scale, so it keeps "do not normalize each channel separately".
   - Record the offsets. Disclose it as neutralization, not calibration.
   - Fall back to skipping it, with a reason, when the sky estimate is unreliable, for example frame-filling nebulosity with no clear histogram peak.
3. **Re-define the display frame:**
   - **Black**: Siril/STF style, `median − 2.8·σ` on luminance after neutralization, or the HMS histogram-foot anchor. It must clip well under 1 % of sky pixels.
   - **White**: from sensor saturation (BITPIX max minus pedestal) or the absolute data max, **not** the 99.5th non-star percentile.
   - **Stretch**: HMS/GHS luminance hyperbolic (`asinh(D·L + b)` form) with highlight convergence to white. Then an MTF that places median sky at the **preset's target background** (Natural ≈ 0.12, Vivid ≈ 0.10, Faint detail ≈ 0.15–0.18; Section 2.3).

     Drive the stretch from target and auto-solved D rather than from `k`.
   - Keep the baseline as a frozen "Seestar-like autostretch" (linked STF, target 0.15) so before and after are comparable. The current k = 8 baseline makes every original look crushed.
4. **Guardrail semantics.**
   - Measure *new* clipping against the new frame.
   - Exempt pixels already saturated in the source (`≥ 65,534`).
   - The guardrail should not fire on a normal Seestar stack. Add a regression test using your M31 and M45 stacks.
5. **Star protection.**
   - Once cores no longer clip, apply protection to the luminance *stretch slope*, not as a cut to the delta.
   - Or rely on HMS highlight convergence and remove the per-star delta cut.
   - Test: no star core is darker than its surrounding ring.

### P1 – one-button Enhance at "AstroWizard golden path" quality

6. **One-button orchestration.**
   - Add a measurement stage that drives all automatic decisions (Section 2.2), with a skip reason for each stage.
   - Add a stretch **auto-solver**: find D so the faint signal is lifted while new clipping stays under the guardrail. Search D, then fit the MTF to the target sky.
   - Record every chosen value in the report and recipe resolution.
7. **Output presets and simple sliders** (Sections 2.3 and 2.4).
   - Replace the strength buttons with presets: Natural, Vivid, Faint detail, Bright core, Star field, Seestar match.
   - Add six sliders that are offsets *relative to the auto-solved values*, so the button result is always the starting point.
   - Every slider maps to recipe fields, the report and acceptance tests (no decorative sliders).
8. **Bounded white balance from field stars** (Spec §2.6 and §8 say "no automatic photometric calibration"; this is statistical, not photometric).
   - Use median star colour ratios with factors clamped to [0.8, 1.25].
   - Exclude stars inside extended signal, saturated stars and crowded clusters.
   - Skip, with the reason reported, when the star reference is unreliable (M45-like fields).
   - Show the factors in Advanced.
   - Without a plate solver and Gaia, never call it SPCC.
9. **SCNR, average neutral** (`G′ = min(G, (R+B)/2)`, lightness preserved). Automatic when residual green excess is measured after the stretch; method and amount in Advanced.
10. **Finishing curve ("Pop").**
    - A monotonic S-curve anchored at the sky level and near white, plus a "darker sky" control.
    - It can reuse the existing shadows/highlights machinery in [tone.py](backend/app/processing/tone.py).
    - This is the step-8 operation the thread credits most.
11. **Saturation.**
    - Raise the range to about 1.1–1.5.
    - Use Siril's rule: only boost pixels above `(median + σ)·factor`.
    - Optionally do it in LCH chroma, with luminance locked (as Vectra does).
12. **Automatic gradient model** (Spec §4 defers higher-order gradients).
    - Grid sampling with `median + 1·MAD` rejection.
    - Low-order polynomial or heavily smoothed RBF, run in sanity mode.
    - Skip automatically when samples overlap extended signal.
    - Keep the supervised planar mode for manual control.
13. **Multiscale denoise.**
    - À trous or undecimated wavelet soft-thresholding per scale (Silentium-style), with a signal gate, run on linear data.
    - Stronger at chroma scales of 4–32 px; strength from measured SNR.
    - This is the largest visible gap against AI-based free workflows (decision D1).
    - The spec already names wavelet thresholding as the next denoise engine.
14. **Edge handling.** Detect low-coverage borders (alt-az field rotation, mosaics) and exclude them from every statistic. No automatic crop.

### P2 – detail (each needs its own validation)

15. **HDR core compression** (HDRMultiscaleTransform-like) for M42, M31 and other cores. Use an à trous large-scale residual compressed only where luminance is high, behind a soft lightness mask. Enabled automatically when a bright extended core is detected and the preset allows it.
16. **Multiscale local contrast** (Revela-like), replacing the single 24 px guided-filter band, with a MAD noise gate and a star energy mask.
17. **Richardson–Lucy deconvolution** with a Moffat PSF fitted to stars, TV-regularized, on linear data, gated by SNR (needs decision D2). Only after a validation suite for ringing and noise exists.
18. **Separate star and nebula stretch** with a *classical* star mask (detection plus PSF footprint), not StarNet. This means separate stretches blended by mask, never star removal or replacement (Spec §2.8).

### Not recommended

- AI denoise or sharpen (GraXpert AI, NXT, BXT, AstroSharp, Cosmic Clarity).
- StarNet/StarXTerminator star removal.
- Seestar AI Enhance.
- Gaia-based SPCC: it needs a plate solver, a catalogue, internet or large local data, and sensor curves, and the spec explicitly excludes catalogue-based calibration.

---

## 9. Proposed one-button linear pipeline (engine 1.1 sketch)

```text
x            = read_fits(rows as stored if Seestar)                      # Finding 1
valid, stars = masks(x);  edges = low_coverage_border(x)                  # stats exclude edges
sky_c, σ_c   = sigma_clipped_median(x_c[valid & ~stars & ~protected & ~edges])
[x           = x - gradient_model(x)]                                     # auto, skips if samples not credible
x            = x - sky_c + P,  P = 3·max(σ_c)                              # neutral, positive sky
[x          *= clamp(field_star_wb, 0.8, 1.25)]                           # auto, skips if unreliable
[x           = wavelet_denoise_linear(x, strength ∝ 1/SNR)]               # P1
processed_linear_fits = x                                                 # saved here

u     = x / (sat_level - min(sky_c) + P)                                  # white = saturation
L     = w·max(u - anchor, 0)        ;   r = (u - anchor)/L
D     = auto_solve(D | new clipping < guard, faint signal lifted)  · preset · slider
Ls    = (asinh(D·L + b) - asinh(b)) / (asinh(D + b) - asinh(b))           # HMS form; GHS in Advanced
rgb   = Ls · (r·(1 - Ls^p) + Ls^p)                                       # highlights → white
rgb   = MTF(m*, (rgb - floor)/(1 - floor)),  floor = med - 2.8σ,  MTF(m*, med) = target_bg(preset, slider)
rgb   = [SCNR if green excess] → pop_curve(preset, slider) → protected_saturation(preset, slider)
rgb   = [HDR core compression if bright extended core] → [multiscale local contrast]
rgb   = manual_tone(rgb) → hue_preserving_gamut_fit(rgb)
```

Record: `sky_c`, `σ_c`, `P`, edge mask, gradient status, WB factors and status, denoise thresholds, `anchor`, `D` (auto value and final value), `b`, `p`, `floor`, `m*`, `target_bg`, SCNR, HDR and local-contrast decisions, and the clip counts versus the source.

### 9.1 GHS equations (for the Advanced stretch)

Generalized Hyperbolic Stretch, from the GHS documentation, with parameters D (stretch), b (local intensity), SP (symmetry point), LP and HP (shadow and highlight protection).

**Base transform T(x):**

| Case | T(x) |
|---|---|
| b = −1 | `ln(1 + D·x)` |
| b < 0, b ≠ −1 | `(1 − (1 − b·D·x)^((b+1)/b)) / (D·(b+1))` |
| b = 0 | `1 − exp(−D·x)` |
| b = 1 | `1 − 1/(1 + D·x)` |
| b > 0, b ≠ 1 | `1 − (1 + b·D·x)^(−1/b)` |

**Full transform:**

| Range | Formula |
|---|---|
| SP ≤ x < HP | `T(x − SP)` |
| LP ≤ x < SP | `−T(SP − x)` (point symmetry about SP) |
| x < LP | Linear, with the slope of the previous segment at LP (protects shadows) |
| x ≥ HP | Linear, with the slope of the SP–HP segment at HP (protects highlights) |

The result is normalized to [0, 1]. Applied to luminance and multiplied back into RGB, it preserves colour. Siril's guidance: put SP just left of the histogram peak, b ≥ 6, increase D gradually, lower HP to protect stars and cores.

---

## 10. Validation plan using your data

**Fixtures** (`D:\Seestar\MyWorks`, read-only):

| Stack | Why |
|---|---|
| `M 31\Stacked_232_M 31_30.0s_IRCUT_20261108-210941.fit` | 4K galaxy, bright core |
| `M 31\DSO_Stacked_416_M 31_20.0s_20261108_214740.fit` | 1080p, different pedestal |
| `M 45\Stacked_458_M 45_20.0s_IRCUT_20251213-005308.fit` | Reflection nebula, hot stars: white-balance trap |
| An emission nebula (M42, IC 1805 or IC 434), a light-polluted session, and a `_mosaic` stack | Dynamic range, gradients, ragged edges |

**Acceptance metrics** (proposed; tune during visual review):

| Check | Proposed target |
|---|---|
| Orientation: correlation with the companion Seestar JPG | > 0.9 |
| Sky neutrality: \|R−G\| and \|B−G\| of display sky median | < 0.01 |
| Background: Natural median sky luminance | 0.10–0.15 |
| Black clipping: new pure-black channel values vs source | < 0.5 % |
| White clipping: new white outside pixels saturated in the source | < 0.05 % |
| Guardrail: firing on the fixtures above | Never |
| Star cores | No star core or galaxy core darker than its surrounding ring (radial-profile monotonicity test) |
| One button | Every preset produces an acceptable result on every fixture with **no** manual input; skipped stages carry a reason |
| Sliders | Each slider changes its documented parameter monotonically and is recorded in the recipe and report |
| Processed-linear FITS | Still saved before display-only steps; neutralization offsets and WB factors recorded and reversible |

**Visual review:** side-by-side with the Seestar JPG, at full frame and as 100 % crops of the core, faint arms or wings, and corners.

---

## 11. Sources

**Facebook thread:** Seestar (Official ZWO Group), post 1137775382368076, 9 November 2026 — https://www.facebook.com/groups/seestar/posts/1137775382368076/

**AstroWizard / StackingWizard:**
- Site — https://astrowizard.lukomatico.com/
- Changelog — https://astrowizard.lukomatico.com/changelog.html
- Community manual, Ed. 3 — https://astrowizard.lukomatico.com/guides/AstroWizard_StackingWizard_Manual_EN_Edition3.pdf

**Seestar FITS and AI tools:**
- Hawkesbury Astrophotography — https://hawkastro.blogspot.com/2024/05/seestar-s50-fits-output-images.html
- Akastroid — https://akastroid.com/blog/seestar-fits-guide/
- ZWO AI Enhance — https://us.seestar.com/blogs/seestar-guide/seestar-ai-enhance
- ZWO AI Denoise — https://www.seestar.com/blogs/tutorial/seestar-ai-denoise-tutorial

**Siril:**
- Seestar tutorial — https://siril.org/tutorials/seestar/
- Seestar script — https://gitlab.com/free-astro/siril-scripts/-/raw/main/preprocessing/Seestar_Preprocessing.ssf
- Background extraction — https://siril.readthedocs.io/en/stable/processing/background.html
- Colour calibration — https://siril.readthedocs.io/en/stable/processing/color-calibration/manual.html
- SPCC — https://siril.readthedocs.io/en/stable/processing/color-calibration/spcc.html
- Stretching (asinh, MTF, GHS) — https://siril.readthedocs.io/en/stable/processing/stretching.html
- Colour tools (SCNR, saturation) — https://siril.readthedocs.io/en/stable/processing/colors.html
- Deconvolution — https://siril.readthedocs.io/en/stable/processing/deconvolution.html
- Wavelets — https://siril.readthedocs.io/en/stable/processing/atrouwavelets.html
- Autostretch source — https://gitlab.com/free-astro/siril/-/raw/master/src/filters/mtf.c

**GHS:**
- PixInsight process documentation — https://www.ghsastro.co.uk/doc/tools/GeneralizedHyperbolicStretch/GeneralizedHyperbolicStretch.html
- Siril GHS tutorial — https://siril.org/tutorials/ghs/

**VeraLux:**
- Scripts folder — https://gitlab.com/free-astro/siril-scripts/-/tree/main/VeraLux
- HyperMetric Stretch source — https://gitlab.com/free-astro/siril-scripts/-/raw/main/VeraLux/VeraLux_HyperMetric_Stretch.py

**GraXpert:**
- README — https://raw.githubusercontent.com/Steffenhir/GraXpert/main/README.md
- Background extraction source — https://raw.githubusercontent.com/Steffenhir/GraXpert/main/graxpert/background_extraction.py
- Denoising source — https://raw.githubusercontent.com/Steffenhir/GraXpert/main/graxpert/denoising.py

**ML tools:**
- StarNet — https://github.com/nekitmm/starnet
- Cosmic Clarity — https://www.setiastro.com/cosmic-clarity
- RC Astro — https://www.rc-astro.com/
- AstroSharp — https://github.com/deepskydetail/AstroSharp
- AstroSharp review (Ian Morison) — https://www.ianmorison.com/astrosharp-astronomical-sharpening-tool/

**Photon Rookie:**
- Siril, GraXpert, GIMP and AstroSharp workflow — https://www.youtube.com/watch?v=--_CQhGJ-Fw
- Siril 1.4.0 workflow — https://www.youtube.com/watch?v=thfk5g3vL1I

**PixInsight HDRMT (practitioner article):** https://chadleader.wixsite.com/my-site/post/bringing-out-the-details-part-2-finding-hidden-structures-hdr-multiscale-transform-pixinsight

---

## 12. Implementation status (engine 1.1.0)

**Decisions taken:**
- **D1:** no AI or learned processing.
- **D2:** Detail is allowed; deconvolution is opt-in.
- **D3:** neutralization, gradient removal and white balance run automatically and skip themselves when unreliable.
- **D4:** Seestar files keep the telescope's orientation.

The spec has been amended (version 1.3).

| Item | Where | Notes |
|---|---|---|
| P0-1 Seestar row order | [readers/fits.py](backend/app/processing/readers/fits.py) | Engine 1.0 assets are re-prepared once at start-up. |
| P0-2 Neutralization | [linear_prep.py](backend/app/processing/linear_prep.py) | Sky is measured from the dimmer 75 % of the frame, so a large target does not tint it. |
| P0-3 Display frame / stretch | [stretch.py](backend/app/processing/stretch.py) | Baseline is a linked STF (sky 0.15). Enhanced uses an HMS-style stretch with highlight convergence. A color-confidence blend keeps the sky neutral. The black floor sits 5σ below the sky. |
| P0-4 Guardrail | [diagnostics.py](backend/app/processing/diagnostics.py) | A pixel already clipped in any channel of the original is not counted as new clipping. |
| P0-5 Star rings | [pipeline.py](backend/app/processing/pipeline.py) | Fixed by highlight convergence plus a gentler star stretch (P2-18). |
| P1-6 Orchestration and auto-solver | [pipeline.py](backend/app/processing/pipeline.py) | Two pixel groups with CPU analysis between them. Every decision is recorded in `processing.json`. |
| P1-7 Presets and sliders | [recipe.py](backend/app/processing/recipe.py), [LookControls.tsx](frontend/src/components/LookControls.tsx) | Six presets, six sliders, plus Protect bright cores. |
| P1-8 White balance | [linear_prep.py](backend/app/processing/linear_prep.py) | Field stars only; gains limited to ±25 %. |
| P1-9 SCNR | [finishing.py](backend/app/processing/finishing.py) | Runs only when green remains after balancing. |
| P1-10 Pop curve | [finishing.py](backend/app/processing/finishing.py) | S-curve anchored at the sky level. |
| P1-11 Saturation | [finishing.py](backend/app/processing/finishing.py) | Faded in above the sky noise; stays just inside the gamut. |
| P1-12 Gradient | [linear_prep.py](backend/app/processing/linear_prep.py) | Degree-2 robust polynomial. Skipped when there is too little sky or the gradient is negligible. |
| P1-13 Wavelet denoise | [denoise.py](backend/app/processing/denoise.py), [wavelets.py](backend/app/processing/wavelets.py) | Isolated dark defects are protected, so they are not spread into blobs. |
| P1-14 Edges | [linear_prep.py](backend/app/processing/linear_prep.py) | Excluded from statistics; never cropped. |
| P2-15 HDR cores | [finishing.py](backend/app/processing/finishing.py) | Runs only when a bright extended core is detected. |
| P2-16 Multiscale detail | [finishing.py](backend/app/processing/finishing.py) | Noise gate, local edge-energy roll-off, star-halo suppression. |
| P2-17 Deconvolution | [deconv.py](backend/app/processing/deconv.py) | Opt-in, experimental. Uses a Gaussian PSF measured from stars. |
| P2-18 Star stretch | [pipeline.py](backend/app/processing/pipeline.py) | Gentler stretch (D/8) at the same sky level, blended in the star mask. |

**Measured with the Natural preset** (sky level is a sigma-clipped median of the display; black and white are new clipping):

| Stack | Sky R / G / B | New black | New white | Guardrail |
|---|---|---|---|---|
| M31, 232 × 30 s (4K) | 0.120 / 0.121 / 0.121 | 0.005 % | 0.003 % | none |
| M31, 416 × 20 s (1080p) | 0.120 / 0.121 / 0.121 | 0.035 % | 0.000 % | none |
| M45, 458 × 20 s (4K) | 0.123 / 0.122 / 0.119 | 0.000 % | 0.004 % | none |
| M42, 77 × 30 s, LP filter (4K) | 0.120 / 0.122 / 0.121 | 0.003 % | 0.001 % | none |

Engine 1.0 flagged every one of these runs for review. GPU run times were 8–18 s per stack.

**Where the implementation differs from this plan, and why:**
- **Equal-weight luminance for the stretch.** The stretch uses the mean of R, G and B rather than Rec.709 weights. Strongly colored nebulae otherwise get under-stretched (Rec.709 weights green at 72 %).
- **Black floor at 5σ, not 2.8σ.** After denoising, the sky noise has heavy tails, so 2.8σ clipped about 1 % of pixels.
- **Stretch target is a constant.** The auto-solver places the 99.9th percentile of star-free signal at 0.88 (Protect bright cores on) or 0.96 (off). These are tuning constants and are recorded per run.
- **Red white-balance gain often hits its limit.** On M45 and both M31 stacks the red gain reached the 0.80 limit (the raw estimate was 0.73–0.79), because the IRCUT stacks' field stars come out red-heavy. Raise the white-balance limit in Advanced for full correction, or lower it for a warmer look.

## 13. Stacking (added after engine 1.1; spec amendment 1.4)

You asked for StackingWizard/Siril-style stacking inside the app, and for enhancement after stacking to be your choice.
**Stack frames…** takes a folder (a Seestar `…_sub` folder of raw subs, or a folder of stacked images from several
nights), plus optional darks, flats, bias and dark-flats. It does the classical Siril steps:

1. Calibration with median masters; the flat is normalized per Bayer site.
2. Hot and cold pixel repair.
3. Frame grading by star count, transparency, FWHM, elongation and sky level. Each skipped frame gets a reason.
4. Star alignment using triangles and RANSAC, which handles alt-az field rotation.
5. Bilinear debayer.
6. Background matching.
7. A noise-weighted mean with kappa-sigma rejection. 2× Bayer drizzle is optional.

The result is added as a new linear FITS. It is enhanced only if you tick **Enhance automatically when stacking
finishes**, which is off by default.

On `M 42_sub` (77 × 30 s):
- 65 frames were used. The 12 skipped frames were cloud at the end of the session plus one blurred frame.
- Alignment RMS was 0.40 px.
- 906 hot pixels were repaired.
- It took about 20 s (about 105 s with 2× drizzle).
- The result matches the telescope's own stack in orientation and framing, with more faint stars and nebulosity
  visible at the same stretch.

Code: [backend/app/processing/stacking/](backend/app/processing/stacking/). Tests:
[test_stacking.py](backend/tests/unit/test_stacking.py) and
[test_stacking_api.py](backend/tests/integration/test_stacking_api.py).

## 14. Optional AI tools (engine 1.2.0; spec amendment 1.5 revises D1)

After seeing the stacked M31, you asked for the AI tools from the free workflows. Three are built in as opt-in
switches, all off by default. Each runs the same model the free tool uses, fed the same way:

- **AI background extraction:** the GraXpert background model.
- **AI noise reduction:** the GraXpert denoise model.
- **AI star separation:** Cosmic Clarity Dark Star (the stars are always added back).

| Tool | Free tool it reproduces | Replaces |
|---|---|---|
| AI background extraction | GraXpert "AI" background extraction | polynomial gradient model |
| AI noise reduction | GraXpert Denoise (3.0.2) | wavelet denoise |
| AI star separation | StarNet / Dark Star with recomposition | star-mask blend |

Findings from the review on your data:

1. **Bulge mistaken for a star.** Dark Star treats M31's bright bulge as a giant star. Two fixes: remove the large-scale
   background before inference, and gate the star layer by structure size.
2. **Over-stretching.** AI-denoised skies fooled the auto-stretch into stretching 10–500× harder than classical, which
   amplified colour mottle. Fix: AI denoising counts as at most 2× cleaner when the stretch is chosen.
3. **Benefit.** Colour mottle drops 2.5× and the dust lanes are clearer, at the same overall look.

See [README](README.md#ai-tools-optional-engine-120-recipe-schema-4) and [docs/STATUS.md](docs/STATUS.md).
