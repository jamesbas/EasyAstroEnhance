<#
.SYNOPSIS  Runs the test suites.
.PARAMETER E2E       Also run the Playwright browser tests (starts a temporary server on a spare port and stops it afterwards).
.PARAMETER RealFiles Only run tests marked 'realfiles' (needs your images in .\samplepics).
.NOTES     GPU tests are marked 'gpu' and are SKIPPED automatically when no working CUDA device/CuPy is present.
#>
param([switch]$E2E, [switch]$RealFiles)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $root 'backend')
try {
    Write-Host '==> Backend tests (pytest)' -ForegroundColor Cyan
    if ($RealFiles) { uv run --frozen pytest -m realfiles -v } else { uv run --frozen pytest -q }
    if ($LASTEXITCODE -ne 0) { throw 'backend tests failed' }
} finally { Pop-Location }

Push-Location (Join-Path $root 'frontend')
try {
    Write-Host '==> Frontend type check' -ForegroundColor Cyan
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'frontend type check failed' }
} finally { Pop-Location }

if ($E2E) { & (Join-Path $PSScriptRoot 'e2e.ps1') }
Write-Host 'All requested tests passed.' -ForegroundColor Green
