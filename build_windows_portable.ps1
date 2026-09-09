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
if (-not (Test-Path $ManifestPath -PathType Leaf)) {
    throw 'purple_dragon_manifest.json is missing.'
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

Write-Host '== Bitcoin Miner Studio Windows x64 Native WebView2 Builder ==' -ForegroundColor Cyan
Write-Host "Version: $Version"
Write-Host "Protected files: $($ProtectedFiles.Count)"

# Do not freeze Python, pywebview, or pythonnet. The first EXE builds proved that
# freezing this stack is the source of the CLR crash; replacing it with Qt fixed
# that crash but introduced a 200+ MB Chromium/Qt payload and slow startup.
# Instead, ship CPython's official embedded runtime and let pywebview use the
# native Microsoft Edge WebView2 runtime already present on supported Windows.
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

Write-Host 'Installing the minimal application runtime into _runtime...'
& $BuildPython -m pip install --disable-pip-version-check --no-warn-script-location --upgrade --target $SitePackages `
    'pywebview==6.2.1' 'pythonnet==3.1.0' 'py7zr==0.22.0'
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install the embedded application runtime.'
}

# Copy the exact signed application surface. Also copy complete UI/assets trees
# so non-code visual resources remain available without adding them to Python.
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
foreach ($ResourceDir in @('assets', 'ui')) {
    $SourceDir = Join-Path $Root $ResourceDir
    if (Test-Path $SourceDir -PathType Container) {
        Copy-Item -LiteralPath $SourceDir -Destination (Join-Path $PortableRoot $ResourceDir) -Recurse -Force
    }
}

# Build a tiny Windows launcher. It remains resident as the parent process and
# starts the bundled pythonw.exe with the signed launch.pyw. End users still
# double-click BitcoinMinerStudio.exe; no system Python installation is needed.
$LauncherSourcePath = Join-Path $BuildDir 'BitcoinMinerStudioLauncher.cs'
$ExePath = Join-Path $PortableRoot 'BitcoinMinerStudio.exe'
$AssemblyVersion = (($Version -split '[^0-9]+' | Where-Object { $_ -ne '' } | Select-Object -First 3) + @('0','0','0'))[0..2] -join '.'
$AssemblyVersion = "$AssemblyVersion.0"
$LauncherSource = @"
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

[assembly: AssemblyTitle("Bitcoin Miner Studio")]
[assembly: AssemblyProduct("Bitcoin Miner Studio")]
[assembly: AssemblyCompany("Purple Dragon Foundation ltd")]
[assembly: AssemblyVersion("$AssemblyVersion")]
[assembly: AssemblyFileVersion("$AssemblyVersion")]

internal static class Program
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBox(IntPtr hWnd, string text, string caption, uint type);

    [STAThread]
    private static int Main()
    {
        try
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string runtime = Path.Combine(root, "_runtime");
            string pythonw = Path.Combine(runtime, "pythonw.exe");
            string script = Path.Combine(root, "launch.pyw");

            if (!File.Exists(pythonw) || !File.Exists(script))
            {
                MessageBox(IntPtr.Zero,
                    "Bitcoin Miner Studio runtime files are missing. Re-extract the complete Windows package.",
                    "Bitcoin Miner Studio", 0x10);
                return 2;
            }

            var psi = new ProcessStartInfo
            {
                FileName = pythonw,
                Arguments = "\"" + script + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            psi.EnvironmentVariables["PYTHONHOME"] = runtime;
            psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            psi.EnvironmentVariables["PYWEBVIEW_GUI"] = "edgechromium";
            psi.EnvironmentVariables["PYTHONNET_RUNTIME"] = "netfx";

            using (Process child = Process.Start(psi))
            {
                if (child == null) return 3;
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception ex)
        {
            MessageBox(IntPtr.Zero, ex.Message, "Bitcoin Miner Studio", 0x10);
            return 1;
        }
    }
}
"@
Set-Content -Path $LauncherSourcePath -Value $LauncherSource -Encoding UTF8

$CscCandidates = @(
    "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)
$Csc = $CscCandidates | Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
if (-not $Csc) {
    throw 'Windows C# compiler was not found on the build runner.'
}
$IconPath = Join-Path $Root 'assets\BitcoinMinerStudio.ico'
& $Csc /nologo /target:winexe /platform:x64 /optimize+ "/win32icon:$IconPath" "/out:$ExePath" $LauncherSourcePath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $ExePath -PathType Leaf)) {
    throw 'Failed to build BitcoinMinerStudio.exe launcher.'
}

# Validate the exact embedded interpreter/runtime that users will receive.
$RuntimePython = Join-Path $RuntimeRoot 'python.exe'
$env:PYTHONHOME = $RuntimeRoot
$env:PYTHONNOUSERSITE = '1'
$env:PYWEBVIEW_GUI = 'edgechromium'
$env:PYTHONNET_RUNTIME = 'netfx'
Write-Host 'Preflighting embedded Python + pythonnet + Edge WebView2 backend...'
Push-Location $PortableRoot
try {
    & $RuntimePython -c "import sys, clr, webview; import webview.platforms.edgechromium; print('Embedded Python:', sys.version); print('Edge WebView2 backend import: OK')"
    if ($LASTEXITCODE -ne 0) {
        throw 'Embedded Edge WebView2 backend preflight failed.'
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
        throw 'Purple Dragon verification failed in the embedded runtime.'
    }
}
finally {
    Pop-Location
}

# Exercise the actual one-click launcher. launch.pyw writes startup-error.log on
# any startup exception, making this a much stronger test than importing modules.
Write-Host 'Running native WebView2 application startup smoke check...'
$StartupError = Join-Path $PortableRoot 'startup-error.log'
$BridgeLog = Join-Path $PortableRoot 'startup-bridge.log'
Remove-Item $StartupError, $BridgeLog -Force -ErrorAction SilentlyContinue
$Watch = [Diagnostics.Stopwatch]::StartNew()
$Launcher = Start-Process -FilePath $ExePath -WorkingDirectory $PortableRoot -PassThru
$WindowReady = $false
$ChildPid = $null
try {
    $Deadline = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $Deadline) {
        Start-Sleep -Milliseconds 250
        if (Test-Path $StartupError -PathType Leaf) {
            throw "Application startup failed: $(Get-Content $StartupError -Raw -ErrorAction SilentlyContinue)"
        }
        $Child = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($Launcher.Id)" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ieq 'pythonw.exe' } | Select-Object -First 1
        if ($Child) {
            $ChildPid = [int]$Child.ProcessId
            $P = Get-Process -Id $ChildPid -ErrorAction SilentlyContinue
            if ($P -and $P.MainWindowTitle -like 'Bitcoin Miner Studio v*') {
                $WindowReady = $true
                break
            }
        }
        if ($Launcher.HasExited) {
            throw "BitcoinMinerStudio.exe exited during startup with code $($Launcher.ExitCode)."
        }
    }

    if (-not $WindowReady) {
        if (-not $ChildPid -or -not (Get-Process -Id $ChildPid -ErrorAction SilentlyContinue)) {
            throw 'The embedded Python application did not remain alive during startup.'
        }
        Write-Host 'Application process is healthy; hosted runner did not expose a window handle.' -ForegroundColor Yellow
    } else {
        Write-Host ("Native WebView2 window ready in {0:N2}s" -f $Watch.Elapsed.TotalSeconds) -ForegroundColor Green
    }
}
finally {
    $Watch.Stop()
    if (-not $Launcher.HasExited) {
        & taskkill.exe /PID $Launcher.Id /T /F 2>$null | Out-Null
    }
}

if (Test-Path $StartupError -PathType Leaf) {
    throw "Application wrote startup-error.log: $(Get-Content $StartupError -Raw -ErrorAction SilentlyContinue)"
}

$ReadmeFirst = @"
Bitcoin Miner Studio v$Version — Windows x64 Portable
====================================================

Launch BitcoinMinerStudio.exe.

This distribution uses an embedded Python 3.12 runtime and the native Microsoft
Edge WebView2 renderer. Python does not need to be installed on the PC.

Keep BitcoinMinerStudio.exe, _runtime, purple_dragon_manifest.json, and the
signed application files together. Do not move the EXE out of this folder.

Microsoft Edge WebView2 Runtime is required. It is normally present on current
Windows 10/11 systems with Microsoft Edge installed.

Purple Dragon Security verifies the signed application files independently of
Windows Authenticode signing.
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
    distribution = 'native-launcher+embedded-python'
    python = $EmbeddedPythonVersion
    gui_backend = 'edgechromium-webview2'
    packaging = 'non-frozen'
    executable = 'BitcoinMinerStudio.exe'
    executable_sha256 = $ExeHash
    archive = $ZipName
    archive_sha256 = $ZipHash
    portable_files = $FileStats.Count
    portable_uncompressed_bytes = [int64]$Bytes
    startup_smoke = if ($WindowReady) { 'window-ready' } else { 'process-alive' }
    startup_smoke_seconds = [math]::Round($Watch.Elapsed.TotalSeconds, 3)
    purple_dragon_build_id = [string]$Manifest.build_id
    purple_dragon_publisher_key_id = [string]$Manifest.publisher_key_id
    purple_dragon_protected_files = $ProtectedFiles.Count
}
$BuildInfo | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $ReleaseDir 'BitcoinMinerStudio-Windows-build.json') -Encoding UTF8

Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue
Remove-Item Env:PYWEBVIEW_GUI -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONNET_RUNTIME -ErrorAction SilentlyContinue

Write-Host ''
Write-Host 'Native WebView2 Windows portable release created successfully.' -ForegroundColor Green
Write-Host "EXE: $ExePath"
Write-Host "ZIP: $ZipPath"
Write-Host "Files: $($FileStats.Count)"
Write-Host ("Uncompressed size: {0:N1} MiB" -f ($Bytes / 1MB))
Write-Host "SHA-256: $ZipHash"
