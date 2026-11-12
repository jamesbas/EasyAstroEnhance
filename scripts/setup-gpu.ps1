<#
.SYNOPSIS  Optional: installs the NVIDIA GPU packages (CuPy for CUDA 13 + pip-delivered CUDA toolkit components) and verifies them.
.NOTES     Verified combination (locked in backend/uv.lock): Python 3.12.10, cupy-cuda13x 14.2.0 with the [ctk] extra,
           NVIDIA driver reporting CUDA 13.x (tested: driver 610.62 / CUDA 13.3, GeForce RTX 5070 Ti, compute capability 12.0).
           This script never installs drivers or a system-wide CUDA toolkit and never changes system settings.
           Only one CuPy variant is installed; do not mix with cupy-cuda12x. If the check fails, the app keeps working on CPU.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv was not found. Install uv: winget install --id=astral-sh.uv -e' }
Push-Location (Join-Path $root 'backend')
try {
    Write-Host '==> Installing optional GPU packages (adds to the CPU environment)' -ForegroundColor Cyan
    uv sync --frozen --extra gpu
    if ($LASTEXITCODE -ne 0) { throw 'uv sync --extra gpu failed' }
    Write-Host '==> Checking GPU setup (allocation + filter + synchronized numeric comparison with the CPU result)' -ForegroundColor Cyan
    uv run --frozen python -m app.gpu_check
    if ($LASTEXITCODE -eq 0) { Write-Host 'GPU acceleration is ready. In the app: Settings > Processing device (Auto is the default).' -ForegroundColor Green }
    else { Write-Host 'The GPU check did not pass. The app still runs fully on the CPU. See README > Troubleshooting.' -ForegroundColor Yellow }
} finally { Pop-Location }
