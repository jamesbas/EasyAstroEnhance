<#
.SYNOPSIS  Starts EasyAstroEnhance on http://127.0.0.1:8765 (localhost only) and opens your browser.
.PARAMETER Port       Port to listen on (default 8765).
.PARAMETER DataDir    Folder for app-owned data (default %LOCALAPPDATA%\EasyAstroEnhance).
.PARAMETER NoBrowser  Do not open the browser.
#>
param([int]$Port = 8765, [string]$DataDir, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root 'frontend\dist\index.html'))) { Write-Warning 'The frontend is not built yet. Run .\scripts\setup.ps1 first.' }
$env:EASYASTRO_PORT = "$Port"
if ($DataDir) { $env:EASYASTRO_DATA_DIR = $DataDir }
if ($NoBrowser) { $env:EASYASTRO_NO_BROWSER = '1' }
Push-Location (Join-Path $root 'backend')
try { uv run --frozen python -m app.serve } finally { Pop-Location }
