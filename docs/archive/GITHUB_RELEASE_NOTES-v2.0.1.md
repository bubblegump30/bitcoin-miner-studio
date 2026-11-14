# Bitcoin Miner Studio v2.0.1 — Stable Windows Release

Bitcoin Miner Studio v2.0.1 is the first stable v2 Windows release based on the BMS-ARCH-2 architecture milestone and the v2.0.1 diagnostics/RPC reliability hotfix.

## Highlights

- Major v2 architecture and UX baseline with centralized runtime context, service registry, local event bus, persistent workspace state, explicit WebView API contract, compact sidebar, workspace bar, and command palette.
- Diagnostics false-positive loop fixed so `0 failure(s)` summaries are no longer counted as application failures.
- Background Bitcoin Core polling now preserves the last-known-good snapshot across isolated RPC timeouts.
- Background block-template polling now preserves the last-known-good template across isolated transient timeouts while stale-work safeguards remain active.
- Direct native Windows host using Microsoft Edge WebView2 with an embedded CPython 3.12 backend.
- No PyInstaller, Qt/PySide6, pywebview, pythonnet, or CLR bridge in the public EXE runtime.
- Per-Monitor V2 DPI awareness for sharp rendering on scaled Windows displays.
- Embedded `cryptography` runtime so Release Readiness passes its cryptography dependency check.
- Purple Dragon signed provenance remains TRUSTED with 67/67 protected application files verified.

## Windows package

The recommended download is:

`BitcoinMinerStudio-v2.0.1-Windows-x64.zip`

Extract the ZIP to a new folder and launch:

`BitcoinMinerStudio.exe`

Python does not need to be installed separately. Microsoft Edge WebView2 Runtime is required and is normally present on current Windows 10/11 systems.

## Integrity

The release workflow generates `SHA256SUMS-Windows.txt` alongside the Windows package. Verify the ZIP checksum against that file before distribution.

## Security

Purple Dragon provides signed provenance, protected-file integrity verification, and critical-action gating. It is tamper evidence, not DRM and not a guarantee that software cannot be copied or reverse engineered.

Publisher: **Purple Dragon Foundation ltd**
