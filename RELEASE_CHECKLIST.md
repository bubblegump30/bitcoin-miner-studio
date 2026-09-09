# Bitcoin Miner Studio v2.0.1 — Stable Release Checklist

## Automated gates

- [x] Full Python regression suite after v2.0.1 publisher signing
- [x] JavaScript syntax validation
- [x] WebView DOM contract validation
- [ ] Clean isolated Release Readiness preflight on the final Windows target
- [x] Purple Dragon publisher signature validation — TRUSTED / VALID
- [x] v2.0.1 protected-file hash map refreshed and publisher-signed
- [x] Publisher private key excluded from release
- [x] Self-tests isolated from production user data
- [x] Local support bundle privacy tests
- [x] Theme persistence / fallback tests
- [x] Windows multiprocessing GUI spawn guard
- [x] Pool failover and Local Test Pool integration tests
- [x] Bitcoin Core / block-template RPC integration tests
- [x] Regtest isolation tests
- [x] ASIC false-positive and LAN-isolation tests
- [x] Update & Release Center candidate-signature/hash verification tests
- [x] Update package path-traversal rejection tests
- [x] Trusted staging / rollback metadata tests
- [x] Update Center no-silent-apply / no-candidate-execution contract tests
- [x] BMS-ARCH-2 runtime/service/event/workspace architecture tests
- [x] Explicit WebView API schema 2 allowlist / no implicit bridge exposure
- [x] Workspace persistence / recent-view / compact-sidebar tests
- [x] Command Palette navigation and safe-command contract tests
- [x] Diagnostics schema 3 architecture-health / support-bundle privacy tests
- [x] JavaScript duplicate-function regression check

## v2.0.1 hotfix smoke test

- [x] Diagnostics own `0 failure(s)` summaries excluded from recent-error classification
- [x] Genuine failure-like activity still produces an Application warning
- [x] Background Core timeout preserves last-known-good connected state
- [x] Background template timeout preserves last-known-good template state
- [x] Manual Core/template timeout still reports explicit failure
- [x] Template timeout still contributes to stale-work safety counters

## v2 architecture / UX manual smoke test

- [ ] Confirm workspace bar tracks the active view and recent-workspace chips
- [ ] Toggle compact sidebar and confirm navigation remains usable/readable
- [ ] Press Ctrl+K and verify Command Palette keyboard navigation and Escape close
- [ ] Confirm Command Palette contains no direct start-mining or other accidental critical-action command
- [ ] Open Diagnostics and confirm BMS-ARCH-2 service health renders without exposing secrets
- [ ] Verify Update & Release Center and all v1.x workspaces still open from the v2 shell

## Manual Windows smoke test before public posting

- [ ] Confirm tray icon appears with the official Bitcoin Miner Studio icon
- [ ] Minimize the window and confirm it hides to tray when enabled
- [ ] Enable Close to Tray and confirm the X button hides instead of exiting
- [ ] Use tray Open, Current Status, Hide Window and Exit commands
- [ ] Send a Test Notification and verify Windows displays it
- [ ] Confirm exiting from tray performs clean shutdown and stops background services
- [ ] Confirm there are no mining/ASIC/pool-switch/block-submission tray commands

- [ ] Sidebar/support marks show the dragon emblem only
- [ ] Security header/banner are side-by-side on wide displays
- [ ] Banner does not dominate vertically
- [ ] Branding stacks cleanly below 1250px

- [ ] Confirm sidebar Foundation logo renders (no broken image icon)
- [ ] Confirm Support Purple Dragon logo renders
- [ ] Confirm Purple Dragon Security banner and publisher logo render
- [ ] Confirm all UI image sources stay under `ui/assets/` and use no `../assets/` traversal

- [ ] Create two pool profiles and confirm passwords do not appear in `pool_profiles.json`
- [ ] Activate each profile and confirm endpoint/worker/policy fields update correctly
- [ ] Run Test Profile and confirm Endpoint Diagnostics uses the selected profile without activating it
- [ ] Export profiles and confirm credentials and private notes are absent
- [ ] Verify Manual/Conservative/Balanced/Aggressive policies and primary-recovery timers
- [ ] Start/stop Local Test Pool and confirm the prior real profile/config is restored

- [ ] Confirm Purple Dragon Foundation logo appears in the sidebar without clipping product text
- [ ] Open Purple Dragon Security and confirm the Foundation banner renders full-width and sharp
- [ ] Confirm Foundation logo/header remain readable in Purple, Obsidian, Graphite and Frost themes
- [ ] Confirm the Bitcoin Miner Studio application icon remains the existing Purple Dragon + Bitcoin artwork

- [ ] Confirm Purple Dragon Foundation ltd branding in sidebar and Purple Dragon provenance
- [ ] Confirm Windows EXE CompanyName is `Purple Dragon Foundation ltd`
- [ ] Confirm taskbar identity uses PurpleDragonFoundationLtd.BitcoinMinerStudio
- [ ] Confirm old default coinbase tag migrates while custom tags remain unchanged

- [ ] Open every native dropdown in Obsidian/Purple/Graphite and confirm the popup background is dark with readable text
- [ ] Switch to Frost and confirm native dropdown popups are light with dark readable text
- [ ] Check Bitcoin Core Network/Auth, Profitability Hashrate Unit, Hardware Status, Miner XP Difficulty and Monitoring dropdowns

- [ ] Confirm Start Bitcoin Core passes the pinned data directory and opens the existing synced node
- [ ] Confirm a missing pinned folder is rejected instead of falling back to the default profile
- [ ] Confirm a mismatched already-running Bitcoin Core process triggers Data-Dir Guard
- [ ] Confirm Auto Configure preserves an explicitly selected data directory

- [ ] Open Hardware Compatibility Center and verify fleet cards match ASIC Control evidence
- [ ] Confirm all four built-in family cards render without a JavaScript `.map` error
- [ ] Confirm generic HTTP / open-port candidates remain Not Promoted
- [ ] Filter by Verified Runtime / Supported Family / Limited / Not Promoted
- [ ] Create a Compatibility Report and confirm private IPs/pool data/notes are absent

- [ ] Open Profitability & Power Center and calculate with manual inputs
- [ ] Use Bitcoin Core network data and confirm height/difficulty/subsidy populate
- [ ] Confirm saved calculator inputs persist after restart
- [ ] Confirm BTC price remains manual and no external request occurs

- [ ] Open Mining Assistant, switch all six goals and run Guided Check
- [ ] Confirm Recommended Path populates immediately after each goal selection
- [ ] Confirm Mining Assistant hero status changes with the selected goal
- [ ] Confirm Windows CPU summary shows a friendly processor model when available

- [ ] Launch with run.bat on Windows 11
- [ ] Close/reopen and confirm clean-shutdown signal
- [ ] Run Release Preflight and confirm 100/100 or review explained warnings
- [ ] Switch several Theme Studio presets and restart
- [ ] Start Local Test Pool → Start Mining → Endpoint Diagnostics
- [ ] Run CPU Solo dashboard against Bitcoin Core without submitting a block
- [ ] Start/stop isolated Regtest Laboratory
- [ ] Open Monitoring and confirm historical samples
- [ ] Create and inspect a support bundle
- [ ] Confirm PayPal support button opens externally
- [ ] Verify Purple Dragon build integrity from the shipped folder

## Public-release notes

The source ZIP is portable source, not a code-signed Windows installer.
Windows executable/installer signing requires the publisher to obtain and use a
trusted code-signing certificate on the Windows packaging machine.


## Benchmark Lab 2.0

- [ ] Quick/Standard/Sustained/Stress timed runs start and stop cleanly.
- [ ] Current/average/peak hashrate, stability, score, elapsed and remaining time update.
- [ ] Completed runs persist to local benchmark history.
- [ ] Worker Scaling Test completes or stops without leaving worker processes alive.
- [ ] JSON and CSV exports contain benchmark history only and no credentials.
- [ ] Dashboard Quick Benchmark still uses the same BenchmarkEngine.


## Mining Academy v1.7.0

- [x] 12-lesson catalog loads through the WebView bridge.
- [x] Lesson, quiz, XP/rank and lab progress persists locally.
- [x] Hash Explorer matches known SHA-256 vectors.
- [x] Difficulty-one target is correct.
- [x] Genesis block header serializes to 80 bytes and reproduces the known block hash.
- [x] Merkle-tree single-TXID and duplicate-last behavior validated.
- [x] Educational Nonce Simulator is bounded to 250,000 attempts.
- [x] Academy module imports no network, wallet, ASIC, subprocess or block-submission control surface.
- [x] Contextual Learn This links work from Benchmark Lab and Profitability & Power.
- [x] Purple Dragon protected-file set includes `mining_academy.py`.


## Diagnostics & Support Center v1.8.0

- [x] Quick Scan and Full Diagnostic execute without mining/network-control side effects.
- [x] Runtime, security, storage, configuration, Bitcoin Core, Pool, ASIC, Monitoring and Application categories render.
- [x] Warning/failure issue classification includes explicit next-step remediation.
- [x] System snapshot uses support-safe/redacted paths.
- [x] Support bundle is created locally only.
- [x] Mining/RPC passwords and credential-backend secrets are excluded/redacted.
- [x] Publisher private keys, wallet seeds/mnemonics and analytics SQLite database are excluded.
- [x] Optional sanitized settings and redacted activity evidence can be toggled.
- [x] Diagnostics module contains no mining start/stop, ASIC restart/settings, pool-switch, Bitcoin Core mutation or block-submission command surface.
- [x] Purple Dragon protected-file set includes `diagnostics_center.py`.

## Update & Release Center v1.9.0

- [ ] Inspect a signed older release and confirm ROLLBACK CANDIDATE
- [ ] Inspect the same-version signed release and confirm REINSTALL / VERIFY
- [ ] Inspect a newer signed release and confirm UPDATE READY
- [ ] Paste a deliberately wrong SHA-256 and confirm inspection is blocked before staging
- [ ] Modify a protected file inside a test candidate and confirm Purple Dragon verification blocks staging
- [ ] Confirm Stable channel rejects a signed Preview package
- [ ] Stage a trusted package and confirm the active application folder is unchanged
- [ ] Confirm rollback-plan metadata records current/target version and staged package checksum
- [ ] Export a release descriptor and confirm no password/private-key/credential fields exist
- [ ] Clear staging and confirm only the local update staging area/rollback metadata are removed
