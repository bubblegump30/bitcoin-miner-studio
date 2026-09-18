[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PrivateKeyPath,
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$ExpectedBranch = 'release/v2.0.2-public-readiness'
$Branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $Branch -ne $ExpectedBranch) {
    throw "Run this helper from branch '$ExpectedBranch'. Current branch: '$Branch'."
}

if (git status --porcelain) {
    throw 'Working tree is not clean. Commit or discard local changes before publisher signing.'
}

$Key = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $PrivateKeyPath).Path)
if (-not (Test-Path -LiteralPath $Key -PathType Leaf)) {
    throw 'Publisher private key file was not found.'
}

Write-Host '== Bitcoin Miner Studio v2.0.2 offline publisher signing ==' -ForegroundColor Cyan
Write-Host 'The private key remains local and is never added to Git.'

# Windows PowerShell can promote native stderr from a failed import probe into a
# terminating NativeCommandError when ErrorActionPreference is Stop. Avoid that
# fragile probe: pip install is idempotent and safely reports "Requirement
# already satisfied" when the dependency is present.
Write-Host 'Ensuring local developer signing dependency: cryptography'
& py -m pip install --disable-pip-version-check 'cryptography>=43,<47'
if ($LASTEXITCODE -ne 0) {
    throw 'Could not install or verify the cryptography signing dependency.'
}

& py -c "import cryptography; print('cryptography', cryptography.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw 'The Python launcher cannot import cryptography after installation.'
}

& py tools\purple_dragon_sign.py $Key
if ($LASTEXITCODE -ne 0) {
    throw 'Purple Dragon publisher signing failed.'
}

$Verify = @'
import json
from purple_dragon_security import verify_integrity
state = verify_integrity()
summary = {
    "trust_level": state.get("trust_level"),
    "signature_valid": state.get("signature_valid"),
    "version": state.get("release_version"),
    "build_id": state.get("build_id"),
    "provenance_tag": state.get("provenance_tag"),
    "release_seal": state.get("release_seal"),
    "files_verified": state.get("verified_file_count"),
    "files_total": state.get("protected_file_count"),
    "critical_controls_enabled": state.get("critical_actions_allowed"),
}
print(json.dumps(summary, indent=2))
ok = (
    state.get("trust_level") == "TRUSTED"
    and state.get("signature_valid") is True
    and state.get("release_version") == "2.0.2"
    and state.get("verified_file_count") == 73
    and state.get("protected_file_count") == 73
    and state.get("critical_actions_allowed") is True
)
raise SystemExit(0 if ok else 9)
'@
$Verify | py -
if ($LASTEXITCODE -ne 0) {
    throw 'Local post-sign verification failed. The manifest will not be committed.'
}

$Changed = @(git status --porcelain)
if ($Changed.Count -ne 1 -or $Changed[0] -notmatch 'purple_dragon_manifest\.json$') {
    throw "Signing changed unexpected repository files:`n$($Changed -join "`n")"
}

& git add -- purple_dragon_manifest.json
& git commit -m 'Sign v2.0.2 Purple Dragon release manifest'
if ($LASTEXITCODE -ne 0) {
    throw 'Could not commit the signed v2.0.2 manifest.'
}

if (-not $NoPush) {
    & git push origin $ExpectedBranch
    if ($LASTEXITCODE -ne 0) {
        throw 'Signed manifest was committed locally but could not be pushed.'
    }
    Write-Host 'Signed v2.0.2 manifest pushed. Signed validation/build CI will start automatically.' -ForegroundColor Green
}
else {
    Write-Host 'Signed v2.0.2 manifest committed locally. Push it when ready to start signed validation/build CI.' -ForegroundColor Yellow
}
