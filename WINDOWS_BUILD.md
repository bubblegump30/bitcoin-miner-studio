# Windows EXE build — Bitcoin Miner Studio v2.0.1

The public Windows distribution uses a **direct native WebView2 host + embedded CPython backend**.

It does **not** use PyInstaller, Qt/PySide6, pywebview, pythonnet, clr-loader, or a frozen Python GUI runtime.

```text
BitcoinMinerStudio\
├─ BitcoinMinerStudio.exe
├─ Microsoft.Web.WebView2.Core.dll
├─ Microsoft.Web.WebView2.WinForms.dll
├─ WebView2Loader.dll
├─ purple_dragon_manifest.json
├─ signed Bitcoin Miner Studio application files
├─ ui\
├─ assets\
└─ _runtime\
   ├─ python.exe
   ├─ pythonw.exe
   ├─ python312.dll
   ├─ python312.zip
   ├─ bms_native_bridge.py
   └─ Lib\site-packages\
      └─ py7zr and its runtime dependencies
```

`run.bat` remains the source/developer launcher. The public portable release is launched with `BitcoinMinerStudio.exe`.

## Why this architecture exists

The first EXE packaging attempts exposed two independent problems:

1. PyInstaller + pywebview WinForms could fail at the pythonnet `Python.Runtime.dll` loader boundary.
2. Replacing WinForms with Qt/PySide6 removed that CLR failure, but added a very large Chromium/Qt runtime, slower cold startup, and rendering/compositing instability on the target Windows machine.

The current design removes both problem layers rather than tuning them:

```text
BitcoinMinerStudio.exe
        │
        ├── Microsoft Edge WebView2 (native C# host)
        │
        └── embedded CPython 3.12 backend
                 │
                 └── private stdin/stdout JSON bridge
```

The JavaScript interface still sees the existing `window.pywebview.api` shape through a compatibility proxy injected by the native host, so the signed UI does not need to be rewritten for this distribution.

## Native bridge

`windows_native_bridge.py` adapts the existing signed `WebBackend` and explicit `api_contract.py` method list to a private line-delimited JSON channel.

The channel:

- uses inherited stdin/stdout handles only;
- does not open a TCP/HTTP port;
- does not create firewall rules;
- exposes only methods already listed in `EXPOSED_API_METHODS`;
- preserves the existing Purple Dragon critical-action gating inside the backend;
- routes the existing file/folder picker calls to native Windows dialogs;
- keeps the existing dependency-free Windows tray manager connected to the native host.

The compiled EXE embeds the bridge SHA-256 and refuses to run a changed bridge file.

## Build locally

Requirements:

- Windows 10/11 x64
- Python 3.12 x64 on the build machine
- Internet access while building, to download the official CPython embedded runtime and Microsoft WebView2 SDK package

Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows_portable.ps1
```

The build outputs:

```text
release-windows\
├─ BitcoinMinerStudio-v2.0.1-Windows-x64.zip
├─ SHA256SUMS-Windows.txt
└─ BitcoinMinerStudio-Windows-build.json
```

## GitHub Actions

Run:

**Actions → Build Windows x64 Portable → Run workflow**

The workflow uses a Windows x64 runner and Python 3.12 only as a build tool. The resulting end-user package includes its own official CPython 3.12 embedded runtime.

A successful run uploads the artifact:

```text
BitcoinMinerStudio-Windows-x64
```

## Release gates

The builder fails instead of publishing an artifact unless all of these pass:

1. Source `purple_dragon_manifest.json` is publisher-signed.
2. Every Purple Dragon protected source file exists.
3. Public runtime contains **no pywebview, pythonnet, clr-loader, PySide6, Qt, or PyInstaller**.
4. Embedded Python can construct the existing Bitcoin Miner Studio backend.
5. Purple Dragon verifies the copied release tree as `TRUSTED` with every protected file valid.
6. The real `BitcoinMinerStudio.exe` starts the embedded backend.
7. Direct Microsoft WebView2 initializes successfully.
8. The injected JavaScript bridge calls the real `get_bootstrap` backend method and receives a response.

That final test exercises the actual release path instead of merely importing a GUI package.

## Runtime requirements

End users do **not** need Python installed.

The Microsoft Edge WebView2 Runtime is required. It is normally already present on current Windows 10/11 installations with Microsoft Edge. If it is missing or damaged, Bitcoin Miner Studio reports that specific condition instead of falling back to another renderer.

## Purple Dragon and Windows trust

The existing Purple Dragon signature still covers the signed Bitcoin Miner Studio application files. The Windows native host and its bridge are release-container components; the host pins the exact bridge SHA-256 before launching it.

Windows Authenticode signing remains a separate trust layer. Until the project has a Windows code-signing certificate, SmartScreen can still display an unknown-publisher warning for `BitcoinMinerStudio.exe` even when the internal Purple Dragon report is `TRUSTED`.
