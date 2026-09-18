[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PortableRoot = Join-Path $Root 'dist\BitcoinMinerStudio'
$RuntimeRoot = Join-Path $PortableRoot '_runtime'
$SitePackages = Join-Path $RuntimeRoot 'Lib\site-packages'
$ReleaseDir = Join-Path $Root 'release-windows'
$ExePath = Join-Path $PortableRoot 'BitcoinMinerStudio.exe'
$DpiManifest = Join-Path $Root 'windows_highdpi.manifest'
$RuntimePython = Join-Path $RuntimeRoot 'python.exe'

foreach ($Required in @($PortableRoot, $RuntimeRoot, $SitePackages, $ReleaseDir, $ExePath, $DpiManifest, $RuntimePython)) {
    if (-not (Test-Path $Required)) {
        throw "Windows finalization input is missing: $Required"
    }
}

$BuildPython = (Get-Command python -ErrorAction Stop).Source

Write-Host '== Finalizing Bitcoin Miner Studio Windows release ==' -ForegroundColor Cyan
Write-Host 'Installing release-readiness cryptography runtime...'
& $BuildPython -m pip install --disable-pip-version-check --no-warn-script-location --upgrade --target $SitePackages `
    'cryptography==46.0.7'
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install the cryptography runtime into the embedded Python environment.'
}

$env:PYTHONHOME = $RuntimeRoot
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
& $RuntimePython -c "import cryptography; print('Cryptography runtime:', cryptography.__version__); raise SystemExit(0 if cryptography.__version__ == '46.0.7' else 12)"
if ($LASTEXITCODE -ne 0) {
    throw 'The embedded Python runtime cannot import the pinned cryptography 46.0.7 runtime after installation.'
}

Write-Host 'Embedding Per-Monitor V2 DPI awareness into BitcoinMinerStudio.exe...'
$Mt = $null
$MtCommand = Get-Command mt.exe -ErrorAction SilentlyContinue
if ($MtCommand) {
    $Mt = $MtCommand.Source
}
if (-not $Mt) {
    $SdkBin = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    if (Test-Path $SdkBin -PathType Container) {
        $Mt = Get-ChildItem -LiteralPath $SdkBin -Recurse -Filter 'mt.exe' -File -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '[\\/]x64[\\/]mt\.exe$' } |
            Sort-Object FullName -Descending |
            Select-Object -ExpandProperty FullName -First 1
    }
}
if (-not $Mt) {
    throw 'Windows SDK mt.exe was not found; cannot embed the high-DPI application manifest.'
}

& $Mt -nologo -manifest $DpiManifest "-outputresource:$ExePath;#1"
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to embed the high-DPI application manifest.'
}

$ExtractedManifest = Join-Path $env:TEMP 'BitcoinMinerStudio.embedded.manifest'
Remove-Item $ExtractedManifest -Force -ErrorAction SilentlyContinue
& $Mt -nologo "-inputresource:$ExePath;#1" "-out:$ExtractedManifest"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $ExtractedManifest -PathType Leaf)) {
    throw 'Could not verify the embedded high-DPI application manifest.'
}
$EmbeddedManifestText = Get-Content $ExtractedManifest -Raw -Encoding UTF8
if ($EmbeddedManifestText -notmatch 'PerMonitorV2') {
    throw 'The finished EXE does not contain Per-Monitor V2 DPI awareness.'
}
Write-Host 'High-DPI manifest: PerMonitorV2 verified.' -ForegroundColor Green

Write-Host 'Re-verifying Purple Dragon after Windows runtime finalization...'
Push-Location $PortableRoot
try {
    $VerifyScript = @'
import json
from purple_dragon_security import verify_integrity
state = verify_integrity()
summary = {
    'trust_level': state.get('trust_level'),
    'signature_valid': state.get('signature_valid'),
    'files_verified': state.get('verified_file_count'),
    'files_total': state.get('protected_file_count'),
    'critical_controls_enabled': state.get('critical_actions_allowed'),
}
print(json.dumps(summary, indent=2))
ok = (
    state.get('trust_level') == 'TRUSTED'
    and state.get('signature_valid') is True
    and state.get('verified_file_count') == state.get('protected_file_count')
    and state.get('protected_file_count', 0) > 0
    and state.get('critical_actions_allowed') is True
)
raise SystemExit(0 if ok else 9)
'@
    $VerifyScript | & $RuntimePython -
    if ($LASTEXITCODE -ne 0) {
        throw 'Purple Dragon verification failed after Windows runtime finalization.'
    }
}
finally {
    Pop-Location
}

Write-Host 'Running final EXE startup smoke test...'
$StartupError = Join-Path $PortableRoot 'startup-error.log'
$BackendLog = Join-Path $PortableRoot 'native-backend.log'
$SmokeResult = Join-Path $PortableRoot 'native-smoke.json'
Remove-Item $StartupError, $BackendLog, $SmokeResult -Force -ErrorAction SilentlyContinue

$SmokeProcess = Start-Process -FilePath $ExePath -ArgumentList '--smoke-test' -WorkingDirectory $PortableRoot -PassThru
if (-not $SmokeProcess.WaitForExit(45000)) {
    try { & taskkill.exe /PID $SmokeProcess.Id /T /F 2>$null | Out-Null } catch { }
    throw 'Final BitcoinMinerStudio.exe smoke test exceeded 45 seconds.'
}
if ($SmokeProcess.ExitCode -ne 0) {
    $Details = ''
    if (Test-Path $StartupError) { $Details += "`nstartup-error.log:`n" + (Get-Content $StartupError -Raw -ErrorAction SilentlyContinue) }
    if (Test-Path $BackendLog) { $Details += "`nnative-backend.log:`n" + (Get-Content $BackendLog -Raw -ErrorAction SilentlyContinue) }
    throw "Final Windows EXE smoke test failed with exit code $($SmokeProcess.ExitCode).$Details"
}
if (-not (Test-Path $SmokeResult -PathType Leaf)) {
    throw 'Final Windows EXE smoke test did not produce native-smoke.json.'
}
$Smoke = Get-Content $SmokeResult -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$Smoke.ok) {
    throw 'Final Windows EXE bridge smoke test reported failure.'
}
Write-Host ("Final native WebView2 startup passed in {0:N2}s" -f ([double]$Smoke.startup_ms / 1000.0)) -ForegroundColor Green
Remove-Item $StartupError, $BackendLog, $SmokeResult -Force -ErrorAction SilentlyContinue

# Rebuild release ZIP/checksums because the runtime and EXE changed after the base builder.
$Manifest = Get-Content (Join-Path $PortableRoot 'purple_dragon_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$Version = [string]$Manifest.version
$ZipName = "BitcoinMinerStudio-v$Version-Windows-x64.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName
Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $PortableRoot '*') -DestinationPath $ZipPath -CompressionLevel Optimal

$ExeHash = (Get-FileHash $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
$ZipHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path (Join-Path $ReleaseDir 'SHA256SUMS-Windows.txt') -Encoding ASCII -Value @(
    "$ExeHash  BitcoinMinerStudio.exe",
    "$ZipHash  $ZipName"
)

# Compute metadata from the finished portable tree, after all runtime additions
# and manifest embedding. This keeps build.json consistent with the artifact.
$FileStats = @(Get-ChildItem $PortableRoot -Recurse -File -Force)
$Bytes = [int64](($FileStats | Measure-Object -Property Length -Sum).Sum)

$BuildInfoPath = Join-Path $ReleaseDir 'BitcoinMinerStudio-Windows-build.json'
if (Test-Path $BuildInfoPath -PathType Leaf) {
    $BuildInfo = Get-Content $BuildInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $BuildInfo.executable_sha256 = $ExeHash
    $BuildInfo.archive_sha256 = $ZipHash
    $BuildInfo.startup_smoke = 'passed-after-finalization'
    $BuildInfo.startup_smoke_seconds = [math]::Round(([double]$Smoke.startup_ms / 1000.0), 3)
    $BuildInfo | Add-Member -NotePropertyName high_dpi_awareness -NotePropertyValue 'PerMonitorV2' -Force
    $BuildInfo | Add-Member -NotePropertyName cryptography_runtime -NotePropertyValue $true -Force
    $BuildInfo | Add-Member -NotePropertyName portable_files -NotePropertyValue $FileStats.Count -Force
    $BuildInfo | Add-Member -NotePropertyName portable_uncompressed_bytes -NotePropertyValue $Bytes -Force
    $BuildInfo | ConvertTo-Json -Depth 6 | Set-Content -Path $BuildInfoPath -Encoding UTF8
}

Write-Host ''
Write-Host 'Windows finalization complete.' -ForegroundColor Green
Write-Host 'DPI: PerMonitorV2'
Write-Host 'Cryptography runtime: 46.0.7 pinned and verified'
Write-Host "Portable files: $($FileStats.Count)"
Write-Host ("Portable size: {0:N1} MiB" -f ([double]$Bytes / 1MB))
Write-Host "ZIP SHA-256: $ZipHash"

Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue