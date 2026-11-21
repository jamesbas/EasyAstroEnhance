# Running EasyAstroEnhance on macOS — assessment and recommendations

*Investigation of engine 1.7.0 (commit `67b966b`), November 2026. No code was changed for this assessment.*

## 1. Short answer

**Running it on a Mac is mostly straightforward; shipping it to Mac users is the real work.**

The application is already built from cross-platform parts: a Python backend (FastAPI, NumPy, SciPy, Astropy,
Pillow, ONNX Runtime) and a browser frontend (React). There is no Windows API, registry, COM or .NET code. The
processing core in `backend/app/processing` is pure Python/NumPy and needs **no algorithmic changes** — every
image-processing step, stacking, sky solving, catalogs and reports will produce the same results on a Mac.

What does need attention:

| Area | Size of change | Why |
|---|---|---|
| Download security (TLS certificates) | **Small but mandatory** | AI model and star-catalog downloads would fail with certificate errors on a bundled Mac Python. |
| A handful of Windows-only paths and texts | Small | Data folder location, drive letters, `D:\…` examples, "File Explorer", `scripts\*.ps1` hints. |
| Seestar folder discovery and folder browser | Small | They look for drive letters; on a Mac external disks and network shares live under `/Volumes`. |
| GPU acceleration | **Not portable** | Pixel-stage GPU acceleration is NVIDIA CUDA (CuPy), which does not exist on Macs. The CPU path is complete and is used automatically. |
| AI tools on the GPU | Small–medium (optional) | Windows uses DirectML; the Mac equivalent is ONNX Runtime's Core ML provider, which must be added and validated per model. Without it, AI tools run on the CPU (slow for noise reduction). |
| Developer scripts | Small–medium | All scripts are PowerShell with Windows paths (`.venv\Scripts\python.exe`, Microsoft Edge). Mac shell equivalents are needed. |
| Installer / packaging | **Large** | The Windows installer (Inno Setup, VC++ runtime, `launch.cmd`) has no Mac counterpart. A Mac app bundle, a DMG, Apple code signing and notarization are needed. |
| "How do I quit?" | Small–medium (design) | On Windows the console window is the app's off switch. A Mac app bundle has no such window. |

**Estimate:** about **1–2 days** to run from source on a Mac (developer mode, CPU only); about **1.5–3 weeks** in
total for a signed, notarized, double-clickable Mac app with Core ML–accelerated AI tools, tested on real Macs. The
biggest variables are Apple signing/notarization of the bundled Python (hundreds of native libraries) and Core ML
compatibility of the five third-party AI models.

## 2. What already works on macOS without changes

- **Dependencies are locked for macOS.** `backend/uv.lock` is a universal lock and already contains macOS wheels
  for every runtime dependency (Python 3.12): NumPy 2.5.4, SciPy 1.18.1, Pillow 13.0.0, imagecodecs, Astropy 8.0.2,
  psutil 7.2.2, FastAPI/uvicorn. `backend/pyproject.toml` already selects plain `onnxruntime` instead of
  `onnxruntime-directml` on non-Windows systems. `uv sync --frozen` should work on a Mac as-is.
- **Processing core.** Pure NumPy/SciPy; deterministic; no platform calls. CPU tiling and threading
  (`EASYASTRO_CPU_THREADS`, `ThreadPoolExecutor`) are portable. The CPU path is the reference implementation the GPU
  path is tested against, so Mac results equal Windows CPU results (within floating-point noise between BLAS builds).
- **Worker process.** `services/queue.py` already uses the `spawn` multiprocessing context, which is also the macOS
  default. The orphan check (`psutil.pid_exists(parent)`) is portable.
- **GPU fallback.** `processing/backends/__init__.py` `probe_cuda()` catches a missing CuPy and reports "CPU"; every
  stage falls back to the CPU. Nothing crashes without NVIDIA hardware.
- **Files and storage.** `pathlib` throughout; atomic `replace()` publishing; SQLite in WAL mode; read-only originals
  via `chmod(stat.S_IREAD)` (on macOS this is mode 0400 and deletion still works because it depends on the folder's
  permissions); NumPy memory-mapped previews; `shutil.disk_usage` / `psutil.virtual_memory` checks.
- **Local server security.** Binds to `127.0.0.1`; Host/Origin allow-list and per-start token are browser-agnostic.
  Safari 16.4+ sends `Sec-Fetch-Site`, which the middleware already handles.
- **Seestar file formats.** FITS reading/orientation, RAW AVI video, mosaics and the MyWorks folder naming are
  defined by the telescope, not the PC — they are the same on a Mac.
- **Browser frontend.** No Windows-only web APIs. It uses `<dialog>.showModal()` (Safari 15.4+),
  `crypto.randomUUID` (with a fallback), pointer capture and standard CSS; TypeScript targets ES2022. Safari 16 or
  newer should work, but the UI has only ever been tested in Edge/Chromium (see §5).

## 3. Changes needed in the working code

### 3.1 Must fix

1. **Certificate verification for downloads** — `backend/app/services/ai_models.py` lines 24–35, and
   `pyproject.toml` (`truststore; sys_platform == 'win32'`).
   Downloads of AI models and the reference catalogs use `truststore` (the operating system's certificate store) on
   Windows only; elsewhere Python's default `ssl` context is used. A standalone/bundled Python on macOS (as
   `uv python install` provides) has no configured CA bundle and does not read the macOS Keychain, so downloads fail
   with `CERTIFICATE_VERIFY_FAILED`. `truststore` supports macOS (Security framework): extend the marker and the
   `sys.platform` check to `darwin`. Then lock again (`uv lock`).

2. **Data folder location** — `backend/app/config.py` line 10.
   Without `LOCALAPPDATA` the app falls back to `~/.local/share/EasyAstroEnhance`, a Linux convention that is hidden
   in Finder. macOS apps use `~/Library/Application Support/EasyAstroEnhance`. Decide this **before** the first Mac
   release: moving it later means migrating users' history, presets, models and catalogs.

3. **Seestar MyWorks discovery** — `backend/app/services/seestar.py` line 39 (`candidates`).
   On non-Windows systems the only root searched is `/`. Seestar data on a Mac is usually on an external disk, a
   card reader, or the telescope's network share mounted in Finder — all appear under `/Volumes/<name>`. Add
   `/Volumes/*` to the searched roots (the home, Pictures, Documents and Desktop folders are already searched for a
   `MyWorks` folder). *To verify on a real setup: the exact share/volume name the Seestar presents over Wi-Fi (SMB)
   when connected from a Mac.*

4. **Folder browser roots** — `backend/app/services/folders.py` lines 38–49 (`roots`).
   Same issue: offer `/Volumes/*` (mounted disks and shares) and the home folders instead of only `/`.

### 3.2 Should fix (user-visible Windows wording)

| Where | Current text | Mac version |
|---|---|---|
| `frontend/src/components/StackDialog.tsx` lines 162, 173 | placeholder `D:\Seestar\MyWorks\M 42_sub`; "in File Explorer: right-click the folder → Copy as path" | `/Volumes/…/MyWorks/M 42_sub`; "in Finder: select the folder, hold Option and choose **Copy … as Pathname**" |
| `frontend/src/components/SeestarImportDialog.tsx` line 85 | placeholder `D:\Seestar\MyWorks` | `/Volumes/…/MyWorks` |
| `backend/app/processing/stacking/frames.py` line 167 | "for example D:\Seestar\MyWorks\M 45_sub" | an OS-appropriate example |
| `frontend/src/components/SettingsDialog.tsx` line 291 | device option "NVIDIA GPU" | hide on Macs (no CUDA) |
| `backend/app/processing/backends/__init__.py` line 43 | "run scripts\setup-gpu.ps1" | on macOS: "GPU acceleration is not available on Macs; CPU processing is fully functional" |
| `backend/app/serve.py` line 21, `backend/app/main.py` line 79 | "Run scripts\setup.ps1" | the Mac script name |

The simplest approach is to have the backend report the platform in `/api/v1/session` (it already reports versions)
and let the frontend pick the example text; keep the backend messages OS-aware with `sys.platform`.

### 3.3 Optional but recommended: AI tools on the Mac GPU (Core ML)

- `backend/app/processing/ai/runtime.py` lines 16–17 and `services/ai_models.py` line 69 only know
  `DmlExecutionProvider` and `CUDAExecutionProvider`. On a Mac, the locked `onnxruntime` 1.32 wheel includes
  `CoreMLExecutionProvider`. Adding it to `GPU_PROVIDERS`/`PROVIDER_LABELS` (label "GPU (Core ML)") is a few lines,
  and the existing per-run CPU fallback (`Runner.__call__`) already handles a provider that fails.
- **Validation is the real work.** Core ML supports a subset of ONNX operators and may run unsupported parts of a model
  on the CPU, or reject very large tensors. Each of the five model families (GraXpert background, GraXpert denoise,
  Dark Star, Cosmic Clarity Sharpen stellar/non-stellar) must be checked on a real Apple Silicon Mac for:
  identical results to the CPU provider (the existing `test_real_gpu_and_cpu_providers_agree` pattern), speed, and
  memory. GraXpert and Seti Astro both ship Mac builds that use these models, which is encouraging but not proof for
  our tile sizes and batch shapes. Consider Core ML's `MLProgram` format and the session option that caches compiled
  models, since first-run compilation can take seconds.
- The new idle release of AI sessions (`services/worker.py`, `AI_IDLE_RELEASE_S`) applies unchanged.
- The GraXpert "copy instead of download" shortcut (`ai_models.py` line 48–49) looks only in
  `%LOCALAPPDATA%\GraXpert`; add the Mac location of GraXpert's model folder (to be confirmed on a Mac with GraXpert
  installed) or simply skip the shortcut on Macs.

### 3.4 Not portable: NVIDIA (CuPy) acceleration of the pixel stages

The `gpu` extra (`cupy-cuda13x`) and `processing/backends/cupy_backend.py` are CUDA-only; Apple GPUs do not run CUDA.
On a Mac, enhancement and stacking run on the CPU (with parallel tiles). This is a performance difference, not a
functional one: every feature, including all of Phase 3, works on the CPU path. For reference, on the Windows test
PC's CPU an 8.3 MP linear stack takes ≈ 14 s and a 2 MP Seestar S30 stack ≈ 6 s (`docs/benchmarks.md`); Apple
Silicon CPUs should be in the same range — measure on real Macs before publishing numbers.

An Apple-GPU backend (for example via MLX or PyTorch MPS) is **not recommended** for the first port: the `Backend`
abstraction would allow it, but the pipeline relies on `cupyx.scipy.ndimage`-style filters (Gaussian, morphology,
affine transforms, FFT convolution) that those libraries do not provide one-to-one, and every stage would need new
CPU-parity tests. Revisit only if Mac users find CPU speed a real problem.

### 3.5 Tests and developer tooling

- **Scripts.** `scripts/setup.ps1`, `start.ps1`, `test.ps1`, `e2e.ps1`, `setup-gpu.ps1` and `build-installer.ps1` are
  PowerShell with Windows paths (`backend\.venv\Scripts\python.exe`, `Win32_Process` to stop the worker, `winget`
  hints). Add `scripts/*.sh` equivalents for setup/start/test/e2e (uv and npm commands are identical). `setup-gpu` has
  no Mac equivalent.
- **Playwright.** `frontend/playwright.config.ts` pins `channel: 'msedge'`. Make the browser configurable and run the
  suite with Chromium **and WebKit** (Safari's engine) on the Mac.
- **Backend tests.** No test depends on Windows, apart from small details to check on a Mac: `test_ai.py` line 353
  builds the real-models path from `LOCALAPPDATA` (real-model tests would simply be skipped), and `test_engine16.py`
  lines 186–189 use `D:\…` strings for the recent-folders list (string handling only; expected to pass). GPU tests skip
  automatically without CUDA.
- **CI.** Add a GitHub Actions job on `macos-14` (Apple Silicon) running `uv sync --frozen`, `pytest`, the frontend
  type-check/build and Playwright (WebKit). This catches regressions without owning a Mac for every change.

## 4. Packaging and distribution — the large part

The Windows installer (`scripts/build-installer.ps1`, `packaging/windows/EasyAstroEnhance.iss`,
`packaging/windows/launch.cmd`) stages a standalone CPython, the locked wheels, the backend, the built frontend and
the VC++ runtime DLLs, then wraps them with Inno Setup into a per-user installer. None of these tools exist on macOS,
but the **same approach carries over**:

1. **Bundle.** Build `EasyAstroEnhance.app`:
   - `Contents/Resources/runtime` — a standalone CPython 3.12 for macOS arm64 (`uv python install 3.12` provides it);
   - the locked production wheels installed into it with `uv pip sync --require-hashes --only-binary :all:`, exactly
     as the Windows script does;
   - `backend/app` and `frontend/dist`;
   - `Contents/MacOS/EasyAstroEnhance` — a small launcher (shell script or tiny native stub) running
     `runtime/bin/python3 -E -s -B -m app.serve`;
   - an `Info.plist` (bundle id, version from `PIPELINE_VERSION`, minimum macOS, icon).
   No VC++ runtime is needed on macOS.
2. **Target Apple Silicon only (arm64), macOS 14 Sonoma or later.** The locked `onnxruntime` 1.32 only ships
   `macosx_14_0_arm64` wheels (no Intel Mac build), and NumPy/SciPy's fastest builds (Apple Accelerate) also target
   macOS 14. Intel Macs could run the core app with AI tools disabled, but a second build is not worth it for a
   shrinking user base. Say so clearly on the download page.
3. **Code signing and notarization (strongly recommended).** Windows SmartScreen shows a warning that users can click
   through. macOS Gatekeeper is much stricter: an unsigned, downloaded app is blocked, and on macOS 15 Sequoia users
   must go to *System Settings → Privacy & Security → Open Anyway* — a poor first experience for the beginner audience.
   This needs an **Apple Developer Program membership (99 USD/year)**, a "Developer ID Application" certificate,
   signing **every** Mach-O binary in the bundle (the Python runtime and each `.so`/`.dylib` in NumPy, SciPy,
   Pillow, imagecodecs, ONNX Runtime…) with the hardened runtime, then `xcrun notarytool submit` and
   `xcrun stapler staple`. Expect some iteration: notarization rejects any unsigned or ad-hoc-signed library, and
   library validation may need the `com.apple.security.cs.disable-library-validation` entitlement if any third-party
   library cannot be re-signed. Signing must happen on a Mac (or a macOS CI runner with the certificate as a secret).
4. **Distribute** a signed, notarized DMG (`hdiutil create`) with the usual "drag to Applications" layout, attached to
   the same GitHub releases as the Windows installer, and add a "Download for Mac" button to `docs/index.html`.
5. **Quitting and running twice.** On Windows the console window is both the running indicator and the off switch
   (`launch.cmd`), and a second launch fails on the busy port with a message. A Mac app bundle has no console window:
   a launcher script that keeps the server in the foreground shows a Dock icon whose **Quit** does not reach the
   script. Recommended:
   - add a **Quit EasyAstroEnhance** action in the web UI (Settings) backed by a token-protected shutdown endpoint
     that stops the worker and server cleanly;
   - in the launcher, if the port is already in use by EasyAstroEnhance, just open the browser at the existing
     instance instead of failing;
   - optionally later, a tiny native or PyObjC menu-bar item with "Open" and "Quit".
   (A Terminal-based `.command` launcher avoids all of this but looks unfinished and still needs signing.)
6. **Data and uninstall.** With the data folder in `~/Library/Application Support/EasyAstroEnhance`, removing the app
   from Applications keeps the user's history, presets, models and catalogs — the same promise the Windows uninstaller
   makes. Document how to remove the data folder.

## 5. Verification plan (needs real Macs)

1. Run from source on an Apple Silicon Mac: `uv sync --frozen`, `npm ci && npm run build`, `pytest` (expect all
   non-GPU tests to pass), start the app and process a real Seestar FITS, JPEG and a stacking folder.
2. Download an AI model and the star catalog in Settings (this exercises the certificate fix).
3. Compare CPU results with the Windows CPU results for the same real stacks (reports and display PNGs should agree to
   within one 8-bit step).
4. Run the browser suite with WebKit and manually check the main screens in Safari: viewer zoom/pan and tiles, Edit
   export drag and rotation, live preview, dialogs, drag-and-drop upload.
5. Core ML: per-model parity and speed against the CPU provider on M1-class and newer chips; memory use on 8 GB Macs.
6. Seestar import: MyWorks on an external disk and on the telescope's network share mounted in Finder.
7. Package: install from the notarized DMG on a clean Mac (quarantine attribute set by the browser download), first
   launch with no Gatekeeper prompt beyond the standard "downloaded from the internet" confirmation, quit/relaunch,
   upgrade over an older version, remove.

## 6. Recommended plan

| Phase | Work | Outcome | Rough effort |
|---|---|---|---|
| 1. Portable source | §3.1 fixes (truststore on macOS, data folder, `/Volumes` discovery and browsing), §3.2 wording, `scripts/*.sh`, configurable Playwright browser, macOS CI job | Developers and technical users can run from source on a Mac (CPU, AI on CPU) | 1–2 days |
| 2. Mac app | App bundle build script, launcher with single-instance handling, in-app Quit, Developer ID signing + notarization, DMG, release and site updates | Ordinary users download and double-click | 1–1.5 weeks (plus Apple account setup) |
| 3. AI speed | Core ML provider with per-model validation and fallbacks | AI tools at usable speed on Apple Silicon | 2–4 days, mostly testing |
| Later, only if needed | Apple-GPU backend for pixel stages | Faster non-AI processing | Large; not recommended now |

**Spec and process notes.** The application spec (`astro-photo-enhancer-app-spec.md`) describes "Optional NVIDIA
acceleration" and a Windows installer; a short amendment should state the supported Mac configuration (Apple
Silicon, macOS 14+, CPU processing, optional Core ML for AI tools) and the Mac packaging requirements. None of the
changes above alters processing output, so `PIPELINE_VERSION` does not change for the port itself; adding Core ML
only changes which device runs a model (still recorded per run as the execution provider).

## 7. Open questions for the owner

1. Is an **Apple Developer Program** membership acceptable (needed for a smooth, signed and notarized install)?
2. **Apple Silicon only**, or should Intel Macs also be supported (with AI tools unavailable)?
3. Who can test: which Mac models (8 GB vs 16 GB+ memory matters for large stacks and AI noise reduction)?
4. How do Seestar owners in the group usually get their files onto a Mac — the telescope's Wi-Fi share, USB, or the
   Seestar app's export? This decides how much effort goes into automatic MyWorks discovery.
