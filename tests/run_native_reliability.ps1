[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SdkDirectory,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
$Output = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$Core = Get-ChildItem -LiteralPath $SdkDirectory -Recurse -Filter 'Microsoft.Web.WebView2.Core.dll' |
    Where-Object FullName -Match 'net462' | Select-Object -First 1
$Forms = Get-ChildItem -LiteralPath $SdkDirectory -Recurse -Filter 'Microsoft.Web.WebView2.WinForms.dll' |
    Where-Object FullName -Match 'net462' | Select-Object -First 1
if (-not $Core -or -not $Forms) { throw 'Pinned WebView2 SDK net462 assemblies are required.' }
Copy-Item -LiteralPath $Core.FullName -Destination $Output -Force
Copy-Item -LiteralPath $Forms.FullName -Destination $Output -Force
# Test-only substitutions match the packaging compiler. No signing/verification
# code is changed, and the fixture has no embedded runtime or mining backend.
$Source = Get-Content -LiteralPath (Join-Path $Root 'windows_native_host.cs') -Raw
$Source = $Source.Replace('__BMS_ASSEMBLY_VERSION__', '2.0.3.0').Replace('__BMS_BRIDGE_SHA256__', ('0' * 64))
$HostSource = Join-Path $Output 'host-test.cs'
[IO.File]::WriteAllText($HostSource, $Source)
$Executable = Join-Path $Output 'native-reliability.exe'
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:exe /main:NativeReliabilityTests "/out:$Executable" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll "/r:$($Core.FullName)" "/r:$($Forms.FullName)" `
    $HostSource (Join-Path $PSScriptRoot 'native_reliability.cs')
if ($LASTEXITCODE -ne 0) { throw 'Native reliability harness compilation failed.' }
& $Executable
if ($LASTEXITCODE -ne 0) { throw 'Native reliability harness failed.' }
