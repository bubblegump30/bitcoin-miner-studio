[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PrivateKeyPath,
    [switch]$NoPush
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root
$ExpectedBranch = 'release/v2.0.3-reliability-support'
if ((& git branch --show-current).Trim() -ne $ExpectedBranch) { throw "Use branch $ExpectedBranch." }
if (git status --porcelain) { throw 'Commit reviewed source changes before offline publisher signing.' }
$Info = Get-Content -LiteralPath release_info.json -Raw | ConvertFrom-Json
if ($Info.version -ne '2.0.3' -or $Info.stability -ne 'Release Candidate') { throw 'Expected prepared v2.0.3 reliability candidate metadata.' }
$Key = (Resolve-Path -LiteralPath $PrivateKeyPath).Path
if ($Key.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Keep publisher key material outside the repository.'
}
& py -X utf8 tools/purple_dragon_sign.py $Key
if ($LASTEXITCODE -ne 0) { throw 'Offline publisher signing failed.' }
@'
import ast
import json
from pathlib import Path
from purple_dragon_security import verify_integrity
tree = ast.parse(Path('tools/purple_dragon_sign.py').read_text(encoding='utf-8'))
required = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PROTECTED_FILES' for target in node.targets))
state = verify_integrity()
assert state['trust_level'] == 'TRUSTED' and state['signature_valid'] is True
assert state['critical_actions_allowed'] is True and state['release_version'] == '2.0.3'
assert state['protected_file_count'] == state['verified_file_count'] == len(required)
print(json.dumps({key:state[key] for key in ('trust_level','publisher_key_id','release_version','build_id','protected_file_count','verified_file_count')},indent=2))
'@ | py -X utf8 -
if ($LASTEXITCODE -ne 0) { throw 'Post-sign publisher trust verification failed.' }
$Changed = @(git status --porcelain)
if ($Changed.Count -ne 1 -or $Changed[0] -notmatch 'purple_dragon_manifest\.json$') { throw 'Signing changed unexpected files.' }
git add -- purple_dragon_manifest.json
git commit -m 'Sign v2.0.3 reliability candidate with existing Purple Dragon identity'
if ($LASTEXITCODE -ne 0) { throw 'Could not commit signed manifest.' }
if (-not $NoPush) {
    git push origin $ExpectedBranch
    if ($LASTEXITCODE -ne 0) { throw 'Signed commit is local; branch push failed.' }
}
