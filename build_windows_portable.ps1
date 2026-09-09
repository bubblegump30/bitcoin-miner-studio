[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'Bitcoin Miner Studio Windows releases must be built on 64-bit Windows.'
}

$BuildPython = (Get-Command python -ErrorAction Stop).Source
& $BuildPython -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) and sys.maxsize > 2**32 else 1)"
if ($LASTEXITCODE -ne 0) {
    throw 'The build host must provide Python 3.12 x64.'
}

$ManifestPath = Join-Path $Root 'purple_dragon_manifest.json'
$BridgeSourcePath = Join-Path $Root 'windows_native_bridge.py'
$HostTemplatePath = Join-Path $Root 'windows_native_host.cs'
foreach ($Required in @($ManifestPath, $BridgeSourcePath, $HostTemplatePath)) {
    if (-not (Test-Path $Required -PathType Leaf)) {
        throw "Required Windows release source is missing: $Required"
    }
}

$Manifest = Get-Content $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Manifest.signature) {
    throw 'The source release is not publisher-signed. Refusing to package it.'
}
$ProtectedFiles = @($Manifest.files.PSObject.Properties.Name)
if ($ProtectedFiles.Count -lt 1) {
    throw 'Purple Dragon protected-file list is empty.'
}
$Version = [string]$Manifest.version

$BuildDir = Join-Path $Root 'build-windows-native'
$DistDir = Join-Path $Root 'dist'
$PortableRoot = Join-Path $DistDir 'BitcoinMinerStudio'
$RuntimeRoot = Join-Path $PortableRoot '_runtime'
$SitePackages = Join-Path $RuntimeRoot 'Lib\site-packages'
$ReleaseDir = Join-Path $Root 'release-windows'

Remove-Item $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $DistDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $ReleaseDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item $BuildDir -ItemType Directory -Force | Out-Null
New-Item $PortableRoot -ItemType Directory -Force | Out-Null
New-Item $RuntimeRoot -ItemType Directory -Force | Out-Null
New-Item $SitePackages -ItemType Directory -Force | Out-Null
New-Item $ReleaseDir -ItemType Directory -Force | Out-Null

Write-Host '== Bitcoin Miner Studio Windows x64 DIRECT WebView2 Builder ==' -ForegroundColor Cyan
Write-Host "Version: $Version"
Write-Host "Protected files: $($ProtectedFiles.Count)"
Write-Host 'GUI architecture: C# WinForms + Microsoft Edge WebView2'
Write-Host 'Python bridge: private stdin/stdout JSON transport'
Write-Host 'pywebview/pythonnet/Qt/PyInstaller: NOT USED'

# ---------------------------------------------------------------------------
# 1. Official embedded CPython runtime
# ---------------------------------------------------------------------------
$EmbeddedPythonVersion = '3.12.10'
$EmbeddedZip = Join-Path $BuildDir "python-$EmbeddedPythonVersion-embed-amd64.zip"
$EmbeddedUrl = "https://www.python.org/ftp/python/$EmbeddedPythonVersion/python-$EmbeddedPythonVersion-embed-amd64.zip"
Write-Host "Downloading official CPython $EmbeddedPythonVersion embedded runtime..."
Invoke-WebRequest -Uri $EmbeddedUrl -OutFile $EmbeddedZip -UseBasicParsing
Expand-Archive -LiteralPath $EmbeddedZip -DestinationPath $RuntimeRoot -Force

$PthPath = Join-Path $RuntimeRoot 'python312._pth'
@(
    'python312.zip',
    '.',
    'Lib\site-packages',
    '..',
    'import site'
) | Set-Content -Path $PthPath -Encoding ASCII

# The backend needs py7zr for release/update package inspection.  Do NOT install
# pywebview, pythonnet, clr-loader, PySide6, Qt, or PyInstaller in this runtime.
Write-Host 'Installing minimal non-GUI Python runtime dependencies...'
& $BuildPython -m pip install --disable-pip-version-check --no-warn-script-location --upgrade --target $SitePackages `
    'py7zr==0.22.0'
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install the embedded Python runtime dependencies.'
}

# ---------------------------------------------------------------------------
# 2. Copy the exact signed Bitcoin Miner Studio application surface
# ---------------------------------------------------------------------------
foreach ($Relative in $ProtectedFiles) {
    $Source = Join-Path $Root $Relative
    if (-not (Test-Path $Source -PathType Leaf)) {
        throw "Protected source file is missing: $Relative"
    }
    $Destination = Join-Path $PortableRoot $Relative
    $DestinationDir = Split-Path $Destination -Parent
    if (-not (Test-Path $DestinationDir)) {
        New-Item $DestinationDir -ItemType Directory -Force | Out-Null
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}
Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $PortableRoot 'purple_dragon_manifest.json') -Force

# Copy any non-protected visual resources without creating nested ui/ui or
# assets/assets directories when protected files already created the folder.
foreach ($ResourceDir in @('assets', 'ui')) {
    $SourceDir = Join-Path $Root $ResourceDir
    $DestinationDir = Join-Path $PortableRoot $ResourceDir
    if (Test-Path $SourceDir -PathType Container) {
        New-Item $DestinationDir -ItemType Directory -Force | Out-Null
        Get-ChildItem -LiteralPath $SourceDir -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $DestinationDir -Recurse -Force
        }
    }
}

# Runtime bridge is intentionally isolated under _runtime.  The compiled host
# contains and checks its exact SHA-256 before Python is allowed to execute it.
$BridgeRuntimePath = Join-Path $RuntimeRoot 'bms_native_bridge.py'
Copy-Item -LiteralPath $BridgeSourcePath -Destination $BridgeRuntimePath -Force
$BridgeHash = (Get-FileHash $BridgeRuntimePath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Native bridge SHA-256: $BridgeHash"

# ---------------------------------------------------------------------------
# 3. Microsoft WebView2 SDK: host WebView2 directly, no pywebview/pythonnet
# ---------------------------------------------------------------------------
$WebView2Version = '1.0.4191.47'
$WebViewPackage = Join-Path $BuildDir "Microsoft.Web.WebView2.$WebView2Version.nupkg"
$WebViewPackageZip = "$WebViewPackage.zip"
$WebViewSdk = Join-Path $BuildDir 'webview2-sdk'
$WebViewUrl = "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/$WebView2Version"
Write-Host "Downloading Microsoft.Web.WebView2 $WebView2Version..."
Invoke-WebRequest -Uri $WebViewUrl -OutFile $WebViewPackage -UseBasicParsing
Copy-Item $WebViewPackage $WebViewPackageZip -Force
Expand-Archive -LiteralPath $WebViewPackageZip -DestinationPath $WebViewSdk -Force

$CoreDll = Get-ChildItem $WebViewSdk -Recurse -Filter 'Microsoft.Web.WebView2.Core.dll' -File |
    Where-Object { $_.FullName -match '[\\/]lib[\\/]net462[\\/]' } | Select-Object -First 1
$WinFormsDll = Get-ChildItem $WebViewSdk -Recurse -Filter 'Microsoft.Web.WebView2.WinForms.dll' -File |
    Where-Object { $_.FullName -match '[\\/]lib[\\/]net462[\\/]' } | Select-Object -First 1
$LoaderDll = Get-ChildItem $WebViewSdk -Recurse -Filter 'WebView2Loader.dll' -File |
    Where-Object { $_.FullName -match '[\\/]runtimes[\\/]win-x64[\\/]native[\\/]' } | Select-Object -First 1
if (-not $CoreDll -or -not $WinFormsDll -or -not $LoaderDll) {
    throw 'The Microsoft WebView2 NuGet package did not contain the expected net462/x64 runtime files.'
}

Copy-Item $CoreDll.FullName (Join-Path $PortableRoot 'Microsoft.Web.WebView2.Core.dll') -Force
Copy-Item $WinFormsDll.FullName (Join-Path $PortableRoot 'Microsoft.Web.WebView2.WinForms.dll') -Force
Copy-Item $LoaderDll.FullName (Join-Path $PortableRoot 'WebView2Loader.dll') -Force

# ---------------------------------------------------------------------------
# 4. Compile the direct native WebView2 host
# ---------------------------------------------------------------------------
$AssemblyParts = @($Version -split '[^0-9]+' | Where-Object { $_ -ne '' } | Select-Object -First 3)
while ($AssemblyParts.Count -lt 3) { $AssemblyParts += '0' }
$AssemblyVersion = "$($AssemblyParts[0]).$($AssemblyParts[1]).$($AssemblyParts[2]).0"
$HostSource = Get-Content $HostTemplatePath -Raw -Encoding UTF8
$HostSource = $HostSource.Replace('__BMS_ASSEMBLY_VERSION__', $AssemblyVersion)
$HostSource = $HostSource.Replace('__BMS_BRIDGE_SHA256__', $BridgeHash)
$CompiledHostSource = Join-Path $BuildDir 'BitcoinMinerStudioHost.cs'
Set-Content -Path $CompiledHostSource -Value $HostSource -Encoding UTF8

$CscCandidates = @(
    "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)
$Csc = $CscCandidates | Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
if (-not $Csc) {
    throw 'Windows .NET Framework C# compiler was not found on the build runner.'
}

$ExePath = Join-Path $PortableRoot 'BitcoinMinerStudio.exe'
$IconPath = Join-Path $Root 'assets\BitcoinMinerStudio.ico'
& $Csc /nologo /target:winexe /platform:x64 /optimize+ /langversion:latest `
    /reference:System.dll `
    /reference:System.Core.dll `
    /reference:System.Drawing.dll `
    /reference:System.Windows.Forms.dll `
    /reference:System.Web.Extensions.dll `
    "/reference:$($CoreDll.FullName)" `
    "/reference:$($WinFormsDll.FullName)" `
    "/win32icon:$IconPath" `
    "/out:$ExePath" `
    $CompiledHostSource
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $ExePath -PathType Leaf)) {
    throw 'Failed to compile the direct WebView2 BitcoinMinerStudio.exe host.'
}

# ---------------------------------------------------------------------------
# 5. Verify embedded runtime and Purple Dragon before launching anything
# ---------------------------------------------------------------------------
$RuntimePython = Join-Path $RuntimeRoot 'python.exe'
$env:PYTHONHOME = $RuntimeRoot
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'

Write-Host 'Checking that banned GUI/runtime stacks are absent...'
Push-Location $PortableRoot
try {
    & $RuntimePython -c "import importlib.util, sys; banned=['webview','pythonnet','clr_loader','PySide6','PyInstaller']; present=[x for x in banned if importlib.util.find_spec(x) is not None]; print('Embedded Python:', sys.version); print('Banned runtime modules present:', present); raise SystemExit(11 if present else 0)"
    if ($LASTEXITCODE -ne 0) {
        throw 'A banned pywebview/pythonnet/Qt/PyInstaller runtime module leaked into the public EXE package.'
    }

    & $RuntimePython -c "import py7zr; from webview_app import WebBackend; b=WebBackend(); print('Backend construction: OK'); b.close()"
    if ($LASTEXITCODE -ne 0) {
        throw 'The embedded backend construction preflight failed.'
    }

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
        throw 'Purple Dragon verification failed in the direct WebView2 release tree.'
    }
}
finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# 6. Full application smoke test through the REAL EXE + bridge + WebView2
# ---------------------------------------------------------------------------
Write-Host 'Running full direct-WebView2 application smoke test...'
$StartupError = Join-Path $PortableRoot 'startup-error.log'
$BackendLog = Join-Path $PortableRoot 'native-backend.log'
$SmokeResult = Join-Path $PortableRoot 'native-smoke.json'
Remove-Item $StartupError, $BackendLog, $SmokeResult -Force -ErrorAction SilentlyContinue

$SmokeProcess = Start-Process -FilePath $ExePath -ArgumentList '--smoke-test' -WorkingDirectory $PortableRoot -PassThru
if (-not $SmokeProcess.WaitForExit(45000)) {
    try { & taskkill.exe /PID $SmokeProcess.Id /T /F 2>$null | Out-Null } catch { }
    throw 'BitcoinMinerStudio.exe did not complete its full native WebView2 smoke test within 45 seconds.'
}
if ($SmokeProcess.ExitCode -ne 0) {
    $Details = ''
    if (Test-Path $StartupError) { $Details += "`nstartup-error.log:`n" + (Get-Content $StartupError -Raw -ErrorAction SilentlyContinue) }
    if (Test-Path $BackendLog) { $Details += "`nnative-backend.log:`n" + (Get-Content $BackendLog -Raw -ErrorAction SilentlyContinue) }
    throw "Direct WebView2 smoke test failed with exit code $($SmokeProcess.ExitCode).$Details"
}
if (-not (Test-Path $SmokeResult -PathType Leaf)) {
    throw 'The direct WebView2 smoke test exited without producing native-smoke.json.'
}
$Smoke = Get-Content $SmokeResult -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$Smoke.ok) {
    throw 'The direct WebView2 bridge smoke test reported failure.'
}
Write-Host ("Full native bridge/WebView2 startup passed in {0:N2}s" -f ([double]$Smoke.startup_ms / 1000.0)) -ForegroundColor Green

# Smoke/debug files must never ship.
Remove-Item $StartupError, $BackendLog, $SmokeResult -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# 7. Package release assets
# ---------------------------------------------------------------------------
$ReadmeFirst = @"
Bitcoin Miner Studio v$Version — Windows x64 Portable
====================================================

Launch: BitcoinMinerStudio.exe

Windows runtime architecture
----------------------------
- Native C# WinForms host
- Microsoft Edge WebView2 renderer
- Embedded CPython $EmbeddedPythonVersion backend
- Private stdin/stdout JSON bridge
- No PyInstaller
- No Qt / PySide6
- No pywebview in the public EXE runtime
- No pythonnet / CLR bridge in the public EXE runtime

Python does not need to be installed on the destination PC.
Microsoft Edge WebView2 Runtime is required and is normally already installed
on current Windows 10/11 systems with Microsoft Edge.

Keep the complete folder together. Purple Dragon Security continues to verify
the signed Bitcoin Miner Studio application files independently of the native
Windows host.
"@
Set-Content -Path (Join-Path $PortableRoot 'README-FIRST.txt') -Value $ReadmeFirst -Encoding UTF8

$ZipName = "BitcoinMinerStudio-v$Version-Windows-x64.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName
Compress-Archive -Path (Join-Path $PortableRoot '*') -DestinationPath $ZipPath -CompressionLevel Optimal

$ExeHash = (Get-FileHash $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
$ZipHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path (Join-Path $ReleaseDir 'SHA256SUMS-Windows.txt') -Encoding ASCII -Value @(
    "$ExeHash  BitcoinMinerStudio.exe",
    "$ZipHash  $ZipName"
)

$FileStats = @(Get-ChildItem $PortableRoot -Recurse -File -Force)
$Bytes = ($FileStats | Measure-Object -Property Length -Sum).Sum
$BuildInfo = [ordered]@{
    product = 'Bitcoin Miner Studio'
    version = $Version
    platform = 'windows-x64'
    distribution = 'direct-webview2-host+embedded-python'
    python = $EmbeddedPythonVersion
    webview2_sdk = $WebView2Version
    gui_backend = 'microsoft-edge-webview2-direct'
    bridge_transport = 'stdio-json-v1'
    packaging = 'non-frozen'
    pywebview_in_runtime = $false
    pythonnet_in_runtime = $false
    qt_in_runtime = $false
    pyinstaller_in_runtime = $false
    executable = 'BitcoinMinerStudio.exe'
    executable_sha256 = $ExeHash
    archive = $ZipName
    archive_sha256 = $ZipHash
    portable_files = $FileStats.Count
    portable_uncompressed_bytes = [int64]$Bytes
    startup_smoke = 'passed'
    startup_smoke_seconds = [math]::Round(([double]$Smoke.startup_ms / 1000.0), 3)
    bridge_sha256 = $BridgeHash
    purple_dragon_build_id = [string]$Manifest.build_id
    purple_dragon_publisher_key_id = [string]$Manifest.publisher_key_id
    purple_dragon_protected_files = $ProtectedFiles.Count
}
$BuildInfo | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $ReleaseDir 'BitcoinMinerStudio-Windows-build.json') -Encoding UTF8

Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue

Write-Host ''
Write-Host 'DIRECT WebView2 Windows portable release created successfully.' -ForegroundColor Green
Write-Host "EXE: $ExePath"
Write-Host "ZIP: $ZipPath"
Write-Host "Portable files: $($FileStats.Count)"
Write-Host ("Portable size: {0:N1} MiB" -f ([double]$Bytes / 1MB))
Write-Host "ZIP SHA-256: $ZipHash"
