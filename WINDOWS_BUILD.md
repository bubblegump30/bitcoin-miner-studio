# Windows EXE build — Bitcoin Miner Studio v2.0.1

The normal public Windows distribution is a **PyInstaller `onedir` package**:

```text
BitcoinMinerStudio\
├─ BitcoinMinerStudio.exe
├─ purple_dragon_manifest.json
├─ signed protected application files
├─ README-FIRST.txt
└─ _internal\
   └─ bundled Python / Qt runtime dependencies
```

`run.bat` remains the source/developer fallback. End users should launch
`BitcoinMinerStudio.exe` from the Windows portable release.

## Build locally on Windows

Requirements:

- Windows 10/11 x64
- **Python 3.12 x64**
- Internet access for the initial dependency install

Python 3.12 is the pinned Windows release-builder runtime for v2.0.1.

The frozen public EXE uses pywebview's **Qt / PySide6** backend. The earlier
WinForms/pythonnet path passed normal-interpreter checks but failed after
PyInstaller freezing at `Python.Runtime.dll`. The Qt backend removes that CLR
runtime dependency from the public executable.

The build now performs both:

1. A normal Qt/PySide6 preflight before freezing.
2. A separate **frozen Qt smoke test** built with PyInstaller and executed on
   the Windows runner before any release artifact is uploaded.

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

Run it from **Actions → Build Windows x64 Portable → Run workflow**. Pushing a
`v*` tag also triggers the build. The workflow uses Python 3.12 x64 and installs
`pywebview[pyside6]` for the frozen Windows GUI runtime.

A successful build publishes a GitHub Actions artifact named:

```text
BitcoinMinerStudio-Windows-x64
```

## Purple Dragon behavior

The builder reads the already signed `purple_dragon_manifest.json` and preserves
the exact signed application bytes.

PyInstaller keeps bundled runtime data under `_internal`, but Purple Dragon's
frozen runtime resolves its verification base beside `BitcoinMinerStudio.exe`.
The builder therefore also places the signed manifest and protected files at
that actual runtime root and verifies **that location** before packaging.

The publisher private key is **not required** for this packaging step and must
never be placed in GitHub Actions or committed to the repository.

Purple Dragon and Windows Authenticode are separate trust layers. Until the
project has a Windows code-signing certificate, Windows SmartScreen may still
show an unknown-publisher warning for `BitcoinMinerStudio.exe` even when the
internal Purple Dragon report is `TRUSTED`.
