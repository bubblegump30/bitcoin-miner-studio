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
    Invoke-PythonCommand -CommandArgs @('-m', 'pip', 'install', '-r', 'requirements.txt', 'pywebview[pyside6]>=6.2,<7', 'pyinstaller>=6.14,<7')
}

Invoke-PythonCommand -CommandArgs @('-c', "import webview, py7zr, PyInstaller, PySide6; print('pywebview:', getattr(webview, '__version__', 'installed')); print('py7zr:', py7zr.__version__); print('PyInstaller:', PyInstaller.__version__); print('PySide6:', PySide6.__version__)")

# Public frozen builds use pywebview's Qt backend. The previous WinForms path
# depended on pythonnet/CLR and failed only after freezing, even though a normal
# interpreter preflight passed. Qt avoids that CLR dependency entirely.
Write-Host 'Preflighting pywebview Qt/PySide6 runtime...'
Invoke-PythonCommand -CommandArgs @('-c', "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from PySide6.QtWidgets import QApplication; app=QApplication([]); import webview.platforms.qt; print('Qt/PySide6 preflight: OK'); app.quit()")

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
New-Item $BuildDir -ItemType Directory | Out-Null
New-Item $ReleaseDir -ItemType Directory | Out-Null

# Force Qt before pywebview chooses a Windows backend. The hook is generated in
# the build workspace and embedded by PyInstaller; it is not shipped as an
# unsigned application source file.
$RuntimeHookPath = Join-Path $BuildDir 'pyi_rth_bms_qt.py'
@'
import os
os.environ['PYWEBVIEW_GUI'] = 'qt'
'@ | Set-Content -Path $RuntimeHookPath -Encoding ASCII

$PyInstallerArgs = @(
    '--noconfirm',
    '--clean',
    '--windowed',
    '--name=BitcoinMinerStudio',
    '--contents-directory=_internal',
    "--icon=$Root\assets\BitcoinMinerStudio.ico",
    "--version-file=$Root\windows_version_info.txt",
    "--runtime-hook=$RuntimeHookPath",
    '--collect-all=webview',
    '--collect-all=py7zr',
    '--hidden-import=webview.platforms.qt',
    '--hidden-import=PySide6.QtCore',
    '--hidden-import=PySide6.QtGui',
    '--hidden-import=PySide6.QtWidgets',
    '--hidden-import=PySide6.QtWebChannel',
    '--hidden-import=PySide6.QtWebEngineCore',
    '--hidden-import=PySide6.QtWebEngineWidgets',
    '--exclude-module=clr',
    '--exclude-module=pythonnet',
    '--exclude-module=clr_loader',
    '--exclude-module=webview.platforms.winforms'
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

# PyInstaller stores added data under _internal, while Purple Dragon's frozen
# runtime resolves its verification root beside BitcoinMinerStudio.exe. Copy
# the exact signed surfaces to the portable root as well so runtime trust uses
# the same 67/67 bytes that were signed. The embedded runtime copies remain for
# normal module/data resolution.
foreach ($Relative in $ProtectedFiles) {
    $Source = Join-Path $InternalRoot $Relative
    $Destination = Join-Path $PortableRoot $Relative
    if (-not (Test-Path $Source -PathType Leaf)) {
        throw "Frozen package is missing protected file: $Relative"
    }
    $DestinationDir = Split-Path $Destination -Parent
    if (-not (Test-Path $DestinationDir)) {
        New-Item $DestinationDir -ItemType Directory -Force | Out-Null
    }
    Copy-Item $Source $Destination -Force
}
Copy-Item (Join-Path $InternalRoot 'purple_dragon_manifest.json') (Join-Path $PortableRoot 'purple_dragon_manifest.json') -Force

# Verify the actual runtime root, not only the PyInstaller _internal directory.
$env:BMS_FROZEN_VERIFY_ROOT = $PortableRoot
$VerifyScript = @'
import json, os
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
    throw 'Purple Dragon verification failed against the actual portable runtime root.'
}
Remove-Item Env:BMS_FROZEN_VERIFY_ROOT -ErrorAction SilentlyContinue

# Build and execute a tiny frozen Qt probe. This specifically tests the layer
# that failed in the first two artifacts: importing and initializing the GUI
# backend after PyInstaller freezing.
Write-Host 'Running frozen Qt backend smoke test...'
$SmokeSource = Join-Path $BuildDir 'bms_qt_frozen_smoke.py'
$SmokeDist = Join-Path $BuildDir 'smoke-dist'
$SmokeWork = Join-Path $BuildDir 'smoke-work'
$SmokeSpec = Join-Path $BuildDir 'smoke-spec'
New-Item $SmokeSpec -ItemType Directory -Force | Out-Null
@'
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYWEBVIEW_GUI'] = 'qt'
from PySide6.QtWidgets import QApplication
app = QApplication([])
import webview.platforms.qt
app.quit()
raise SystemExit(0)
'@ | Set-Content -Path $SmokeSource -Encoding ASCII

$SmokeArgs = @(
    '--noconfirm',
    '--clean',
    '--console',
    '--name=BMSQtFrozenSmoke',
    "--distpath=$SmokeDist",
    "--workpath=$SmokeWork",
    "--specpath=$SmokeSpec",
    "--runtime-hook=$RuntimeHookPath",
    '--hidden-import=webview.platforms.qt',
    '--hidden-import=PySide6.QtWebChannel',
    '--hidden-import=PySide6.QtWebEngineWidgets',
    '--exclude-module=clr',
    '--exclude-module=pythonnet',
    '--exclude-module=clr_loader',
    '--exclude-module=webview.platforms.winforms',
    $SmokeSource
)
& $Python.Exe @($Python.Prefix) -m PyInstaller @SmokeArgs
if ($LASTEXITCODE -ne 0) {
    throw 'Frozen Qt smoke-test build failed.'
}
$SmokeExe = Join-Path $SmokeDist 'BMSQtFrozenSmoke\BMSQtFrozenSmoke.exe'
if (-not (Test-Path $SmokeExe -PathType Leaf)) {
    throw 'Frozen Qt smoke-test executable was not produced.'
}
$SmokeProcess = Start-Process -FilePath $SmokeExe -PassThru -Wait -NoNewWindow
if ($SmokeProcess.ExitCode -ne 0) {
    throw "Frozen Qt backend smoke test failed with exit code $($SmokeProcess.ExitCode)."
}
Write-Host 'Frozen Qt backend smoke test: OK' -ForegroundColor Green

$ReadmeFirst = @"
Bitcoin Miner Studio v2.0.1 — Windows x64 Portable
==================================================

Launch: BitcoinMinerStudio.exe

Keep BitcoinMinerStudio.exe, purple_dragon_manifest.json, the signed application
files, and the _internal folder together. Do not move the EXE out of this folder.

The Windows portable build uses pywebview's Qt / PySide6 backend. Python is not
required on the destination PC.

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
    gui_backend = 'qt-pyside6'
    packaging = 'pyinstaller-onedir'
    executable = 'BitcoinMinerStudio.exe'
    executable_sha256 = $ExeHash
    archive = $ZipName
    archive_sha256 = $ZipHash
    purple_dragon_build_id = [string]$Manifest.build_id
    purple_dragon_publisher_key_id = [string]$Manifest.publisher_key_id
    purple_dragon_protected_files = $ProtectedFiles.Count
    frozen_gui_smoke_test = 'passed'
}
$BuildInfo | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $ReleaseDir 'BitcoinMinerStudio-Windows-build.json') -Encoding UTF8

Write-Host ''
Write-Host 'Windows portable release created successfully.' -ForegroundColor Green
Write-Host "EXE: $ExePath"
Write-Host "ZIP: $ZipPath"
Write-Host "Checksums: $ChecksumPath"
