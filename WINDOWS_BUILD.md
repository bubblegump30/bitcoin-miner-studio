# Windows EXE build — Bitcoin Miner Studio v2.0.1

The Windows distribution now uses a **native launcher + embedded CPython + Microsoft Edge WebView2** architecture. It does **not** freeze pywebview/pythonnet with PyInstaller and it does **not** ship Qt/PySide6.

```text
BitcoinMinerStudio\
├─ BitcoinMinerStudio.exe        # tiny native Windows launcher
├─ launch.pyw                    # signed Purple Dragon entry point
├─ purple_dragon_manifest.json
├─ signed application files
├─ assets\
├─ ui\
├─ README-FIRST.txt
└─ _runtime\
   ├─ pythonw.exe
   ├─ python.exe
   ├─ python312.dll
   ├─ python312.zip
   └─ Lib\site-packages\
      ├─ pywebview
      ├─ pythonnet
      └─ py7zr
```

End users launch `BitcoinMinerStudio.exe`. No system Python installation is required.

## Why this architecture

Two frozen GUI approaches were tested and rejected:

1. PyInstaller + WinForms/pythonnet failed after freezing at `Python.Runtime.dll`, even though normal-interpreter checks passed.
2. PyInstaller + Qt/PySide6 started successfully but added a very large Chromium/Qt payload, slow cold starts, and rendering/compositing instability.

The production Windows package therefore keeps Python **non-frozen**, using CPython's official embedded runtime, and forces pywebview to use Windows' native `edgechromium` renderer backed by Microsoft Edge WebView2. This is substantially closer to the source/developer execution model that was already stable.

## Runtime requirements

- Windows 10/11 x64
- Microsoft Edge WebView2 Runtime

Current Windows 10/11 systems with Microsoft Edge normally already have WebView2. Python does not need to be installed.

## Build locally

The build host requires:

- Windows x64
- Python 3.12 x64
- Internet access to download the official CPython 3.12 embedded package and Python runtime dependencies

Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows_portable.ps1
```

Outputs are written to `release-windows/`:

```text
BitcoinMinerStudio-v2.0.1-Windows-x64.zip
SHA256SUMS-Windows.txt
BitcoinMinerStudio-Windows-build.json
```

## GitHub Actions

Run **Actions → Build Windows x64 Portable → Run workflow**. Pushing a `v*` tag also triggers the build.

The workflow builds the native launcher, creates the isolated embedded Python runtime, verifies the Edge WebView2/pythonnet import path in that exact runtime, verifies Purple Dragon, launches the actual packaged application as a startup smoke test, then publishes:

```text
BitcoinMinerStudio-Windows-x64
```

## Purple Dragon behavior

The packaging layer does not modify signed application files. It reads the existing signed `purple_dragon_manifest.json`, copies the exact protected bytes into the portable application root, and verifies them using the same embedded runtime shipped to users.

The publisher private key is **not required** for Windows packaging and must never be committed to GitHub or placed in GitHub Actions.

Purple Dragon provenance and Windows Authenticode are separate trust layers. Until `BitcoinMinerStudio.exe` is Authenticode-signed with a Windows code-signing certificate, Windows SmartScreen may still show an unknown-publisher warning even when Purple Dragon reports `TRUSTED`.
