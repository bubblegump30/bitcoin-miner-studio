## v2.0.2 — Public Readiness & Reliability Hotfix

- Isolated Bitcoin Core setup self-tests from real Windows process, registry, PATH and user-profile state so tests are deterministic on machines that already run Bitcoin Core.
- Removed two `return`-from-`finally` paths that could suppress exceptions and now fail the CI compile gate on any Python `SyntaxWarning`.
- Made Release Readiness architecture-aware for the native Microsoft Edge WebView2 host used by the public Windows package.
- Hardened Stratum endpoint parsing: only supported Stratum schemes are accepted; embedded credentials, paths/query strings and invalid ports are rejected.
- Tightened Stratum transport cleanup and oversized-response handling.
- Made settings persistence atomic to reduce corruption risk during interrupted writes.
- Excluded VCS/runtime cache metadata from staged release folders and made staged-tree cleanup resilient to Windows read-only file attributes.
- Corrected finalized Windows package file-count/size metadata so it describes the exact shipped tree.
- Pinned the official CPython 3.12.10 embedded runtime by SHA-256 before extraction.
- Added `windows_native_bridge.py` to Purple Dragon protection; the final signed v2.0.2 manifest contains 73 protected files, including the native bridge, native C# host, and Windows release/signing tooling.
- Added a Windows Public Readiness CI gate covering strict Python compilation, JavaScript syntax, deterministic Core/pool/Regtest/ASIC regressions, Stratum URL hardening and release hygiene.
- Preserved the v2.0.1 direct WebView2 + embedded CPython architecture; no PyInstaller, Qt/PySide6, pywebview or pythonnet runtime was reintroduced.

## v2.0.1 — Diagnostics / RPC Reliability Hotfix

- Fixed Diagnostics self-recursion where its own `0 failure(s)` activity summaries were incorrectly counted as recent application failures.
- Added zero-count error/failure filtering while preserving detection of genuine error/failure activity entries.
- Background Bitcoin Core polling now preserves the last-known-good connected snapshot across an isolated RPC timeout instead of temporarily replacing it with Offline.
- Background getblocktemplate polling now preserves the last-known-good template across an isolated RPC timeout; template age continues to advance so stale UI state remains visible.
- Consecutive template timeout failures still count toward Solo Mining / ASIC Solo Bridge stale-work shutdown safeguards.
- Manual Core/template refreshes continue to return explicit timeout errors rather than hiding failures.
- Added regression coverage for the Diagnostics false-positive loop and transient RPC state preservation.
- Purple Dragon protected files re-hashed and publisher-signed for the v2.0.1 hotfix.

## v2.0.0 — Major Architecture / UX Milestone

- Added **BMS-ARCH-2** runtime architecture with centralized product/version/path context.
- Added a thread-safe local event bus with bounded retention; no network telemetry transport.
- Added a service registry for backend lifecycle, health and architecture observability.
- Added persistent workspace state with recent views, pinned views, compact-sidebar preference and command usage.
- Replaced implicit WebView public-method reflection with **explicit API contract schema 2**.
- Added the v2 workspace bar, recent-workspace shortcuts and compact sidebar mode.
- Added a Ctrl/Cmd+K **Command Palette** for navigation and safe utility actions.
- Added dashboard and Diagnostics architecture-health surfaces.
- Diagnostics schema upgraded to **3** with privacy-safe BMS-ARCH-2 support-bundle summaries.
- Removed historical duplicate JavaScript function declarations from the merged UI runtime.
- Preserved Update & Release Center, Diagnostics & Support Center, Mining Academy, Benchmark Lab 2.0 and the existing mining/Core/ASIC/Pool toolchain.
- Purple Dragon protected surface expanded for the new v2 architecture modules.

## v1.9.0 — Update & Release Center

- Added a dedicated **Update & Release Center** inside the existing Stable release workspace.
- Added local inspection for complete signed Bitcoin Miner Studio `.7z`, `.zip`, and extracted release folders without executing candidate code.
- Added optional published SHA-256 verification before cryptographic release inspection.
- Added Purple Dragon publisher-signature verification and full protected-file hash verification for candidate releases.
- Added semantic version comparison with UPDATE READY, REINSTALL / VERIFY, and ROLLBACK CANDIDATE decisions.
- Added Stable / Preview channel policy. Stable blocks non-Stable candidates; Preview permits signed Preview candidates.
- Added trusted local staging under the Bitcoin Miner Studio app-data directory. Staging never overwrites the running application folder.
- Added rollback-plan metadata recording the current build, target release, staged checksum, and explicit offline-apply policy.
- Added local update history and explicit staging cleanup.
- Added support-safe public release descriptor export with build ID, release seal, publisher key ID, protected-file digest, and trust state.
- Added native package/folder pickers and update-folder access.
- Added `py7zr` as the local `.7z` inspection dependency.
- Added `update_release_center.py` to Purple Dragon protected-file verification.
- Preserved v1.8.0 Diagnostics & Support Center, v1.7.0 Mining Academy, v1.6.0 Benchmark Lab 2.0, and the existing mining/Core/ASIC toolchain.
- No background download service, silent self-update, candidate execution, or automatic in-place patching was introduced.

## v1.8.0 — Diagnostics & Support Center

- Added a dedicated **Diagnostics & Support Center** workspace.
- Added **Quick Scan** and **Full Diagnostic** modes using read-only operational evidence.
- Added health checks for Python/WebView/crypto runtime, application storage/free space, Purple Dragon trust, configuration validation, Bitcoin Core state, pool/miner state, ASIC fleet/solo bridge, local monitoring and recent application-session signals.
- Added category health summaries, 0–100 diagnostics scoring and HEALTHY / ATTENTION / DEGRADED / CRITICAL classification.
- Added an Issues & Next Steps panel with explicit remediation guidance for warnings and failures.
- Added a support-safe system snapshot with OS, Python, architecture, CPU and redacted application-data path.
- Added **local diagnostics support bundles** containing diagnostics evidence, security summary, optional sanitized settings, optional redacted activity logs, release-readiness evidence, pool diagnostics and startup logs when present.
- Support bundles never include mining/RPC passwords, credential-backend secrets, publisher private keys, wallet seeds/mnemonics or the analytics SQLite database, and are never uploaded automatically.
- Added local support-folder access and Copy Diagnostics Report actions.
- Diagnostics are deliberately non-destructive: no mining start/stop, ASIC restart/settings, pool switching, Bitcoin Core mutation or block submission APIs are used.
- Added `diagnostics_center.py` to Release Readiness and Purple Dragon protected-file verification.
- Preserved all v1.7.0 Mining Academy and v1.6.0 Benchmark Lab 2.0 functionality.

## v1.7.0 — Mining Academy

- Added **Mining Academy** with 12 structured lessons covering mining fundamentals, SHA-256d, block headers, difficulty/target, Merkle trees, coinbase transactions, Bitcoin Core RPC, solo mining, Stratum, ASIC efficiency, economics and security.
- Added persistent local lesson status, quiz results, Academy XP and rank progression.
- Added interactive Hash Explorer, Difficulty & Target Visualizer, 80-byte Block Header Lab, Merkle Tree Lab and educational Nonce Mining Simulator.
- Added a known-valid Bitcoin genesis-header exercise for endianness and Proof-of-Work target comparison.
- Added contextual **Learn This** links from Benchmark Lab 2.0 and Profitability & Power Center.
- Academy endpoints are deliberately isolated from wallets, pool credentials, ASIC control, live mining workers, Bitcoin Core state-changing RPC and block submission.
- Added `mining_academy.py` to Release Readiness and Purple Dragon protected-file verification.
- Preserved all v1.6.0 Benchmark Lab 2.0 functionality, history and exports.
- Purple Dragon release manifest re-signed for the v1.7.0 protected-file set.

## v1.6.0 — Benchmark Lab 2.0

- Added a dedicated **Benchmark Lab 2.0** workspace without replacing or duplicating the existing SHA-256d benchmark engine.
- Added Quick (10s), Standard (30s), Sustained (60s), Stress (120s), and custom-duration local benchmark runs.
- Added live current, average and peak SHA-256d hashrate, total hashes, elapsed/remaining time and stability telemetry.
- Added a transparent local **BMS Score**: average kH/s multiplied by measured stability, intended for comparing this PC with its own prior runs.
- Added persistent local benchmark history under the Bitcoin Miner Studio data directory.
- Added best/latest score comparison and detailed history table.
- Added automated Worker Scaling Test across recommended logical-worker counts with scaling-efficiency measurement.
- Added credential-free JSON and CSV Benchmark Lab exports.
- Dashboard Quick Benchmark remains backward-compatible and uses the same BenchmarkEngine/Benchmark Lab controller.
- Benchmarking remains local-only: no pool, wallet, Bitcoin Core or ASIC connection is required.
- Added Benchmark Lab configuration defaults, release metadata, packaging versioning and regression coverage.
- Purple Dragon publisher signing remains external; re-sign v1.6.0 with the private publisher key before treating the modified source as a trusted release build.

## v1.5.0 — Windows Tray & Background Monitoring

- Added a dependency-free native Windows system tray using the existing Bitcoin Miner Studio ICO.
- Added Minimize to Tray and optional Close to Tray behavior.
- Existing Pool/Core/ASIC/Security background monitors continue while the main WebView window is hidden.
- Added privacy-safe tray status and local Windows health notifications for pool failover, Core disconnect/recovery, ASIC availability drops and Purple Dragon health warnings.
- Tray menu commands are intentionally limited to Open, Current Status, Hide Window and Exit.
- The tray cannot start mining, switch pools, control ASICs, reveal credentials or submit blocks.
- Added a dedicated Tray & Background page with settings, live status and a notification test.
- Added release validation for tray poll ranges and protected `windows_tray.py`.

## v1.4.0.2 — Foundation Branding Layout Hotfix

- Small icon surfaces now show only the Purple Dragon emblem instead of compressing the full company lockup.
- Purple Dragon Security now uses a professional split publisher/header + banner layout on wide displays.
- The Foundation banner is constrained to a 190px supporting visual rather than a page-dominating hero.
- Responsive layout stacks cleanly below 1250px.
- Same-origin asset loading, Pool Profiles & Smart Failover, themes, and the existing app icon are preserved.

# Bitcoin Miner Studio — Changelog

## v1.4.0.1 — Foundation Asset Loading Hotfix

- Fixed broken Purple Dragon Foundation logo/banner images in WebView2.
- Root cause: `ui/index.html` referenced visual assets through `../assets/...`; WebView2 local-file loading did not reliably allow the parent-directory resource path.
- Added WebView-safe copies under `ui/assets/` and changed every UI image/favicon reference to same-origin child paths.
- Added a regression check that forbids `../assets/` UI image references.
- The actual UI-served copies are now included in Purple Dragon protected-file verification.
- Existing root `assets/` copies remain for native application icon/packaging use.
- Pool Profiles & Smart Failover behavior is unchanged.

## v1.4.0 — Pool Profiles & Smart Failover

- Added persistent local Pool Profiles with a dedicated profile editor and saved-profile table.
- Profiles store primary + up to 3 backup Stratum endpoints, worker, pool fee, failover policy, watchdog, mining-process and difficulty preferences.
- Added secure per-profile password storage through the existing credential backend; passwords are never written to `pool_profiles.json`.
- Added one-click Activate, Test Profile, Delete and sanitized Export actions.
- Sanitized exports exclude credentials and free-form profile notes.
- Added four failover policies: Manual Only, Conservative, Balanced and Aggressive.
- Conservative requires two consecutive endpoint failures before switching; Balanced/Aggressive switch after one confirmed failure.
- Added scheduled primary recovery after a healthy backup interval, configurable per profile.
- Added runtime telemetry for failover policy, endpoint uptime, primary-recovery attempts and last failover reason.
- Local Test Pool remains isolated: it forces Manual failover and restores the previous real-pool/profile configuration afterward.
- Activating a profile also synchronizes its configured pool-fee assumption into Profitability & Power Center.
- No ASIC pool changes occur automatically; ASIC controls remain separately authorized and private-LAN gated.

## v1.3.0.5 — Foundation Visual Branding Integration

- Integrated the supplied **Purple Dragon Foundation ltd** wide software-development banner.
- Integrated the supplied **Purple Dragon Foundation ltd** logo artwork.
- Added the Foundation mark to the Bitcoin Miner Studio sidebar while preserving the Bitcoin Miner Studio product identity.
- Added the Foundation mark to the project-support / PayPal surface.
- Added a prominent Foundation banner and publisher identity header to the Purple Dragon Security Center.
- Both artwork files are packaged as protected release assets and included in Purple Dragon signed integrity verification.
- The existing Purple Dragon + Bitcoin artwork remains the Windows/application icon.
- No mining, ASIC, Pool, Core, wallet, profitability or block-submission behavior changed.

## v1.3.0.4 — Purple Dragon Foundation ltd Branding Migration

- Publisher / creator identity is now **Purple Dragon Foundation ltd** throughout Bitcoin Miner Studio.
- Windows AppUserModelID is `PurpleDragonFoundationLtd.BitcoinMinerStudio`.
- Purple Dragon signed provenance now binds and verifies the publisher name.
- Added Foundation branding to the WebView sidebar, Security provenance and Tk fallback.
- Added Windows executable CompanyName / copyright / product-version metadata.
- Mainnet, ASIC Solo and Regtest default coinbase tags now use the Foundation brand.
- Exact legacy default coinbase branding migrates automatically; custom user tags remain untouched.
- Project-support wording identifies **Purple Dragon Foundation ltd**.
- Product name remains **Bitcoin Miner Studio**.

## v1.3.0.3 — Global Dropdown Theme Hotfix

- Fixed opened WebView2/Windows dropdown menus using a white/native-light background while Miner Studio supplied light text.
- Applied explicit `color-scheme: dark` directly to every native `select`, `option`, and `optgroup` in dark themes.
- Added opaque theme-aware option backgrounds instead of relying on translucent control backgrounds.
- Frost retains an explicit light native dropdown palette with dark text.
- Added selected/disabled option states and consistent focus styling.
- The fix is global and covers Bitcoin Core, Profitability & Power, Hardware Compatibility, Miner XP, Monitoring, and future native dropdowns.
- No mining, Core, Pool, ASIC, wallet, security, or submission behavior changed.

## v1.3.0.2 — Bitcoin Core Data-Dir Reliability Hotfix

- Bitcoin Core launches from Miner Studio now require and always pass an explicit `-datadir=...`.
- Miner Studio refuses to fall back to Bitcoin Core's default Windows profile directory when a configured data folder is missing.
- Auto Configure no longer silently replaces an explicitly pinned Bitcoin data directory with a different detected/default profile.
- Added a Data-Dir Guard that detects explicit running-process mismatches.
- Bitcoin-Qt processes without `-datadir` are checked against the saved Windows data-directory setting when available.
- If a running Bitcoin Core process cannot be tied to the configured data folder, Miner Studio blocks a duplicate launch and instructs the user to close/relaunch it safely.
- When the correct node is already running, Miner Studio skips launching a duplicate process.
- Added visible Data-Dir Guard status to the Bitcoin Core Setup Assistant.
- Mining, Pool, ASIC, Regtest, block submission and wallet behavior are unchanged.

## v1.3.0.1 — Hardware Compatibility Serialization Hotfix

- Fixed `Hardware Compatibility: (f.examples || []).map is not a function`.
- Family `examples` are now emitted from Python as JSON-safe lists.
- Fixed the generic cgminer family entry, which had accidentally been authored as a plain string.
- The JavaScript renderer now uses `Array.isArray()` and safely normalizes unexpected bridge values before rendering.
- Added a regression test covering the exact pywebview serialization failure.
- No ASIC discovery/control behavior changed.

## v1.3.0 — Hardware Compatibility Center

- Added a dedicated Hardware Compatibility Center.
- Added local recognition families for Bitmain/Antminer, MicroBT/WhatsMiner, Canaan/Avalon and generic cgminer-compatible ASIC APIs.
- Added evidence-backed states: Verified Runtime, Supported Family, Generic/Limited and Not Promoted.
- Added per-device capability mapping for monitoring, Web UI, pool control, restart and ASIC Solo Bridge eligibility.
- Preserved strict positive-evidence discovery: generic HTTP/HTTPS or open TCP 4028 alone never promotes a device as an ASIC.
- Added searchable/filterable current-fleet compatibility cards.
- Added a built-in family registry and capability-policy documentation.
- Added a privacy-sanitized local Compatibility Report for GitHub/support use; private IPs, pool URLs/workers, credentials and device notes are excluded.
- The Center is read-only: it performs no LAN scan, pool change, ASIC restart or firmware modification.

## v1.2.0 — Profitability & Power Center

- Added a dedicated local Profitability & Power Center.
- Estimate expected BTC/day from hashrate, network difficulty and block reward.
- Estimate electricity cost/day/month/year from watts and $/kWh.
- Estimate revenue after pool fee, net/day/month/year and break-even electricity price.
- Calculate efficiency in W/TH and approximate miner share of network hashrate.
- Added mean time to solo block, 50% probability time and 1h/24h/7d/30d/1y solo probability.
- Bitcoin Core can supply local height/difficulty/subsidy data.
- BTC price and average transaction-fee inputs remain manual; no cloud price service was added.
- All outputs are estimates and do not guarantee profitability.

## v1.1.0.1 — Mining Assistant Polish Hotfix

- Fixed Recommended Path staying on its placeholder after selecting a goal.
- Root cause: the UI renderer called an undefined `esc()` helper while generating path rows; it now uses the existing `escapeHtml()` helper.
- Mining Assistant hero is now goal-aware: e.g. `POOL MINING · SETUP NEEDED`, `SOLO MINING · PREPARED`, `BITCOIN CORE · SYNCED`.
- Windows CPU summary now prefers the friendly `ProcessorNameString` registry value instead of the raw `AMD64 Family ...` identifier.
- Mining engines, Pool, ASIC, Core and submission behavior are unchanged.

## v1.1.0 — Mining Assistant

- Added the beginner-friendly **Mining Assistant** page.
- Added “Can I Mine?” local readiness scoring.
- Added six goals: Learn & Test, Test This PC, Pool Mining, Connect an ASIC, Bitcoin Core and Solo Mining.
- Added readiness cards for CPU, pool, Core, ASIC, solo prerequisites and Purple Dragon security.
- Added goal-specific recommended paths that route to existing Miner Studio controls.
- Added one-time onboarding and persistent goal/review preferences.
- Mining Assistant is advisory only and never starts mining, scans the LAN, changes pools, controls ASICs, changes Core or submits blocks automatically.

## v1.0.1 — Official App Icon

- Approved Purple Dragon + Bitcoin artwork is now the official application icon.
- Added 16, 24, 32, 48, 64, 128 and 256 px Windows ICO representations.
- Source/pythonw launches apply it to the native pywebview window.
- Windows taskbar grouping receives a stable Bitcoin Miner Studio AppUserModelID.
- Tk fallback uses the same artwork.
- PyInstaller embeds the same ICO in the packaged executable.
- Icon assets are part of Purple Dragon integrity and Release Readiness.

## v1.0.0 — Stable Release

Bitcoin Miner Studio reaches its first Stable release after the v0.9.x
Release Candidate hardening cycle.

### Stable feature set

- SHA-256d CPU benchmark and Pool/Stratum mining;
- Pool & Stratum PowerTools 2.0 with endpoint diagnostics, failover and share analytics;
- Local Test Pool with ephemeral lifecycle and multi-client diagnostics;
- Bitcoin Core detection, RPC diagnostics and block-template engine;
- guarded coinbase construction, solo candidate assembly and submitblock workflow;
- isolated Regtest Mining Laboratory;
- LAN-only ASIC discovery, fleet monitoring and ASIC Solo Bridge;
- Monitoring & Analytics with local SQLite history and CSV/JSON export;
- Purple Dragon signed provenance and tamper gate;
- Miner XP / Hash Hunt cosmetic mini-game;
- Theme Studio with 10 persistent themes;
- privacy-sanitized local support bundles;
- Release Readiness preflight;
- optional PayPal project-support link.

### Stable guarantees

- no cloud telemetry;
- no automatic support-bundle upload;
- no silent auto-update;
- no publisher private key in the distributed release;
- pool/RPC passwords remain outside settings.json;
- Local Test Pool remains loopback-only;
- ASIC Solo Bridge remains private-LAN-only;
- automatic block submission remains disabled;
- Hash Hunt remains isolated from real mining APIs.

## v0.9.0.4

Added the theme-aware PayPal project-support card with a fixed external URL.

## v0.9.0.3

Fixed Theme Studio overlay stacking above glass Dashboard panels.

## v0.9.0.2

Added Theme Studio with Purple, Graphite, Obsidian, Frost, Sapphire, Crimson,
Emerald, Cyan, Amber and Rose presets.

## v0.9.0.1

Cleaned stale Local Test Pool metadata from Release Candidate scoring and added
an explicit Configuration PASS gate.

## v0.9.0

Introduced Release Candidate readiness, support bundles, configuration
validation, crash-session signal and release-engineering hardening.

## v0.8.0

Added persistent Monitoring & Analytics.

## v0.7.x

Pool & Stratum PowerTools 2.0, Windows multiprocessing fixes and Local Test Pool
reliability hardening.

## v0.6.x

Purple Dragon Security and Miner XP / Hash Hunt.

## v0.5.x

ASIC Solo Mining Integration and strict positive-evidence ASIC discovery.

## v0.4.x

Bitcoin Core, coinbase/payout, solo mining, block assembly and Regtest Lab.

## v0.1–v0.3

Initial benchmark, Stratum pool mining, ASIC/fleet management and holographic UI.
