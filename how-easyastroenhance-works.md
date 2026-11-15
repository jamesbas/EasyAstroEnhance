# How EasyAstroEnhance works

Use this as a starting point when people ask "how did you process this?" It's written in plain language and avoids
tables, so it pastes cleanly into a Facebook post. There's a short version and a longer one. Pick one, then fill in
the details of your image at the bottom.

---

## Short version (copy and paste)

I built my own application, EasyAstroEnhance, that makes it simple to enhance any image, or to stack a set of
sub-frames first. Everything runs on my own PC, and my original files are never changed.

For this image:

1. **Stacking:** my Seestar sub-frames were checked one by one, and frames with clouds, trailing or blurry stars were
   thrown out. The rest were aligned on the stars and averaged. Hot pixels and satellite trails were removed along the
   way.
2. **Background:** light pollution and gradients were removed, and the sky was made a neutral grey/black.
3. **Colour:** colour was balanced using the stars themselves.
4. **Noise:** noise was reduced while the data was still "linear" (before brightening), which is when it works best.
5. **Stretch:** the image was brightened automatically, keeping bright cores from blowing out and stars from bloating.
6. **Finishing:** a touch of contrast, detail and colour was added. A safety check stops the app if it starts
   clipping blacks or whites.

It's one button with presets (Natural, Vivid, Faint detail, Bright core, Star field, Seestar match), plus a few
sliders if I want to tweak.

---

## Longer version (copy and paste)

I built my own application, EasyAstroEnhance, that makes it simple for me to enhance any image, or a set of images
for stacking. It brings together the steps people usually do across several free programs (Siril, GraXpert,
StarNet/Dark Star and so on) behind one "Enhance" button. Everything runs locally on my PC, and my original files are
never modified. Here's what it does.

### Step 1: Stacking (when I start from sub-frames)

I point it at the folder of sub-frames my Seestar saved (for example the "M 31_sub" folder), and it:

- **Reads every frame without touching the originals.**
- **Calibrates** with dark and flat frames if I have them. Either way, it finds and fixes hot and cold pixels (the
  sensor's stuck bright and dark dots).
- **Grades each frame.** It counts the stars and measures how sharp and round they are and how bright the sky is.
  Frames hit by clouds, wind, trailing or dawn are skipped, and it tells me why.
- **Aligns the frames on the stars.** It matches triangles of stars between frames, which also handles the slow
  rotation of the sky that alt-az scopes like the Seestar have.
- **Turns the raw colour sensor data into colour** (debayering).
- **Matches the sky level of every frame** and gives cleaner frames more weight.
- **Averages everything with outlier rejection.** Anything that appears in only a few frames, like satellite and
  airplane trails, is thrown out.
- **Optionally uses "drizzle" at 2× size** for finer detail when there are lots of frames.

The result is one clean "linear" stacked image (unstretched; it still looks dark).

### Step 2: Cleaning the data (while it's still linear)

- **Removes light pollution and gradients**, the uneven glow from city lights or the moon.
- **Neutralises the background colour** so the sky isn't green, red or brown.
- **Balances colour using the field stars**, so a typical star comes out close to white.
- **Reduces noise.** Grain and colour blotches are smoothed while fine detail and stars are protected.

### Step 3: Bringing out the object (the "stretch")

- **Brightens the faint signal automatically** so the galaxy or nebula shows up. It sets the sky at a natural dark
  level instead of crushing it to pure black.
- **Protects bright cores** (like the centre of M31 or the core of M42) so they don't turn into a white blob.
- **Stretches stars more gently** so they stay small and keep their colour.

### Step 4: Finishing

- **Adds a little contrast ("pop")** anchored on the sky, so the background doesn't brighten.
- **Enhances detail** in dust lanes and spiral arms only where there's real signal, never in the noise.
- **Boosts the colour** that's already there, without making the sky noisy.
- **Removes any leftover green cast** if there is one.
- **Runs a safety check.** If more than 0.1% of the image would be newly clipped to pure black or white, it
  automatically backs off and redoes the finishing.

### Optional AI tools (I can switch these on or off)

For some images I switch on three optional AI tools. They are the same trained models many people use in free
programs, running on my own graphics card:

- **AI background extraction** (GraXpert's model) removes light pollution even around big galaxies and nebulae.
- **AI noise reduction** (GraXpert's denoise model) removes grain and colour mottle.
- **AI star separation** (Dark Star from Seti Astro's Cosmic Clarity) temporarily lifts the stars off. The galaxy or
  nebula is brightened and sharpened on its own, then the stars go back on, kept small. The stars are never removed
  from the final image.

These are image clean-up tools, not "generative AI". Nothing is drawn from a text prompt or copied from someone
else's photo of the object. They work only on my own pixels. The app records which model was used for every image.

### What it never does

- It never adds stars, detail or structure from other images, and it never "paints in" anything.
- It never removes stars from the final image.
- It never changes my original files. Every enhancement starts again from the original.
- It never sends my images anywhere. No cloud, no accounts.

Every result comes with a report listing exactly which steps ran, which were skipped (and why), and the settings
used. That makes it easy to answer "what did you do?" and to repeat the same processing later.

---

## Fill in the details for each post

Copy this block under your post and fill it in. The numbers are shown in the app: the "Stacked N of M frames" note
under the viewer, and the summary under the enhanced image.

- Target: M__
- Telescope: ZWO Seestar S30 / S50 (filter: IR-cut / LP)
- Sub-frames: ___ × ___ s (___ kept, ___ skipped for clouds/blur), total ___ minutes
- Location / Bortle: ___
- Stacked in: EasyAstroEnhance (native size / 2× drizzle; darks/flats: yes/no)
- Enhanced in: EasyAstroEnhance, preset "___"
- Tweaks: Background ___, Stretch ___, Contrast ___, Colour ___, Detail ___, Noise reduction ___
- AI tools: background extraction on/off, noise reduction on/off, star separation on/off
- Anything else: (e.g. cropped in ___)

---

## Credits (worth mentioning when the AI tools are on)

- GraXpert background and denoise models: GraXpert Development Team (graxpert.com), CC BY-NC-SA 4.0, non-commercial
  use.
- Dark Star star separation model: Seti Astro, Cosmic Clarity (MIT licence).
- The stacking and processing steps follow the same well-known techniques used by free tools like Siril, GraXpert
  and PixInsight-style workflows, re-implemented in one app.
