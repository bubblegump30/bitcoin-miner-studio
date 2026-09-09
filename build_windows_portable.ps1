[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($env:OS -ne 'Windows_NT') {
    throw 'This build must run on 64-bit Windows.'
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'Bitcoin Miner Studio Windows releases require a 64-bit Windows build host.'
}

function Resolve-Python {
    $candidates = @(
        @{ Command = 'py'; Args = @('-3.12') },
        @{ Command = 'python'; Args = @() }
    )
    foreach ($candidate in $candidates) {
        try {
            $cmd = Get-Command $candidate.Command -ErrorAction Stop
            & $cmd.Source @($candidate.Args) -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) and sys.maxsize > 2**32 else 1)"
            if ($LASTEXITCODE -eq 0) {
                return @{ Exe = $cmd.Source; Prefix = @($candidate.Args) }
            }
        } catch {
            continue
        }
    }
    throw 'Python 3.12 x64 was not found. GitHub Actions installs Python 3.12 automatically.'
}

$Python = Resolve-Python
function Invoke-PythonCommand {
    param([Parameter(Mandatory = $true)][string[]]$CommandArgs)
    & $Python.Exe @($Python.Prefix) @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

Write-Host '== Bitcoin Miner Studio Windows x64 Portable Builder ==' -ForegroundColor Cyan
Invoke-PythonCommand -CommandArgs @('-c', "import sys; print('Python:', sys.executable); print('Version:', sys.version)")

if (-not $SkipInstall) {
    Write-Host 'Installing release-build dependencies...'
    Invoke-PythonCommand -CommandArgs @('-m', 'pip', 'install', '--upgrade', 'pip')
    Invoke-PythonCommand -CommandArgs @('-m', 'pip', 'install', '-r', 'requirements.txt', 'pyinstaller>=6.14,<7')
}

Invoke-PythonCommand -CommandArgs @('-c', "import webview, py7zr, PyInstaller; print('pywebview:', getattr(webview, '__version__', 'installed')); print('py7zr:', py7zr.__version__); print('PyInstaller:', PyInstaller.__version__)")

# Preflight the exact Windows GUI runtime that pywebview uses. This catches
# pythonnet/CLR incompatibilities before PyInstaller publishes an unusable EXE.
Write-Host 'Preflighting pywebview WinForms/pythonnet runtime...'
Invoke-PythonCommand -CommandArgs @('-c', "import clr; import webview.platforms.winforms; print('WinForms/pythonnet preflight: OK')")

$ManifestPath = Join-Path $Root 'purple_dragon_manifest.json'
if (-not (Test-Path $ManifestPath -PathType Leaf)) {
    throw 'purple_dragon_manifest.json is missing.'
}
$Manifest = Get-Content $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Manifest.signature) {
    throw 'The source release is not publisher-signed. Refusing to build a public Windows package.'
}

$ProtectedFiles = @($Manifest.files.PSObject.Properties.Name)
if ($ProtectedFiles.Count -lt 1) {
    throw 'Purple Dragon protected-file list is empty.'
}

$BuildDir = Join-Path $Root 'build'
$DistDir = Join-Path $Root 'dist'
$ReleaseDir = Join-Path $Root 'release-windows'
Remove-Item $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $DistDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $ReleaseDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item $ReleaseDir -ItemType Directory | Out-Null

$PyInstallerArgs = @(
    '--noconfirm',
    '--clean',
    '--windowed',
    '--name=BitcoinMinerStudio',
    '--contents-directory=_internal',
    "--icon=$Root\assets\BitcoinMinerStudio.ico",
    "--version-file=$Root\windows_version_info.txt",
    '--collect-all=webview',
    '--collect-all=py7zr',
    '--collect-all=pythonnet',
    '--collect-all=clr_loader',
    '--hidden-import=clr',
    '--hidden-import=pythonnet'
)

foreach ($Relative in $ProtectedFiles) {
    $Source = Join-Path $Root $Relative
    if (-not (Test-Path $Source -PathType Leaf)) {
        throw "Protected source file is missing before build: $Relative"
    }
    $Destination = Split-Path $Relative -Parent
    if ([string]::IsNullOrWhiteSpace($Destination)) { $Destination = '.' }
    $PyInstallerArgs += "--add-data=$Source;$Destination"
}
$PyInstallerArgs += "--add-data=$ManifestPath;."
$PyInstallerArgs += (Join-Path $Root 'launch.pyw')

Write-Host "Building PyInstaller onedir package with $($ProtectedFiles.Count) Purple Dragon protected files..."
& $Python.Exe @($Python.Prefix) -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$PortableRoot = Join-Path $DistDir 'BitcoinMinerStudio'
$InternalRoot = Join-Path $PortableRoot '_internal'
$ExePath = Join-Path $PortableRoot 'BitcoinMinerStudio.exe'
if (-not (Test-Path $ExePath -PathType Leaf)) {
    throw 'BitcoinMinerStudio.exe was not produced.'
}
if (-not (Test-Path (Join-Path $InternalRoot 'purple_dragon_manifest.json') -PathType Leaf)) {
    throw 'Frozen package is missing the Purple Dragon manifest.'
}

$env:BMS_FROZEN_VERIFY_ROOT = $InternalRoot
$VerifyScript = @'
import json, os, sys
from purple_dragon_security import verify_integrity
root = os.environ['BMS_FROZEN_VERIFY_ROOT']
state = verify_integrity(root)
summary = {
    'trust_level': state.get('trust_level'),
    'signature_valid': state.get('signature_valid'),
    'files_verified': state.get('verified_file_count'),
    'files_total': state.get('protected_file_count'),
    'critical_controls_enabled': state.get('critical_actions_allowed'),
    'status': state.get('status'),
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
$VerifyScript | & $Python.Exe @($Python.Prefix) -
if ($LASTEXITCODE -ne 0) {
    throw 'Purple Dragon verification failed against the frozen package.'
}
Remove-Item Env:BMS_FROZEN_VERIFY_ROOT -ErrorAction SilentlyContinue

$ReadmeFirst = @"
Bitcoin Miner Studio v2.0.1 — Windows x64 Portable
==================================================

Launch: BitcoinMinerStudio.exe

Keep BitcoinMinerStudio.exe and the _internal folder together.
The source/developer launcher run.bat remains in the GitHub source tree; it is
not required for this portable build.

Purple Dragon Security verifies the signed protected application surfaces at
runtime. Windows Authenticode signing is a separate trust layer; SmartScreen
may show a publisher warning until the executable is Authenticode-signed with
a Windows code-signing certificate.
"@
Set-Content -Path (Join-Path $PortableRoot 'README-FIRST.txt') -Value $ReadmeFirst -Encoding UTF8

$Version = [string]$Manifest.version
$ZipName = "BitcoinMinerStudio-v$Version-Windows-x64.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName
Compress-Archive -Path (Join-Path $PortableRoot '*') -DestinationPath $ZipPath -CompressionLevel Optimal

$ExeHash = (Get-FileHash $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
$ZipHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$Checksums = @(
    "$ExeHash  BitcoinMinerStudio.exe",
    "$ZipHash  $ZipName"
)
$ChecksumPath = Join-Path $ReleaseDir 'SHA256SUMS-Windows.txt'
Set-Content -Path $ChecksumPath -Value $Checksums -Encoding ASCII

$BuildInfo = [ordered]@{
    product = 'Bitcoin Miner Studio'
    version = $Version
    platform = 'windows-x64'
    python = '3.12'
    packaging = 'pyinstaller-onedir'
    executable = 'BitcoinMinerStudio.exe'
    executable_sha256 = $ExeHash
    archive = $ZipName
    archive_sha256 = $ZipHash
    purple_dragon_build_id = [string]$Manifest.build_id
    purple_dragon_publisher_key_id = [string]$Manifest.publisher_key_id
    purple_dragon_protected_files = $ProtectedFiles.Count
}
$BuildInfo | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $ReleaseDir 'BitcoinMinerStudio-Windows-build.json') -Encoding UTF8

Write-Host ''
Write-Host 'Windows portable release created successfully.' -ForegroundColor Green
Write-Host "EXE: $ExePath"
Write-Host "ZIP: $ZipPath"
Write-Host "Checksums: $ChecksumPath"
