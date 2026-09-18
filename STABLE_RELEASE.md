# Bitcoin Miner Studio v2.0.2 — Stable

This folder is the Bitcoin Miner Studio v2.0.2 Stable source release.

## v2.0.2 public-readiness hotfix

The v2.0.2 release tightens deterministic Windows testing, native WebView2 release detection, Stratum input validation, atomic settings persistence and build supply-chain verification. The native Python bridge joins the Purple Dragon protected surface, bringing the final publisher-signed manifest to 69 protected files, including release-preparation tooling.

## v2.0.1 hotfix

Diagnostics false-positive recursion and transient background Bitcoin Core/getblocktemplate timeout state loss are corrected without weakening stale-work or explicit error-reporting safeguards.

## v2 architecture baseline

The Stable v2 baseline uses **BMS-ARCH-2**: centralized runtime context, explicit WebView API schema 2, local service-health/event infrastructure and persistent workspace state. The UI adds a unified workspace bar, compact navigation, recent views and a safe Command Palette. Diagnostics schema 3 exposes service-health evidence without adding cloud telemetry or automatic control actions.

Compatibility is intentionally preserved for existing mining, Bitcoin Core, pool, ASIC, Benchmark Lab, Mining Academy, Diagnostics and Update & Release Center workflows.

## Start on Windows

Use:

`run.bat`

The launcher selects a working Python interpreter and uses its matching
`pythonw.exe`; it does not rely on a stale global `pyw.exe`.

## Verify before mining

Use:

`verify_build_integrity.bat`

or open **Release Readiness** and choose **Run Release Preflight**.

## Support bundle

Use **Release Readiness → Create Support Bundle**.

Bundles are local only and exclude pool/RPC passwords, seed phrases, private
keys, worker/payout identifiers and the persistent Monitoring database.

## Packaging

`package_portable.bat` produces a clean source-portable ZIP on Windows.

`package_pyinstaller.bat` is an optional executable-build helper. It requires
PyInstaller to be installed on the packaging machine. It does not install
PyInstaller automatically and does not code-sign the executable.

## Official app icon

`assets/BitcoinMinerStudio.ico` is the official Windows application icon.

## Mining Assistant

v1.1.0 adds local advisory readiness checks and guided setup with no automatic mining or hardware control.

## v1.1.0.1

Mining Assistant Recommended Path rendering, goal-aware hero status and friendly Windows CPU naming were polished without changing mining controls.

## Profitability & Power Center

v1.2.0 adds local-only mining/power estimates with optional Bitcoin Core network inputs and no cloud market-price dependency.

## Hardware Compatibility Center

v1.3.0 adds local evidence-backed ASIC compatibility classification and sanitized reporting without cloud lookups or automatic hardware changes.

## v1.3.0.1

Hardware Compatibility family examples are now bridge-safe JSON arrays with defensive UI normalization.

## v1.3.0.2 — Core Data-Dir Guard

Bitcoin Core launches are pinned to an explicit validated data directory; default-profile fallback and ambiguous duplicate Core launches are prevented.

## v1.3.0.3 — Dropdown Theme Reliability

All native WebView2 dropdown controls now use explicit theme-aware popup background/text palettes, including Frost light mode.

## Publisher

Created and published by **Purple Dragon Foundation ltd**.

## v1.3.0.5 — Foundation Visual Identity

Purple Dragon Foundation ltd banner/logo assets are integrated and signed as protected release resources.

## v1.4.0 — Pool Profiles & Smart Failover

Persistent credential-safe pool profiles, policy-aware endpoint failover and scheduled primary recovery are now part of the stable feature set.

## v1.4.0.1

WebView-safe Foundation image loading under `ui/assets/`.

## v1.4.0.2

Foundation visual hierarchy corrected.

## v1.5.0

Native Windows tray and local background health monitoring added with no mining controls exposed from the tray.


## v1.6.0 — Benchmark Lab 2.0

- Dedicated Benchmark Lab workspace using the existing local SHA-256d engine.
- Quick (10s), Standard (30s), Sustained (60s), Stress (120s), and custom timed runs.
- Live current, average and peak hashrate plus total hashes and stability.
- BMS local-comparison score derived from average kH/s and measured stability.
- Persistent local benchmark history with best/latest comparison.
- Automated logical-worker scaling test with scaling-efficiency results.
- Local JSON and CSV benchmark report export.
- Dashboard Quick Benchmark remains backward-compatible with the same benchmark engine.


## v1.8.0 — Diagnostics & Support Center

The Stable source release now includes a read-only Diagnostics & Support Center with Quick/Full scans, category scoring, guided remediation, support-safe system evidence and privacy-sanitized local support bundles. Support packaging is local-only and excludes credential secrets, publisher private keys, wallet seeds/mnemonics and the analytics database.

## v1.7.0 — Mining Academy

Mining Academy adds local structured learning, progress/ranks, quizzes and five deterministic educational labs. It has no wallet, credential, ASIC-control, live-mining, state-changing Bitcoin Core RPC or block-submission API surface.

## v1.9.0 — Update & Release Center

The release workspace now includes local signed-package inspection, optional package SHA-256 validation, Stable/Preview channel policy, trusted staging, rollback-plan metadata, local update history and release descriptor export. Candidate packages are inspected without executing their code. Bitcoin Miner Studio does not silently download or apply updates and does not rewrite the active application folder while running.

For `.7z` package inspection the standard `run.bat` dependency setup installs `py7zr`. ZIP inspection uses Python's standard library.
