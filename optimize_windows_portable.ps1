[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($env:OS -ne 'Windows_NT') {
    throw 'This optimization step must run on Windows.'
}

$PortableRoot = Join-Path $Root 'dist\BitcoinMinerStudio'
$InternalRoot = Join-Path $PortableRoot '_internal'
$PySideRoot = Join-Path $InternalRoot 'PySide6'
$ReleaseDir = Join-Path $Root 'release-windows'
$ExePath = Join-Path $PortableRoot 'BitcoinMinerStudio.exe'
$ManifestPath = Join-Path $PortableRoot 'purple_dragon_manifest.json'

foreach ($Required in @($PortableRoot, $InternalRoot, $PySideRoot, $ExePath, $ManifestPath)) {
    if (-not (Test-Path $Required)) {
        throw "Required portable-build path is missing: $Required"
    }
}

function Get-TreeStats {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -Force)
    $Bytes = ($Files | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $Bytes) { $Bytes = 0 }
    return [ordered]@{
        files = $Files.Count
        bytes = [int64]$Bytes
    }
}

Write-Host '== Bitcoin Miner Studio Qt release optimization ==' -ForegroundColor Cyan
$Before = Get-TreeStats -Path $PortableRoot
Write-Host ("Before: {0} files, {1:N1} MiB" -f $Before.files, ($Before.bytes / 1MB))

# Bitcoin Miner Studio uses Qt Widgets + Qt WebEngine through pywebview. It does
# not use Qt Quick/QML. PyInstaller's Qt dependency discovery can nevertheless
# include the complete QML tree (thousands of files), which materially hurts
# cold-start scanning on Windows and greatly inflates the portable package.
$QmlRoot = Join-Path $PySideRoot 'qml'
if (Test-Path $QmlRoot) {
    $QmlStats = Get-TreeStats -Path $QmlRoot
    Write-Host ("Removing unused Qt QML tree: {0} files, {1:N1} MiB" -f $QmlStats.files, ($QmlStats.bytes / 1MB))
    Remove-Item -LiteralPath $QmlRoot -Recurse -Force
}

# Debug-only Chromium/WebEngine payloads are not used by the stable release.
# Keep the normal WebEngine resources, locale packs, software OpenGL fallback,
# and production devtools resources for compatibility.
$DebugResources = @(
    'resources\qtwebengine_devtools_resources.debug.pak',
    'resources\qtwebengine_resources.debug.pak',
    'resources\v8_context_snapshot.debug.bin'
)
foreach ($Relative in $DebugResources) {
    $Path = Join-Path $PySideRoot $Relative
    if (Test-Path $Path -PathType Leaf) {
        $Size = (Get-Item $Path).Length
        Write-Host ("Removing debug-only Qt resource: {0} ({1:N1} MiB)" -f $Relative, ($Size / 1MB))
        Remove-Item -LiteralPath $Path -Force
    }
}

$After = Get-TreeStats -Path $PortableRoot
$SavedFiles = $Before.files - $After.files
$SavedBytes = $Before.bytes - $After.bytes
Write-Host ("After:  {0} files, {1:N1} MiB" -f $After.files, ($After.bytes / 1MB))
Write-Host ("Saved:  {0} files, {1:N1} MiB" -f $SavedFiles, ($SavedBytes / 1MB)) -ForegroundColor Green

# Re-verify the exact signed runtime surface. The optimizer must never alter a
# Purple Dragon protected file.
Write-Host 'Re-verifying Purple Dragon protected files after optimization...'
$env:BMS_OPTIMIZED_VERIFY_ROOT = $PortableRoot
$VerifyScript = @'
import json, os
from purple_dragon_security import verify_integrity
root = os.environ['BMS_OPTIMIZED_VERIFY_ROOT']
state = verify_integrity(root)
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
    and state.get('protected_file_count', 0) > 0
    and state.get('verified_file_count') == state.get('protected_file_count')
    and state.get('critical_actions_allowed') is True
)
raise SystemExit(0 if ok else 9)
'@
Push-Location $PortableRoot
try {
    $VerifyScript | python -
    if ($LASTEXITCODE -ne 0) {
        throw 'Purple Dragon verification failed after Qt release optimization.'
    }
}
finally {
    Pop-Location
    Remove-Item Env:BMS_OPTIMIZED_VERIFY_ROOT -ErrorAction SilentlyContinue
}

# Exercise the actual packaged application, not only an import probe. On hosted
# runners a GUI handle may not always be exposed, so a surviving process is an
# acceptable fallback; an immediate process exit is always a hard failure.
Write-Host 'Running optimized frozen-app startup smoke check...'
$StartupError = Join-Path $PortableRoot 'startup-error.log'
Remove-Item $StartupError -Force -ErrorAction SilentlyContinue
$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$Process = Start-Process -FilePath $ExePath -WorkingDirectory $PortableRoot -PassThru
$WindowReady = $false
$SmokeSeconds = 15
try {
    $Deadline = [DateTime]::UtcNow.AddSeconds($SmokeSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        Start-Sleep -Milliseconds 250
        $Process.Refresh()
        if ($Process.HasExited) {
            $Details = ''
            if (Test-Path $StartupError -PathType Leaf) {
                $Details = Get-Content $StartupError -Raw -ErrorAction SilentlyContinue
            }
            throw "Optimized BitcoinMinerStudio.exe exited during startup smoke check. $Details"
        }
        if ($Process.MainWindowHandle -ne 0) {
            $WindowReady = $true
            break
        }
    }
}
finally {
    $Stopwatch.Stop()
    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(5000) | Out-Null
    }
}

$StartupResult = if ($WindowReady) { 'window-ready' } else { 'process-alive' }
if ($WindowReady) {
    Write-Host ("Optimized frozen app window appeared in {0:N2}s" -f $Stopwatch.Elapsed.TotalSeconds) -ForegroundColor Green
} else {
    Write-Host ("Optimized frozen app remained healthy for {0}s; hosted runner exposed no window handle." -f $SmokeSeconds) -ForegroundColor Yellow
}

# Recreate public release assets from the optimized portable tree.
$Manifest = Get-Content $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$Version = [string]$Manifest.version
$ZipName = "BitcoinMinerStudio-v$Version-Windows-x64.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName
Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $PortableRoot '*') -DestinationPath $ZipPath -CompressionLevel Optimal

$ExeHash = (Get-FileHash $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
$ZipHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$ChecksumPath = Join-Path $ReleaseDir 'SHA256SUMS-Windows.txt'
Set-Content -Path $ChecksumPath -Encoding ASCII -Value @(
    "$ExeHash  BitcoinMinerStudio.exe",
    "$ZipHash  $ZipName"
)

$BuildInfoPath = Join-Path $ReleaseDir 'BitcoinMinerStudio-Windows-build.json'
$BuildInfo = Get-Content $BuildInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json
$BuildInfo | Add-Member -NotePropertyName optimization -NotePropertyValue 'qt-release-pruned' -Force
$BuildInfo | Add-Member -NotePropertyName portable_file_count -NotePropertyValue $After.files -Force
$BuildInfo | Add-Member -NotePropertyName portable_uncompressed_bytes -NotePropertyValue $After.bytes -Force
$BuildInfo | Add-Member -NotePropertyName optimized_saved_files -NotePropertyValue $SavedFiles -Force
$BuildInfo | Add-Member -NotePropertyName optimized_saved_bytes -NotePropertyValue $SavedBytes -Force
$BuildInfo | Add-Member -NotePropertyName frozen_app_smoke -NotePropertyValue $StartupResult -Force
$BuildInfo | Add-Member -NotePropertyName frozen_app_smoke_seconds -NotePropertyValue ([math]::Round($Stopwatch.Elapsed.TotalSeconds, 3)) -Force
$BuildInfo.archive_sha256 = $ZipHash
$BuildInfo.executable_sha256 = $ExeHash
$BuildInfo | ConvertTo-Json -Depth 8 | Set-Content -Path $BuildInfoPath -Encoding UTF8

Write-Host ''
Write-Host 'Optimized Windows portable release rebuilt successfully.' -ForegroundColor Green
Write-Host "ZIP: $ZipPath"
Write-Host "SHA-256: $ZipHash"
