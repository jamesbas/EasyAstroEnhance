# How EasyAstroEnhance works

Use this as a starting point when people ask "how did you process this?" It's written in plain language and avoids
tables, so it pastes cleanly into a Facebook post. Pick the short or longer version, keep only the steps you used, and
fill in the details of your image at the bottom.

Want to try it? The [EasyAstroEnhance website](https://jamesbas.github.io/EasyAstroEnhance/) has the Windows 11 x64
installer and a quick-start guide. After installing, open **EasyAstroEnhance** from the Start menu.
It opens in your browser, but the photos are processed on your PC. No account or GPU is needed for normal enhancement.

---

## Short version (copy and paste)

I processed this with EasyAstroEnhance, a local app for bringing out faint detail in telescope photos. I can start
with a JPEG, TIFF, or a stacked FITS from my telescope, or combine individual exposures or stacks from several
nights first.

I pick a preset and click **Enhance**. The app can even out the sky background, reduce noise, and brighten faint
structure. I can fine-tune the contrast, colour, and detail, then compare before and after and save a new image.
My originals are never changed or uploaded. Optional AI cleanup is off by default, and the app doesn't add stars
or borrow detail from other photos.

---

## Longer version (copy and paste)

I use EasyAstroEnhance to bring out detail in my telescope photos. I can enhance a JPEG or an existing TIFF or FITS
stack without stacking again. If I have individual exposures or several nights of data for the same target, I can
combine them first. Everything runs locally and leaves my original files alone.

### Step 1: Stack, if needed

- **Individual exposures:** I open **Stack frames…** and point it at a folder, such as a Seestar `_sub` folder.
  The app can use calibration frames (darks, flats, bias or dark-flats) if I have them. It checks star sharpness and
  shape and sky brightness, explains why it skips poor or unaligned frames, and lines up the rest on the stars,
  even when the field has rotated. It repairs persistent hot or cold pixels, and averaging with outlier rejection
  can help remove passing satellite or aircraft trails. I can choose native size or optional 2× drizzle for suitable
  data; drizzle uses the captured frames, not AI upscaling.
- **Several nights:** I can combine already-stacked FITS images of the same target. The app aligns them even if the
  image scales differ and gives stacks with more exposure time more weight.

Stacking adds a new, unbrightened (linear) FITS to the image queue. Enhancement is a separate step unless I tick
**Enhance automatically when stacking finishes**.

### Step 2: Enhance for the kind of image I have

If the app asks **How was this image saved?** for a TIFF or FITS, I choose **Linear stack** (not yet brightened)
or **Already processed**. If I choose **I'm not sure**, it shows a preview but waits for me to confirm before
enhancing. JPEGs use the already-processed workflow.

- **Linear stack:** The app can correct uneven sky glow when it can reliably tell sky from the target, neutralise
  a colour cast in the background, and use suitable field stars as a guide for white balance. After reducing noise,
  it brightens faint structure (a *stretch*) and treats stars and bright cores more gently. The **Original** view
  of a linear stack gets its own basic display stretch so I can see what I'm comparing; the file itself is unchanged.
- **Already processed:** A JPEG or a previously stretched TIFF or FITS gets gentler brightness and contrast
  adjustments, background colour correction, and noise reduction rather than a full linear stretch.

I can choose **Natural**, **Vivid**, **Faint detail**, **Bright core (HDR)**, **Star field**, or **Seestar match** and
fine-tune with the sliders. If too many pixels become newly pure black or white, the app backs off the finishing
adjustments and retries once. If clipping is still above its limit, it flags the result for review.

### Optional colour and stretch tools

- **Enhance Hubble-style** gives suitable linear H-alpha/OIII colour FITS, such as a Seestar LP stack, a gold-and-teal
  look. It changes the display, not the linear data. It's a dual-band palette, not a true SHO image: the app doesn't
  infer a missing sulfur channel. Regular broadband images aren't eligible for this button.
- **Object Color** lets me adjust selected colour ranges in the galaxy or nebula. **Manual focus** lets me choose
  which brightness range gets the strongest stretch on a linear image.
- For prepared FITS data, **Combine channels…** can mix separate filter stacks into a new linear image. Optional
  catalog colour matching can refine relative RGB balance on a broadband image that already has a sky-coordinate
  solution, using a reference-star file I supply. The app doesn't solve the image or download a star catalog.

This is display enhancement, not absolute scientific calibration. Sharper-looking detail doesn't mean the telescope
recorded more resolution.

### Optional AI cleanup

All three tools are **off by default**. If I turn one on, the model runs on my own PC after a one-time download
(GPU when supported, CPU as a fallback). The usual non-AI method runs if the model is missing or can't run.

- **AI background extraction** (GraXpert) estimates uneven sky glow in a linear stack.
- **AI noise reduction** (GraXpert) reduces grain and colour blotches on linear or already-processed images.
- **AI star separation** (Seti Astro's Cosmic Clarity Dark Star) separates stars temporarily so the galaxy or nebula
  can be processed separately. The stars are added back into the final image. This is for linear stacks.

None draws new stars, fills in missing sky, or works from someone else's image. Strong cleanup can soften faint
features or dim a faint halo, so I check the before and after. The report names any model actually used.

### Step 3: Compare and share

I can compare the original and the result side by side or switch between saved results. I can export a PNG, JPEG,
16-bit TIFF, a before/after comparison JPEG, or a processed FITS for FITS input. The standard processed FITS export
omits location and observer fields; there's a separate full-metadata option if I want those included.

The result comes with a summary and a downloadable report that records the app version, settings, steps that ran
or were skipped, and why. That's the best place to check what actually happened before I describe the processing.

---

## Fill in the details for each post

Copy this block under your post, fill it in, and delete anything that doesn't apply. Use the stack summary and the
enhancement report rather than assuming every feature ran.

- Target: M__
- Telescope and filter: ___ (e.g. Seestar S30, IR-cut or LP)
- Input: telescope JPEG / linear TIFF or FITS stack / individual exposures / stacks from several nights
- Stacked in: telescope / EasyAstroEnhance / other / not applicable
- Exposure: ___ of ___ frames used (or ___ nights combined), ___ minutes of total exposure used
- Stacking options, if used: calibration frames ___; native size or 2× drizzle ___
- Enhanced in: EasyAstroEnhance v___, preset "___"; tweaks ___
- Optional tools actually used: Hubble-style / manual stretch / channel mixing / AI model(s) ___
- Other edits or notes: ___ (e.g. cropped in another app)

---

## Credits (include the models you used)

- GraXpert background and denoise models: [GraXpert Development Team and contributors](https://graxpert.com/),
  CC BY-NC-SA 4.0 (non-commercial use).
- Cosmic Clarity Dark Star star separation model: Seti Astro (Franklin Marek), MIT licence.

For more on supported inputs and processing methods, see the [README](./README.md).
