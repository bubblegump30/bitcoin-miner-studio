# Bitcoin Miner Studio v2.0.2 — Public Readiness & Reliability Hotfix

Bitcoin Miner Studio v2.0.2 hardens the v2.0.1 stable Windows architecture for broader distribution without reintroducing the frozen/Qt/CLR runtime stacks retired in v2.0.1.

## Highlights

- deterministic Bitcoin Core setup/self-test isolation on real Windows machines;
- strict `SyntaxWarning` CI gate and cleanup of exception-suppressing `finally` returns;
- direct Microsoft Edge WebView2-aware Release Readiness checks;
- hardened Stratum endpoint parsing and response-buffer handling;
- atomic settings persistence;
- corrected post-finalization package metadata;
- SHA-256 verification of the official embedded CPython 3.12.10 archive before extraction;
- Purple Dragon protected surface expanded to 68 files, including `windows_native_bridge.py`;
- dedicated Windows Public Readiness Gate covering Core, pool/failover, Regtest, ASIC Solo, JavaScript, Python and repository hygiene.

## Windows architecture

- native C# WinForms host;
- Microsoft Edge WebView2 renderer;
- embedded CPython 3.12.10 backend;
- private stdin/stdout JSON bridge;
- no separate Python install required;
- no PyInstaller, Qt/PySide6, pywebview, pythonnet or CLR bridge in the public EXE runtime.

Microsoft Edge WebView2 Runtime is required and is normally present on current Windows 10/11 systems.

## Verification

Use the published `SHA256SUMS-Windows.txt` and confirm the in-app Purple Dragon Security state is `TRUSTED` with a valid publisher signature and all protected files verified before enabling critical controls. Purple Dragon is tamper-evident provenance, not DRM and not a guarantee against copying or reverse engineering.

The v2.0.2 Windows package does **not** claim a Microsoft Authenticode signature. Until an Authenticode certificate is added, Windows SmartScreen/reputation prompts may occur on newly downloaded builds. Verify the published SHA-256 checksum and Purple Dragon provenance before running the package.

See `PRIVACY.md` and `MINING_SAFETY.md` before public distribution or first-time mining use.
