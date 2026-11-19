<#
.SYNOPSIS  Build the offline EasyAstroEnhance installer for Windows 11 x64.
.PARAMETER IsccPath  Optional path to ISCC.exe if Inno Setup is not installed in its default location.
#>
param([string]$IsccPath)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Build the installer on 64-bit x86 Windows.' }
foreach ($tool in 'uv.exe', 'npm.cmd') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is required to build the installer." }
}
if (-not $IsccPath) {
    $IsccPath = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if (-not $IsccPath) {
        $IsccPath = foreach ($dir in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Programs")) {
            foreach ($major in 7, 6) {
                $candidate = Join-Path $dir "Inno Setup $major\ISCC.exe"
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidate }
            }
        }
        $IsccPath = $IsccPath | Select-Object -First 1
    }
}
if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath -PathType Leaf)) {
    throw 'Install Inno Setup 7 or supply the path to ISCC.exe with -IsccPath.'
}
$IsccPath = (Resolve-Path -LiteralPath $IsccPath).Path

$recipe = Get-Content -LiteralPath (Join-Path $root 'backend\app\processing\recipe.py') -Raw
if ($recipe -notmatch '(?m)^PIPELINE_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"\r?$') {
    throw 'Could not read the app version from backend\app\processing\recipe.py.'
}
$version = $Matches[1]

$frontend = Join-Path $root 'frontend'
Push-Location $frontend
try {
    npm.cmd ci --include=dev --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'The frontend build failed.' }
} finally { Pop-Location }

$stage = Join-Path ([IO.Path]::GetTempPath()) "EasyAstroEnhance-build-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    $payload = Join-Path $stage 'payload'
    $pythonStore = Join-Path $stage 'python'
    $runtime = Join-Path $payload 'runtime'
    New-Item -ItemType Directory -Path "$payload\backend", "$payload\frontend", "$payload\licenses" | Out-Null

    uv.exe python install 3.12 --install-dir $pythonStore --no-registry --no-bin
    if ($LASTEXITCODE -ne 0) { throw 'Could not stage Python 3.12.' }
    $python = @(Get-ChildItem -LiteralPath $pythonStore -Directory -Filter 'cpython-3.12.*-windows-x86_64-none')
    if ($python.Count -ne 1) { throw 'Expected one standalone x64 Python runtime.' }
    Move-Item -LiteralPath $python[0].FullName -Destination $runtime

    $requirements = Join-Path $stage 'requirements.txt'
    Push-Location (Join-Path $root 'backend')
    try {
        uv.exe export --frozen --no-dev --no-install-project --output-file $requirements | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not export the production dependencies from uv.lock.' }
        uv.exe pip sync $requirements --python "$runtime\python.exe" --target "$runtime\Lib\site-packages" --require-hashes --only-binary ':all:' --link-mode copy
        if ($LASTEXITCODE -ne 0) { throw 'Could not stage the locked production wheels.' }
    } finally { Pop-Location }

    # Native wheels need the VC++ C++ and OpenMP DLLs even on a PC with no system redist.
    # Use the pinned official Visual Studio 2026 release package, not DLLs from System32.
    $vcHash = 'a4ab48822362df6e478eb4ed33bf825a07a6faacd6879c1e3d59929cd38b984b'
    $vcArchive = Join-Path $stage 'vc-redist.vsix'
    Invoke-WebRequest -UseBasicParsing -Uri "https://download.visualstudio.microsoft.com/download/pr/a424e95b-20f6-4af6-844f-9d9a806080a7/$vcHash/Microsoft.VC.14.50.18.0.CRT.Redist.X64.base.vsix" -OutFile $vcArchive
    if ((Get-FileHash -LiteralPath $vcArchive -Algorithm SHA256).Hash -ne $vcHash) { throw 'VC++ archive SHA-256 mismatch.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($vcArchive)
    try {
        foreach ($entry in $archive.Entries) {
            if ($entry.FullName -match '^Contents/VC/Redist/MSVC/[^/]+/x64/Microsoft\.VC145\.(CRT|OpenMP)/[^/]+\.dll$') {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $runtime $entry.Name), $true)
            }
        }
    } finally { $archive.Dispose() }
    foreach ($dll in 'msvcp140.dll', 'msvcp140_1.dll', 'vcomp140.dll') {
        if (-not (Test-Path -LiteralPath "$runtime\$dll" -PathType Leaf)) { throw "Missing $dll in the VC++ archive." }
    }

    Copy-Item -LiteralPath (Join-Path $root 'backend\app') -Destination "$payload\backend\app" -Recurse
    Copy-Item -LiteralPath "$frontend\dist" -Destination "$payload\frontend\dist" -Recurse
    Copy-Item -LiteralPath (Join-Path $root 'packaging\windows\launch.cmd') -Destination $payload
    foreach ($package in 'react', 'react-dom', 'scheduler') {
        Copy-Item -LiteralPath "$frontend\node_modules\$package\LICENSE" -Destination "$payload\licenses\$package.txt"
    }

    $definition = Join-Path $root 'packaging\windows\EasyAstroEnhance.iss'
    & $IsccPath '/Q' "/O$stage" "/DAppVersion=$version" "/DPayload=$payload" $definition
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup could not build the installer.' }
    $output = Join-Path $root 'dist\windows'
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    $name = "EasyAstroEnhance-$version-Windows-x64-Setup.exe"
    $installer = Join-Path $output $name
    Move-Item -LiteralPath (Join-Path $stage $name) -Destination $installer -Force
    Write-Host "Installer: $installer"
    Get-FileHash -LiteralPath $installer -Algorithm SHA256
} finally { Remove-Item -LiteralPath $stage -Recurse -Force }
