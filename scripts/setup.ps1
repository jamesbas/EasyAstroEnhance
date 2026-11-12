<#
.SYNOPSIS  One-time setup: installs the locked Python (3.12) and npm dependencies and builds the frontend. CPU-only; fully functional without a GPU.
.PARAMETER Gpu  Also install the optional NVIDIA/CuPy packages (same as running setup-gpu.ps1 afterwards).
.PARAMETER SkipFrontend  Skip `npm ci` and the production build.
.NOTES    Requires: uv (https://docs.astral.sh/uv/) and Node.js 20+ with npm. Internet is needed only for this step.
          Re-running without -Gpu removes the optional GPU packages (the environment is synced to the lockfile).
#>
param([switch]$Gpu, [switch]$SkipFrontend)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Need($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "$name was not found. $hint" }
}
Need uv 'Install uv: winget install --id=astral-sh.uv -e'
Need node 'Install Node.js LTS: winget install OpenJS.NodeJS.LTS'
Need npm 'Install Node.js LTS: winget install OpenJS.NodeJS.LTS'

Write-Host '==> Backend: installing locked Python dependencies (Python 3.12)' -ForegroundColor Cyan
Push-Location (Join-Path $root 'backend')
try {
    if ($Gpu) { uv sync --frozen --extra gpu } else { uv sync --frozen }
    if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
} finally { Pop-Location }

if (-not $SkipFrontend) {
    Write-Host '==> Frontend: installing locked npm dependencies and building' -ForegroundColor Cyan
    Push-Location (Join-Path $root 'frontend')
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
    } finally { Pop-Location }
}
Write-Host 'Setup complete. Start the app with: .\scripts\start.ps1' -ForegroundColor Green
