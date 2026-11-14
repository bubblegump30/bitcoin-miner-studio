# Bitcoin Miner Studio v2.0.0 — Major Architecture / UX Upgrade

Upgrade from v1.9.0 by replacing the application source folder with the **complete signed v2.0.0 release**. Preserve the user-data directory under `.bitcoin-miner-studio`; do not merge individual protected source files between signed versions.

## What changes in v2

- BMS-ARCH-2 centralizes runtime identity and application-data paths.
- Service lifecycle/health is represented through a local service registry.
- A bounded local event bus provides in-process operational events with no cloud transport.
- Workspace state persists the last/recent views, pinned views, compact sidebar preference and command usage.
- WebView API exposure is controlled by an explicit signed API schema v2 allowlist.
- The UI adds a workspace bar, compact sidebar, recent-workspace shortcuts and Ctrl/Cmd+K Command Palette.
- Diagnostics schema 3 reports architecture/service health and writes only privacy-safe architecture data to support bundles.

## Compatibility

The upgrade preserves existing configuration, mining controls, Bitcoin Core integration, pool profiles/failover, ASIC management, Monitoring, Benchmark Lab 2.0, Mining Academy, Diagnostics & Support Center and Update & Release Center behavior. No silent self-update, cloud telemetry or automatic support upload is introduced.

## Trust and rollback

Use the complete Purple Dragon signed v2.0.0 folder. Editing a protected file after signing invalidates the build until the publisher intentionally regenerates and re-signs the manifest. Keep the complete trusted v1.9.0 folder/archive if a rollback is required; do not mix protected v1.9 and v2 files.

## First launch checks

1. Run `verify_build_integrity.bat` and confirm `TRUSTED`, `VALID` and every protected file verified.
2. Launch with `run.bat`.
3. Confirm the workspace bar and Command Palette operate normally.
4. Open Diagnostics & Support Center and run a Quick Scan.
5. Open Update & Release Center and confirm the current release is v2.0.0 Stable.
