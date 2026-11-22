# EasyAstroEnhance

A small **local** application that enhances telescope photographs (JPEG, TIFF, stacked FITS) with conventional
numerical image processing. Add files → pick a preset → **Enhance** → compare before/after → download.

**[Visit the website](https://jamesbas.github.io/EasyAstroEnhance/)** for the Windows installer and a beginner's quick-start guide.

* Everything runs on your PC (FastAPI on `127.0.0.1` + a React UI). No accounts, no cloud, no API keys.
* **No generative processing**: no diffusion/inpainting, no super-resolution, no synthetic stars, no reference
  photographs of the target. Enhancement uses only the uploaded pixels; optional sharing labels are added separately.
* **Optional AI tools (off by default):** AI background extraction, AI noise reduction and AI star separation run
  trained image-restoration networks (GraXpert, Cosmic Clarity Dark Star) locally on your GPU. They are opt-in per run,
  and every result names the model it used. See "AI tools" below.
* Originals are immutable (read-only copies, byte-for-byte; every run re-reads the original).
* Optional NVIDIA GPU acceleration (CuPy) for eligible stages with a complete CPU fallback.

Full specification: [astro-photo-enhancer-app-spec.md](astro-photo-enhancer-app-spec.md). Plain-language explanation for
sharing (e.g. with your processed images): [how-easyastroenhance-works.md](how-easyastroenhance-works.md).

## Install on Windows

Download `EasyAstroEnhance-<version>-Windows-x64-Setup.exe` from the Assets section of a
[GitHub Release](https://github.com/jamesbas/EasyAstroEnhance/releases) that includes the installer. Run it,
then open **EasyAstroEnhance** from the Start menu. It opens in your default browser. To quit, close its
console window or press **Ctrl+C** there; closing the browser tab alone does not stop the app.

The installer is for **Windows 11 x64 (Intel/AMD)**. It works offline and does not require administrator
access, Git, Python, Node.js, or an NVIDIA GPU. CUDA acceleration is not bundled. Optional AI model files
are still separate, opt-in downloads.

### Uninstall or update

1. Quit EasyAstroEnhance by closing its console window. Closing the browser tab alone does not stop it.
2. In Windows **Settings → Apps → Installed apps**, find **EasyAstroEnhance**, click **…**, and choose **Uninstall**.
   Do this from the same Windows account that installed it.
3. If you're updating, run the new installer under that same account.

Uninstalling removes the program and shortcuts, but keeps app history, presets, exports, and any downloaded AI
models in `%LOCALAPPDATA%\EasyAstroEnhance`. Leave this folder alone when updating. Your original photos outside
that folder are not touched.

**For maintainers:** On Windows x64, install the `uv` and Node.js prerequisites below and
[Inno Setup 7](https://jrsoftware.org/inno-setup/downloads). Run `.\scripts\build-installer.ps1` from
the repository root. It bundles Python 3.12, the locked production dependencies, the built frontend,
and app-local Visual C++ runtime DLLs. It writes the installer to `dist\windows\` and prints its SHA-256.

Before sharing, test on a clean Windows 11 machine and confirm you have the
[rights to redistribute the Visual C++ DLLs](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files).
Consider code signing: unsigned downloads can trigger Windows SmartScreen warnings. Upload the `.exe`
as a **GitHub release asset**, not a Git commit. Update the download link and version in [the website](./docs/index.html)
when a new installer is ready to share. GitHub Pages serves the `/docs` folder on `main`.

---------------------------------------------------------------------------------------------------

## 1. Requirements for running from source

| Need | Notes |
|---|---|
| Windows 11 (primary platform) | The Python core is portable; scripts are PowerShell. |
| [uv](https://docs.astral.sh/uv/) | `winget install --id=astral-sh.uv -e` — installs/uses the locked **Python 3.12** automatically. |
| Node.js 20+ with npm | `winget install OpenJS.NodeJS.LTS` (Node 24 / npm 11 were used). |
| Microsoft Edge | Only for the Playwright browser tests (no browser download needed). |
| NVIDIA GPU (optional) | Driver reporting CUDA 13.x. Nothing else is installed system-wide. |

Internet is needed **only** for the one-time dependency installation.

## 2. Setup (exact commands)

From the repository root in PowerShell:

```powershell
.\scripts\setup.ps1              # CPU-only: locked Python deps (uv sync --frozen) + npm ci + frontend build
```

Optional GPU acceleration (adds CuPy; CPU-only installs never need it):

```powershell
.\scripts\setup-gpu.ps1          # uv sync --frozen --extra gpu, then runs the GPU check
# or: .\scripts\setup.ps1 -Gpu   # same packages in one step
```

> Re-running `setup.ps1` **without** `-Gpu` syncs the environment to the CPU lock and removes the GPU packages.

The GPU extra installs `cupy-cuda13x[ctk]` (CuPy 14.2.0 plus pip-delivered CUDA 13 toolkit components such as NVRTC
that CuPy needs to compile its kernels). **Verified combination on the target PC:** Python 3.12.10, NVIDIA GeForce
RTX 5070 Ti (compute capability 12.0, 16 GB), driver 610.62 reporting CUDA 13.3, Windows 11. Do not install other
CuPy variants alongside it; no driver or system CUDA toolkit changes are made. Without `[ctk]` the device is detected
but the probe fails (“Failed to find CUDA headers”) — the app reports that truthfully and stays on CPU.

## 3. Start

```powershell
.\scripts\start.ps1              # http://127.0.0.1:8765, opens your browser
.\scripts\start.ps1 -Port 9000 -DataDir D:\EasyAstroData -NoBrowser
```

Equivalent manual command: `cd backend; uv run --frozen python -m app.serve`. Stop with **Ctrl+C**.

The running version is shown in the top bar (for example `v1.1.0`) and under **Settings → About**; every result's
`processing.json` also records the engine version that produced it. After updating, restart the app and reload the page.

App data (originals' copies, previews, runs, exports, SQLite database) lives in `%LOCALAPPDATA%\EasyAstroEnhance`
(override with `-DataDir` / `EASYASTRO_DATA_DIR`). **Settings → Clear local history** lists exactly what it removes; your
own files elsewhere are never touched. **Settings → Storage** shows how much space results use and can keep only the newest
N results per image (default: keep all). Limits (env overrides): 20 files per batch (`EASYASTRO_MAX_FILES`), 512 MiB per file
(`EASYASTRO_MAX_FILE_MB`), 100 megapixels (`EASYASTRO_MAX_MEGAPIXELS`). CPU processing uses up to 8 threads;
`EASYASTRO_CPU_THREADS` caps it (for example `2` on a shared or low-memory PC).

## 4. Test

```powershell
.\scripts\test.ps1               # backend pytest + frontend type-check
.\scripts\test.ps1 -E2E          # + Playwright browser tests (temporary server on port 8791, uses Edge)
.\scripts\test.ps1 -RealFiles    # only tests that use your real images (.\samplepics and your Seestar folder)
```

For an isolated CPU-only browser run, set `$env:EASYASTRO_CPU_ONLY='1'` before running
`.\scripts\e2e.ps1 -Specs color,intake`. This setting applies to the test process and its server, not a running copy of the app.

Direct commands: `cd backend; uv run --frozen pytest -q` · `uv run --frozen pytest -m "not gpu"` ·
`cd frontend; npm run typecheck; npx playwright test`.
Tests marked `aimodels` use the real downloaded AI models (default `%LOCALAPPDATA%\EasyAstroEnhance\ai-models`, or
`EAE_AI_MODELS_DIR`) on a real Seestar stack and skip when either is missing; all other AI tests use tiny synthetic
ONNX models. GPU tests (marker `gpu`) are **skipped automatically** when CuPy/CUDA is unavailable; CPU-only runs never claim GPU
support. Tests marked `realfiles` skip when their files are absent: `samplepics/`, and your Seestar stacks under
`EAE_SEESTAR_DIR` (default `D:\Seestar\MyWorks`; read-only — M31, M45 and M42 stacks are checked for orientation against
the telescope's JPG, a neutral sky on target and no guardrail). Synthetic images/FITS/TIFF in the tests are labelled
test fixtures and are never used as output content.

Benchmarks / review helpers: `cd backend; uv run python tools/benchmark.py` (writes `docs/benchmarks.md`) and
`uv run python tools/visual_review.py [--dir "D:\Seestar\MyWorks\M 31"] [--presets natural,vivid]` (writes comparisons,
100% crops and reports to `docs/visual-review/`, git-ignored).

Development servers: `cd backend; $env:EASYASTRO_DEV_ORIGINS='http://localhost:5173'; uv run python -m app.serve` and
`cd frontend; npm run dev` (Vite proxies `/api`).

## 5. How it works

```
frontend/ (React + TypeScript + Vite)         backend/app/
  UploadPanel, ImageQueue, EnhancementPanel,    api/         FastAPI routers (assets, jobs, runs/exports, presets, settings)
  CompareViewer, ExportMenu, dialogs            services/    coordinator (SQLite writes, durable queue), worker process,
                                                             previews (memory-mapped uint16), batch ZIP
                                                processing/  PURE core (no HTTP/DB/UI): readers, pipeline, background,
                                                             denoise, tone, color, local_contrast, star_protection, linear,
                                                             masks, tiling, export, backends (numpy / cupy)
```

* One **worker process** (spawn start method; CUDA initialised only there) does decoding, analysis and enhancement.
  The API process never runs CPU jobs; SQLite writes happen only in the coordinator. Jobs/items are persisted; a restart
  marks queued/running items **interrupted** (manual **retry** only). Cancellation is cooperative between stages/tiles.
* Same-origin security: Host/Origin allow-list (localhost only), cross-site requests rejected, mutations need an
  ephemeral per-start session token (kept out of URLs and logs).
* Results are written to `runs/<id>.partial`, validated (dimensions, finite values, PNG round-trip) and published with an
  atomic rename. Identical settings reuse the cached run (cache key: source SHA-256, engine + dependency versions,
  canonical recipe, per-file regions/background model, backend, precision); **Reprocess** always makes a new run.
  The exports of a run are written in parallel; the 16-bit display TIFF is made on first download (or for a ZIP) from
  the run's stored 16-bit display values, so its pixels are identical, and its size and SHA-256 are then added to the run.
* On the CPU, the pixel stages run on parallel tiles whose overlap covers every chained filter, so the result is
  bit-for-bit the same as one full-frame pass; independent analysis steps also run in parallel.

### Processing method disclosure (engine 1.7.2, recipe schema 10 — one-button Enhance)

Press **Enhance**. The default preset, **Auto**, measures each image (a bright extended core, faint extended signal,
star density) on a small binned copy and applies one of the built-in looks — Moon & planets, Bright core (HDR), Faint
detail, Star field or Natural; the choice and its reasons are shown above the sliders and recorded in the report (the
object's name is never used). You can also pick a **preset** yourself (Natural, Vivid, Faint detail, Bright core (HDR),
Star field, Moon & planets, Seestar match) or click **Preview presets on this image** for reduced-size quick looks of each. The panel opens in a
**Simple** view (Sky brightness, Stretch, Noise reduction); **All controls** adds Contrast/Pop, Color, Detail, **Star
color** and a *Protect bright cores* switch plus the tools below. Moving a Look slider makes the settings your own
(Custom). After a first result, changed settings are shown as a **Live preview (not saved)** in the viewer; **Save this
result** stores exactly that preview as a new run, and **Use these settings** in the result history brings back the
settings of an earlier result. To take something back: **Remove a step** under a result turns off one step it applied
(for example *Detail enhanced* or *Stars kept small*; the stretch itself can't be removed) and live-previews the result
without it; **Undo / Redo** (Ctrl+Z / Ctrl+Y) step through settings changes, kept separately for each image; **Reset to
defaults** returns to Auto with every optional tool off; **Go back to this result** in the result list makes an earlier
result the one shown and downloaded again; and **Delete…** removes a result after you confirm (never the original).
Everything else is measured from the image and recorded. The method follows the free tools Seestar owners
use (Siril, GraXpert's classical background tools, VeraLux HyperMetric Stretch, AstroWizard), using only their
classical algorithms — see [improve-enhance.md](improve-enhance.md). No 8-bit conversion exists for TIFF/FITS.

* **Linear (stacked TIFF/FITS confirmed “Linear stack”)** — two pixel groups with analysis in between:
  1. *Linear clean-up* (processed-linear array saved after this): **hot/cold pixel repair** (isolated one-pixel defects
     on faint background: a spike in one colour channel only, or a pixel far below all its neighbours; one-pixel spikes
     in every channel may be stars and are never touched) → **row/column banding repair** (only when the sky's
     row or column means scatter clearly more than noise allows) → optional supervised background → automatic
     **gradient** model (robust polynomial on sky boxes, or a flexible spline surface when the polynomial leaves a large
     residual on a mostly empty field; skipped with a reason when the target fills the frame or the gradient is
     negligible) → **background neutralization** (per-channel sky offset to one shared
     pedestal — an offset per channel, never a per-channel scale) → bounded **white balance from field stars**
     (median color of isolated, unsaturated stars; gains limited to ±25 %; skipped when unreliable, and for
     H-alpha/OIII dual-band stacks such as Seestar LP, whose stars are not white through the filter; not photometric
     calibration; or **Accurate star colours** from the Gaia catalog, below) → optional **Richardson–Lucy
     deconvolution** (Advanced, off by default; Moffat PSF fitted to the stars, total-variation regularized, deringed,
     SNR-gated, star cores excluded) or **AI sharpening** → **à trous wavelet noise reduction** (luminance + chroma, per-scale
     measured noise, structure/star/defect gated, coarse residual untouched).
  2. *Display*: **hyperbolic luminance stretch** `Ls = (asinh(D·L+b) − asinh(b)) / (asinh(D+b) − asinh(b))` with
     highlight convergence (bright cores fade to white instead of clipping), white point at the data maximum, D
     auto-solved so the brightest extended signal lands at 0.88 (0.96 with core protection off), then an MTF that puts
     the sky exactly on the Sky brightness level → gentler stretch inside confident star masks → HDR core compression
     (only when a bright extended core is found) → pop S-curve → manual tone → multiscale **detail** (noise- and
     edge-gated) → **large-scale structure** (with Contrast/Pop above 0.3: the 64–256 px band of galaxy arms and nebula
     filaments, gated above its noise and capped) → SCNR green removal (only when green remains; never for dual-band stacks, where green carries OIII)
     → protected saturation → **star color** (saturation of the existing colour inside the star mask only) → **star
     colour fringe reduction** (only when bright stars have a blue/violet ring measurably stronger than a wider ring
     around them; lowers that hue's saturation in the ring, keeping brightness).
  The linear stage is cached for the current image, so a display-only change (Look sliders, tone, colour) reruns only
  the display stage — with the same result as a fresh run.
* **Rendered (JPEG; display-referred TIFF/FITS):** background neutralization → wavelet noise reduction → rational
  midtone gain + MTF toward the Sky brightness level (limited to 0.6–1.6× of the image's own sky) → star protection →
  the same finishing tail.
* The **Original** for linear data is a frozen *linked* autostretch (STF style, sky at 0.15) derived once per asset, so
  the source's own color cast stays visible in the comparison.
* **Seestar FITS orientation:** ZWO writes rows top-down without `ROWORDER`; those files are kept as stored so they
  match the telescope's JPG (other FITS still follow the bottom-up convention).
* **Tone controls** compose into one monotonic transform in fixed order: black point → brightness (2^EV, ±1 EV) →
  shadows → highlights. Neutral offsets add nothing; monotonicity is validated.
* **Guardrail:** new black/white clipping (per-pixel transitions vs the original display; pixels already clipped in any
  channel of the original are not new) above 0.1 % halves the finishing strengths once and reruns; if still above, the
  result is flagged “review”.
* **Moon & planets** (preset; Auto picks it for a bright disc with almost no stars, and always for a video stack): the
  sky goes to black, the surface is kept in range instead of being lifted toward white, small-scale detail is
  sharpened above the noise, the star stretch is off, and the Moon's colour is balanced on its own disc (a planet keeps
  its colours).
* **Not implemented by design:** generative processing, super-resolution, blind (hint-free) plate solving, and cubes.

### Optional color and stretch tools

These controls are off or neutral in the built-in presets. You can still add a file and press **Enhance** without
opening any of them. Saved presets from recipe schemas 3–5 migrate with newly added options off.

* **Enhance Hubble-style:** on a linear H-alpha/OIII color FITS (including Seestar `LP`), click the button next to
  the normal Enhance actions. It processes only the image you're viewing, using a default 65% gold-and-teal
  blend. There is no CSV, WCS requirement or restacking. **Object Color → Hubble-style (dual-band)** has an optional
  strength slider and thumbnail preview. If the filter is unrecognized, use **Confirm Hα/OIII filter** there only
  if you know that's how the image was captured. Known broadband files (including `IRCUT`) are not eligible.
  The blend protects stars, faint sky and highlights and affects only the display, not the linear FITS. This is
  **Hubble-style, not SHO**: no sulfur signal is inferred. Normal **Enhance selected** stays unchanged.
* **Object Color:** adjust red/orange, green/teal or blue/violet independently. The mask favors existing color in
  extended signal and fades out over dark sky, detected stars and highlights. **Show color mask** displays a live
  thumbnail based on the original display; it is not an exact preview of the full enhancement. Enhance applies the
  adjustment after the regular display finishing. If stars cannot be protected reliably, the full run skips the
  adjustment and explains why. It never changes the processed-linear FITS.
* **Sky position** (All controls → Advanced → Sky position, or under Star colour): click **Find on the sky** to check the
  FITS file's own sky coordinates (WCS) against catalog stars, or work them out from the header's pointing and pixel
  scale (a typed object name such as *M 31* also works). Needs the star catalog (Settings → **Reference data**, one
  download). Offline: no plate-solving service or external program. Seestar stacks solve in a few seconds. You rarely
  need this button: Accurate star colours and Edit export's annotations find the position by themselves when needed.
* **Accurate star colours** (Star colour): one switch for linear broadband RGB FITS. The colour balance is fitted to the
  Gaia-measured colours of the stars in the frame (through the sky position, found automatically when needed) instead
  of assuming the average star is white. Relative colour calibration through a generic RGB passband model, not
  camera-specific spectrophotometry; when the catalog or a sky position is missing, normal white balance runs and the
  report says why.
* **Use my own catalog** (Star colour): on a solved, linear **broadband RGB FITS**, import a UTF-8 CSV with the header
  `ra_deg,dec_deg,r_over_g,b_over_g`. Supply ICRS coordinates in degrees and **positive linear reference flux ratios**
  in your intended RGB passbands, for stars in this field. Raw Gaia BP/RP magnitudes are not RGB ratios. It uses the
  FITS sky solution (WCS) to cross-match isolated, unsaturated
  stars, requires at least eight consistent matches, and fits relative RGB gains. If the WCS, catalog or matches are
  insufficient, the report says why and the normal field-star white balance still runs if enabled. No network is
  used. Imported CSVs (up to 2 MiB) stay in the app's `color-catalogs` directory; presets reference them by SHA-256.
* **Stretch method → Manual focus:** for linear data, pick the part of the brightness range where the stretch
  is strongest and tune its strength. Shadow and highlight color protection are separate options. The sky level is
  still anchored to **Sky brightness**. Run Enhance and compare with an earlier run; **Automatic** is still the default.
* **Combine channels…:** add and confirm your FITS masters as linear, then choose RGB, LRGB, HOO, SHO, SHO from
  two dual-band stacks, or Ha into broadband red. Assign each master to its role and optionally scale it. The
  first input defines the output grid; mismatched solved inputs are resampled using their sky coordinates.
  Without WCS, explicitly confirm that same-size inputs are already aligned. Only valid overlap is kept; other
  pixels are marked missing, not filled. Dual-band SHO assumes Ha/SII is in red and estimates OIII from green
  and blue; Ha into broadband uses a lighten blend, not continuum subtraction. A new, unenhanced linear FITS
  is added to the queue with its source hashes and mix settings in the header. Mixed-filter inputs keep their
  palette instead of receiving automatic stellar white balance or green removal.

### AI tools (optional)

Under **AI tools** in the Enhancement panel, four switches are all off by default:

| Tool | Model (licence) | Replaces | Works on |
|---|---|---|---|
| AI background extraction | GraXpert background 1.0.1, 218 MB (CC BY-NC-SA 4.0) | automatic polynomial gradient | linear stacks |
| AI noise reduction | GraXpert denoise 3.0.2, 478 MB (CC BY-NC-SA 4.0); strength = Noise reduction slider | wavelet noise reduction | all images |
| AI star separation | Cosmic Clarity Dark Star 2.1 / 2.1c, 15 MB each (MIT) | star-mask blending | linear stacks |
| AI sharpening | Cosmic Clarity Sharpen (stellar + non-stellar radius 1/2/4/8), 5 × 12 MB (MIT) | deconvolution | linear stacks |

* **Downloading models:** the first time you switch a tool on, click **Download** next to it, or manage all models in
  Settings → AI models. On Windows, downloads use native certificate validation so Windows can retrieve missing
  intermediate certificates when permitted. The files come from fixed URLs and are verified by SHA-256 before use.
  If GraXpert is already installed, its identical model files are copied instead of downloaded.
* **Where they run:** on a compatible GPU through DirectML on Windows, with the CPU as a fallback. AI processing can
  take much longer on the CPU, especially noise reduction on large images. For faster processing on a PC or VM
  without a compatible GPU, leave the AI switches off; standard enhancement is still available.
  In one CPU-only Windows VM test, enhancement took nearly 7 minutes with all three AI tools enabled versus
  24 seconds with AI off. Actual times depend on the hardware and the image.
  For comparison, **on the test PC's GPU** an 8 MP Seestar stack took about 1.5 s for background extraction,
  17 s for noise reduction, and 6–11 s for star separation. These are not CPU estimates.
* **GPU memory:** loaded models stay ready while images are being processed (a batch reuses them) and are released,
  with the GPU memory they hold (about 5 GB with background, noise reduction and star separation), once the app has
  been idle for 60 seconds. The next AI run then reloads them (about 3 s).
* **If a model is missing or fails:** the step is skipped with a reason and the classical step runs instead.
* **Star separation:** on a confirmed linear stack, enable **AI star separation** to show **Star brightness**.
  At **100%** (the default) the app keeps its usual star blend. Set **1–99%** to dim the separated stars, or set
  **0%** to leave that layer out altogether, then run **Enhance** again. Stars the model doesn't separate may remain,
  especially large or saturated stars. This uses the same Dark Star model and changes only the enhanced display and
  its exports, not the original or the processed-linear FITS. The report records the applied setting or why it was
  skipped. Existing presets keep their saved setting; older presets without this control keep the usual blend.
* **Star size** (with star separation): below 100% each separated star's glow is shrunk toward its core — centre,
  colour and peak brightness kept, never brighter — in the enhanced display only. On a real M 31 stack the median star
  width went from 5.9 px to 4.1 px at 70%.
* **Starless / Stars layers:** after a run with star separation, **More formats** offers Starless and Stars-only PNGs
  and linear FITS files (made when first downloaded; starless + stars equals the processed-linear data). Large or
  saturated stars may remain partly in the starless layer. They are never part of Download all by default.
* **AI sharpening:** sharpens fine structure and tightens stars blurred by seeing and focus; the strength slider sets
  galaxy/nebula sharpening and Advanced → *AI star sharpening* sets the stars. Only fine detail that stands out from
  the noise the stack had *before* noise reduction is sharpened, so smooth areas — faint nebula, a galaxy's glow, the
  sky — stay smooth instead of turning into grain (engine 1.7.1), and no pixel becomes darker than its neighbourhood
  was (no dark pits along dust lanes or rings around stars). Saturated star cores pass through. The report gives the
  share of the image sharpened and the sky noise before and after. The models'
  super-resolution variants are never used.
* **Stretch safeguard:** AI denoised data are treated as at most 2× cleaner when the stretch is chosen. Without this,
  the solver over-stretched and amplified colour mottle.
* **Processing report:** after the enhancement finishes, choose **More formats → Processing report (JSON)** below
  the image. For each AI step that ran, `execution_provider` shows the CPU or GPU used and `seconds` shows how long
  it took. The report also identifies the model file, SHA-256, and licence, and FITS HISTORY names the models.
  GraXpert's models are licensed for non-commercial use only.
* **Limits:** these networks predict pixel values. Background extraction can darken the faintest outer halo of a
  frame-filling galaxy, and full-strength denoising can soften the faintest structure. Compare before and after.

This is **display enhancement, not absolute flux calibration**: normal star-based white balance is not photometric
calibration. Optional catalog calibration fits relative RGB only, and a sharper look is not extra measured resolution. Every run’s `processing.json`
records source SHA-256, engine/dependency versions, requested vs applied recipe, every measured parameter (sky levels,
pedestal, gradient model, white-balance gains, stretch D/b/p/floor/MTF, detectors), skipped steps with reasons,
clipping transitions, noise estimate (with its limitations), backend/device/transfers/timings and export hashes.

### Stacking (Stack frames…)

Use **Stack frames…** (top bar, or the start screen) and click **Browse…** to pick the folder — the list shows drives,
common folders, recently stacked folders and the other `…_sub` folders next to them, with their FITS counts — or paste a
folder path, for example `D:\Seestar\MyWorks\M 42_sub`
(File Explorer: right-click the folder → *Copy as path*). Browsing only lists folders; nothing is opened or changed.
**Scan folder** shows what was found; **Start stacking** runs
it in the background with a progress banner and Cancel. The folder is only read. The result is added as a new linear
FITS image (`<target> - stacked N frames.fits`). It is **not** enhanced unless you tick *Enhance automatically when
stacking finishes* (off by default), so you can look at it and adjust the settings first.

* **Sub-frames** (raw Seestar `Light_*.fit`, CFA or mono): optional darks / flats / bias / dark-flats (separate folders
  or tagged by `IMAGETYP` in the same folder) → fixed hot/cold pixel repair (found on the master dark, or on a median of
  the lights) → frame measurement and grading (clouds, trailing, bloated stars, bright sky; each skipped frame has a
  reason) → star alignment (triangle matching + RANSAC; handles alt-az field rotation) → bilinear debayer →
  background matching → noise-weighted average with kappa-sigma rejection (removes satellite/plane trails) → colour
  balance to a neutral sky, like the Seestar's own stacks (one gain per colour, green unchanged; raw Seestar camera colour
  is ~1.4× red — on 117 IC 1805 subs the gains were red × 0.71, blue × 1.03; skipped with a reason when the sky is too
  dark; Advanced → untick to keep camera colour; recorded in `CBAL_R/G/B` and the stack details).
  Output: native size, or optional **2× drizzle** (Bayer drizzle; uncovered pixels are filled from the native stack and
  the fraction is reported).
* **Stacked images from several nights** (a folder of Seestar `Stacked_*.fit` of one target): aligned at any scale,
  resampled onto the largest image, background-matched and averaged, weighted by integration time.
* Debayering and resampling use the NVIDIA GPU when available. Measured on the target PC: 77 Seestar S30 subs
  (1080 × 1920, 30 s) → 65 used (12 cloudy/blurred frames skipped with reasons), 0.40 px alignment RMS across 10° of
  field rotation, 906 hot pixels repaired, ≈ 20 s (2× drizzle: ≈ 105 s, 2160 × 3840).
* **Mosaics** (Seestar `…_mosaic_sub` folders, or frames whose pointings differ): detected automatically (a checkbox in
  the dialog can override). Frames are aligned through overlapping panels and the result covers every panel; frames
  are graded against the frames pointing nearest to them. Uncovered corners stay empty — **Crop stacking edges** in
  Edit export removes them. Measured: IC 1805 (84 subs, 52 used; the rest cloudy) → 2713 × 3113 in 50 s with no visible
  seams.
* **Moon, Sun and planet videos** (Seestar RAW `.avi`, with its `.avi.txt`): enter the video file instead of a folder,
  or use Import from Seestar → *Stack video…*. Lucky imaging: every frame is graded for sharpness, the sharpest 25 %
  (at least 20) are aligned and averaged. A real 1495-frame lunar video stacks in about 26 s. If the target was
  over-exposed in the recording, a warning says so — that detail cannot be recovered. MP4 previews cannot be stacked.
* Every stacked value is a weighted mean of measured, resampled pixels — nothing is synthesized. The stack report (frames
  used/rejected, calibration, alignment, weights, rejection, timings) is stored with the stack
  (`GET /api/v1/stacks/{id}` → `full_report`); a summary is in the FITS `HISTORY`.

### Import from Seestar

**Import from Seestar…** (top bar, or the start screen) finds your Seestar `MyWorks` folder (copied from the telescope
or synced by the Seestar app; Browse… or paste the path if it isn't found) and lists your targets, newest first, with
the newest stack's frames, exposure and filter. **Add newest stack** adds it in one click; **Stack sub-frames…** /
**Stack mosaic…** / **Stack video…** open Stack frames already filled in with *Enhance automatically* on. Only folder and
file names are read to build the list; the files are never changed.

### Input handling

| Input | Handling |
|---|---|
| JPEG | 8-bit RGB/grayscale; EXIF orientation applied once; embedded ICC → sRGB. CMYK is rejected with guidance. |
| TIFF | Single page uint8/uint16/float32 gray/RGB (chunky or planar); orientation tag applied once. Alpha, palette, CMYK, int16/float64, multi-page → explained, never cast. State must be confirmed. |
| FITS | Astropy; scaling (BSCALE/BZERO) applied exactly once, originals recorded; BLANK/NaN masked (never dark stars); HDU selector; 2-D mono and documented 3-plane RGB; undocumented 3-plane shapes ask for confirmation; cubes/CFA get intake guidance. Rows flipped once for display and flipped back on export so WCS stays valid. |

State prompt “**How was this image saved?** Linear stack / Already processed / I’m not sure” — “not sure” allows a
labelled preview only; processing stays blocked. When the FITS header gives clear evidence (for example a ZWO Seestar
stack's `INSTRUME` and `STACKCNT`, or `NCOMBINE`), the matching answer is marked **Recommended** with the reason, and
**Use recommended answers for all N files** confirms them in one click; you still confirm, and nothing is inferred from
the histogram. Exports: full-resolution PNG (8-bit for 8-bit sources, 16-bit
otherwise), 16-bit TIFF (made when first downloaded), JPEG q95, comparison JPEG, processed float FITS (labelled *processed-linear* or
*display-processed*; location/observer keywords removed unless you pick the explicit full-metadata FITS), report,
summary, and Download all (ZIP with a folder per run and a batch summary; shows progress and can be cancelled).

### Edited exports for sharing

Select a finished result and choose **Edit export…** under the image. Rotate in 90° steps or use the angle slider to
fine-tune. Zoom to crop and drag the preview (or use its arrow keys) to choose the framing. Fine rotations may leave
black corners; zoom in to crop them. Zoom does not enlarge the exported pixels. For stacks with uneven edges (dithering,
field rotation or mosaics), **Crop stacking edges** frames the largest clean area at the image's aspect ratio; it is
only a suggestion and nothing is cropped unless you click it.

**Annotations**: when the image's sky position isn't known yet, the dialog finds it by itself as it opens (a few
seconds; needs the star catalog from Settings → Reference data). If it can't be found — for example a JPEG without
coordinates — the reason is shown and you can type the target's name under *Sky position* above. **Label objects** draws the
galaxies, nebulae and clusters of the OpenNGC catalog inside the framing (untick any you don't want; needs the object
catalog from Settings → Reference data), **Compass** shows north and east, and **Scale bar** shows the angular scale.
They are drawn only on this sharing copy.

Enter optional **Label text** for a name, company or caption. **Include target name** fills in the FITS `OBJECT`
name when available, or lets you enter one manually. **Text style** chooses the font (Sans, Serif, Script or
Typewriter — open-licence fonts shipped with the app, with accented letters), the text colour and whether a dark box
sits behind the text (without it the text gets a thin dark outline), plus a **position** (four corners, top or bottom
centre) and **size** for the target name and the label separately. Texts at the same position are stacked, target name
first, and move clear of the compass and scale bar. The label text and style are remembered for your next export.
Choose **PNG (16-bit)** or **JPEG (for sharing)**. This creates a separate copy of the enhanced display, not a
new enhancement run. The file records the source result and edit settings, but doesn't copy the original header.
Your regular downloads, original file, and processed-linear FITS or TIFF stay unchanged.

## 6. Dependency locks

`backend/uv.lock` (Python 3.12 pinned by `backend/.python-version` and `requires-python`) and
`frontend/package-lock.json`. Installs use `uv sync --frozen` and `npm ci`. Key versions: NumPy 2.5.4, SciPy 1.18.1,
Astropy 8.0.2, tifffile 2026.11.8, Pillow 13.0.0, FastAPI 0.162.5, Pydantic 2.14.3, CuPy 14.2.0 (optional).
Versions used by each run are recorded in its report. To update: edit `backend/pyproject.toml`, run `uv lock`, re-run the
tests, and bump `PIPELINE_VERSION` if outputs change.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `uv` / `npm` not found | Install them (see Requirements) and reopen PowerShell. |
| Page says “Frontend is not built” | `.\scripts\setup.ps1` (or `cd frontend; npm ci; npm run build`). |
| 403 “Missing or outdated session token” | The server restarted; reload the page. |
| Port in use | `.\scripts\start.ps1 -Port 9000`. |
| GPU shows “Processing: CPU” | Settings → **Check GPU setup**. “CuPy is not installed” → `.\scripts\setup-gpu.ps1`. “Failed to find CUDA headers” → the `[ctk]` extra is missing (re-run setup-gpu). Update the NVIDIA driver if the runtime is newer than the driver. CPU always works. |
| “needs about X GB of memory” | The up-front estimate exceeded the RAM budget (default 60% of available). Close programs, or raise the memory fraction in Settings; a 100 MP linear RGB image needs tens of GB. |
| “Download the star catalog…” under Sky position | Settings → **Reference data** → Download (once; internet needed only for the download). |
| Sky position “not found” | The file has no pointing in its header (for example a JPEG): type the object name and click **Try with this name**. |
| AI tool shows “Model not downloaded” | Click **Download** next to it (internet needed once), or Settings → AI models. The classical step is used until then. |
| AI model download fails with a certificate error | Check the PC's date and time and install pending Windows updates. Open the model's source, [Hugging Face](https://huggingface.co/jromanghf/graxpert-models) or [GitHub](https://github.com/setiastro/cosmicclarity/releases), in a browser on the same PC. If it shows a certificate warning, don't bypass it. On a managed network, ask the administrator to check the trusted HTTPS proxy certificate. |
| “This file needs debayering or stacking first” | Single raw/CFA frames cannot be enhanced on their own; use **Stack frames…** on their folder, or add the telescope’s stacked RGB/mono image. |
| Stacking: “Enter the full folder path” | Paste an absolute path such as `D:\Seestar\MyWorks\M 42_sub` (quotes are fine). |
| Stacking: many frames skipped | Open the stack report; choose *Lenient* or *Off* under Advanced → *Skip poor frames* to keep more frames. |
| Disk full | Free space; results are only published after validation, partial files are removed on restart. |

## 8. Status and known limitations

See [docs/STATUS.md](docs/STATUS.md) for the verified-vs-unverified matrix, benchmark results and the visual-review
checklist. Short version: the real Seestar stacked RGB FITS, a real uint16 TIFF, and the remaining visual-review images
have **not** been provided yet; FITS/TIFF support is verified with the real mono radio FITS you supplied and with clearly
labelled synthetic fixtures, but is **not** claimed complete for Seestar stacks until a real stacked FITS passes the path.
