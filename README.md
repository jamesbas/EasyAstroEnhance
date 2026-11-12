# EasyAstroEnhance

A small **local** application that enhances telescope photographs (JPEG, TIFF, stacked FITS) with conventional
numerical image processing. Add files → choose enhancements → **Enhance** → compare before/after → download.

* Everything runs on your PC (FastAPI on `127.0.0.1` + a React UI). No accounts, no cloud, no API keys.
* **No generative or learned processing of any kind**: no diffusion/inpainting, no super-resolution, no synthetic
  stars, no reference photographs of the target. Output pixels derive only from the uploaded pixels.
* Originals are immutable (read-only copies, byte-for-byte; every run re-reads the original).
* Optional NVIDIA GPU acceleration (CuPy) for eligible stages with a complete CPU fallback.

Full specification: [astro-photo-enhancer-app-spec.md](astro-photo-enhancer-app-spec.md).

---------------------------------------------------------------------------------------------------

## 1. Requirements

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

App data (originals' copies, previews, runs, exports, SQLite database) lives in `%LOCALAPPDATA%\EasyAstroEnhance`
(override with `-DataDir` / `EASYASTRO_DATA_DIR`). **Settings → Clear local history** lists exactly what it removes; your
own files elsewhere are never touched. Limits (env overrides): 20 files per batch (`EASYASTRO_MAX_FILES`), 512 MiB per file
(`EASYASTRO_MAX_FILE_MB`), 100 megapixels (`EASYASTRO_MAX_MEGAPIXELS`).

## 4. Test

```powershell
.\scripts\test.ps1               # backend pytest + frontend type-check
.\scripts\test.ps1 -E2E          # + Playwright browser tests (temporary server on port 8791, uses Edge)
.\scripts\test.ps1 -RealFiles    # only tests that use your real images in .\samplepics
```

Direct commands: `cd backend; uv run --frozen pytest -q` · `uv run --frozen pytest -m "not gpu"` ·
`cd frontend; npm run typecheck; npx playwright test`.
GPU tests (marker `gpu`) are **skipped automatically** when CuPy/CUDA is unavailable; CPU-only runs never claim GPU
support. Tests marked `realfiles` skip when `samplepics/` is absent. Synthetic images/FITS/TIFF in the tests are labelled
test fixtures and are never used as output content.

Benchmarks / review helpers: `cd backend; uv run python tools/benchmark.py` (writes `docs/benchmarks.md`) and
`uv run python tools/visual_review.py` (writes comparisons, 100% crops and reports to `docs/visual-review/`, git-ignored).

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

### Processing method disclosure (engine 1.0.0, recipe schema 2)

Two display paths share one tail; no 8-bit conversion exists for TIFF/FITS (16-bit/float values are quantised only at
the chosen export).

* **Rendered (JPEG; display-referred TIFF/FITS):** optional supervised background correction → gentle luminance/chroma
  residual shrinkage (robust MAD noise from valid, unprotected, non-star pixels; edge/star-aware gate) → rational
  midtone curve + bounded manual offsets → star-protected stretch → optional local contrast → guarded luminance-ratio
  reconstruction, hue-preserving gamut fitting, protected saturation → clipping check.
* **Linear (stacked TIFF/FITS confirmed “Linear stack”):** one shared scale/offset (never per channel) →
  background correction → denoise in the linear domain (**processed-linear array is saved here**, before any
  display-only step) → luminance asinh display renderer with a recorded black/span/k → the same display tail.
  Negative physical values are retained in the linear data; the baseline display uses a *frozen* mapping derived once from
  the source so “Original” and “Enhanced” are never auto-stretched independently.
* **Tone controls** compose into one monotonic transform in fixed order: black point → brightness (2^EV, ±1 EV) →
  shadows → highlights (smooth bounded bumps, ±0.12 peak). Neutral offsets add nothing; monotonicity is validated.
* **Star protection** builds a soft mask from confidently identified compact sources (local background/noise, size,
  shape, isolation and core-sharpness checks) and attenuates only the *positive* tone change where a star is brighter
  than its star-free surroundings. It never removes, shrinks or replaces stars; unreliable detection is skipped and
  disclosed.
* **Local contrast** (off by default): guided-filter base/detail on luminance at a scale in full-resolution pixels,
  noise-gated, bounded (±0.06), suppressed near stars/invalid/protected pixels. Not deconvolution.
* **Background correction:** constant (≥3 confirmed regions) or first-order plane (≥6 widely distributed, non-collinear
  confirmed regions; robust Huber fit with residual, conditioning, outlier and contamination checks). Confirmation is
  stored per asset and is never copied by presets or “Apply to all”. Constant and plane terms are separated so nothing is
  subtracted twice.
* **Strength tables** (proposed tuning values, not universal): denoise 0.30/0.40/0.55, rational gain 1.25/1.45/1.75,
  asinh k 20/45/90, saturation 1.08/1.12/1.20, star protection 0.50/0.75/0.90, local contrast 0.35/0.60/0.90,
  background 0.5/0.75/1.0 (Gentle/Balanced/Strong). Natural = all Gentle; Brighter detail = all Balanced.
* **Guardrail:** new black/white clipping (per-pixel transitions, invalid/protected excluded) above 0.1% reduces
  strengths once and reruns; if still above, the conservative result is kept and flagged “review”.
* **Deferred (not implemented):** calibration frames, stacking, debayering, cubes/multi-page TIFF, plate solving,
  photometric calibration, higher-order gradients, deconvolution, star reduction/removal, narrowband palettes.

This is **display enhancement, not scientific calibration**: background neutralization is not photometric colour
calibration and a sharper look is not extra measured resolution. Every run’s `processing.json` records source SHA-256,
engine/dependency versions, requested vs applied recipe, per-file resolved parameters, skipped steps with reasons,
clipping transitions, noise estimate (with its limitations), backend/device/transfers/timings and export hashes.

### Input handling

| Input | Handling |
|---|---|
| JPEG | 8-bit RGB/grayscale; EXIF orientation applied once; embedded ICC → sRGB. CMYK is rejected with guidance. |
| TIFF | Single page uint8/uint16/float32 gray/RGB (chunky or planar); orientation tag applied once. Alpha, palette, CMYK, int16/float64, multi-page → explained, never cast. State must be confirmed. |
| FITS | Astropy; scaling (BSCALE/BZERO) applied exactly once, originals recorded; BLANK/NaN masked (never dark stars); HDU selector; 2-D mono and documented 3-plane RGB; undocumented 3-plane shapes ask for confirmation; cubes/CFA get intake guidance. Rows flipped once for display and flipped back on export so WCS stays valid. |

State prompt “**How was this image saved?** Linear stack / Already processed / I’m not sure” — “not sure” allows a
labelled preview only; processing stays blocked. Exports: full-resolution PNG (8-bit for 8-bit sources, 16-bit
otherwise), 16-bit TIFF, JPEG q95, comparison JPEG, processed float FITS (labelled *processed-linear* or
*display-processed*; location/observer keywords removed unless you pick the explicit full-metadata FITS), report,
summary, and Download all (ZIP with a folder per run and a batch summary).

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
| “This file needs debayering or stacking first” | Single raw/CFA frames are not supported; export the telescope’s stacked RGB/mono image. |
| Disk full | Free space; results are only published after validation, partial files are removed on restart. |

## 8. Status and known limitations

See [docs/STATUS.md](docs/STATUS.md) for the verified-vs-unverified matrix, benchmark results and the visual-review
checklist. Short version: the real Seestar stacked RGB FITS, a real uint16 TIFF, and the remaining visual-review images
have **not** been provided yet; FITS/TIFF support is verified with the real mono radio FITS you supplied and with clearly
labelled synthetic fixtures, but is **not** claimed complete for Seestar stacks until a real stacked FITS passes the path.
