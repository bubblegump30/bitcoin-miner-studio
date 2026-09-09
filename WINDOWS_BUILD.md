# Windows EXE build — Bitcoin Miner Studio v2.0.1

The normal public Windows distribution is a **PyInstaller `onedir` package**:

```text
BitcoinMinerStudio\
├─ BitcoinMinerStudio.exe
├─ README-FIRST.txt
└─ _internal\
   ├─ purple_dragon_manifest.json
   ├─ signed protected source/UI files
   └─ bundled Python/runtime dependencies
```

`run.bat` remains the source/developer fallback. End users should launch
`BitcoinMinerStudio.exe` from the Windows portable release.

## Build locally on Windows

Requirements:

- Windows 10/11 x64
- Python 3.11+ x64 (3.13 recommended)
- Internet access for the initial dependency install

From PowerShell in the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows_portable.ps1
```

The build appears under `release-windows/`:

```text
BitcoinMinerStudio-v2.0.1-Windows-x64.zip
SHA256SUMS-Windows.txt
BitcoinMinerStudio-Windows-build.json
```

## Build with GitHub Actions

The repository includes `.github/workflows/windows-portable.yml`.

You can run it from **Actions → Build Windows x64 Portable → Run workflow**.
Pushing a `v*` tag also triggers the build. The workflow publishes a GitHub
Actions artifact named `BitcoinMinerStudio-Windows-x64` containing the ZIP,
checksums, and build metadata.

## Purple Dragon behavior

The builder reads the already signed `purple_dragon_manifest.json`, includes
all protected source/UI surfaces in the frozen `_internal` directory, and
verifies the copied package against the signed manifest before creating the
ZIP. The publisher private key is **not required** for this packaging step and
must never be placed in GitHub Actions or committed to the repository.

Purple Dragon and Windows Authenticode are separate trust layers. Until the
project has a Windows code-signing certificate, Windows SmartScreen may still
show an unknown-publisher warning for `BitcoinMinerStudio.exe` even when the
internal Purple Dragon report is `TRUSTED`.
