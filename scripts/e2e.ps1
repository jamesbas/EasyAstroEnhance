<#
.SYNOPSIS  Playwright end-to-end tests against a temporary server (own data directory, spare port). Uses installed Microsoft Edge.
  Optional: spec file filters, e.g. .\scripts\e2e.ps1 stacking
#>
param([string[]]$Specs = @())
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$port = 8791
$data = Join-Path ([IO.Path]::GetTempPath()) ("eae-e2e-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
if (-not (Test-Path (Join-Path $root 'frontend\dist\index.html'))) { throw 'Build the frontend first: .\scripts\setup.ps1' }
$env:EASYASTRO_PORT = "$port"; $env:EASYASTRO_DATA_DIR = $data; $env:EASYASTRO_NO_BROWSER = '1'
$py = Join-Path $root 'backend\.venv\Scripts\python.exe'
$server = Start-Process -FilePath $py -ArgumentList '-m', 'app.serve' -WorkingDirectory (Join-Path $root 'backend') -PassThru -WindowStyle Hidden
try {
    $ok = $false
    1..40 | ForEach-Object { if (-not $ok) { try { Invoke-RestMethod "http://127.0.0.1:$port/api/v1/health" | Out-Null; $ok = $true } catch { Start-Sleep -Milliseconds 500 } } }
    if (-not $ok) { throw 'The test server did not start.' }
    Push-Location (Join-Path $root 'frontend')
    try {
        $env:EAE_BASE_URL = "http://127.0.0.1:$port"
        $sample = Get-ChildItem (Join-Path $root 'samplepics') -Filter *.jpg -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($sample) { $env:EAE_TEST_JPEG = $sample.FullName }
        $stackDir = Join-Path $data 'stack-subs\M 99_sub'
        & $py -c "import sys; sys.path[:0] = [r'$(Join-Path $root 'backend')', r'$(Join-Path $root 'backend\tests')']; from pathlib import Path; from stack_fixtures import _make_subs; _make_subs(Path(r'$stackDir'), n=6)"
        if ($LASTEXITCODE -eq 0) { $env:EAE_STACK_DIR = $stackDir }
        npx playwright test @Specs
        if ($LASTEXITCODE -ne 0) { throw 'Playwright tests failed' }
    } finally { Pop-Location }
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ParentProcessId -eq $server.Id } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Remove-Item $data -Recurse -Force -ErrorAction SilentlyContinue
}
