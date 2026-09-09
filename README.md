# Bitcoin Miner Studio v2.0.1 — Stable

**Publisher:** Purple Dragon Foundation ltd  
**Created by:** Purple Dragon Foundation ltd


## v2.0.1 — Diagnostics / RPC Reliability Hotfix

This hotfix corrects two issues found from a real v2.0.0 Diagnostics support bundle. Diagnostics no longer treats its own `0 failure(s)` summary lines as recent application errors, eliminating the false 98/100 ATTENTION loop. Background Bitcoin Core and getblocktemplate polling now preserves the most recent verified state across an isolated RPC timeout, while explicit/manual refresh still reports the timeout and mining stale-work safety still counts consecutive template failures.


## v2.0.0 — Major Architecture / UX Milestone

Bitcoin Miner Studio v2 introduces **BMS-ARCH-2**, a cleaner application foundation that preserves the existing mining, Bitcoin Core, ASIC, pool, benchmarking, education, diagnostics and update capabilities while making the desktop app easier to extend and operate. Runtime paths and identity now come from one `RuntimeContext`; service health is tracked through a local `ServiceRegistry`; a bounded local `LocalEventBus` provides in-process operational events; and persistent workspace state is owned by `WorkspaceManager`.

The WebView boundary is now an **explicit API schema v2 allowlist** rather than implicit exposure of every public backend method. The UX gains a unified workspace bar, recent-workspace navigation, compact sidebar mode, architecture-health surfaces and a Ctrl/Cmd+K **Command Palette** for safe navigation and utility commands. Diagnostics schema v3 reports BMS-ARCH-2 service health and includes a privacy-safe architecture summary in local support bundles.

The v2 architecture remains local-first. It does not introduce cloud telemetry, silent self-update, automatic support upload, automatic mining actions, or candidate-code execution.

## v1.9.0 — Update & Release Center

Bitcoin Miner Studio now includes a local-first **Update & Release Center**. It can inspect complete signed `.7z` / `.zip` packages or extracted release folders, optionally verify a published SHA-256, validate the Purple Dragon publisher signature and every protected-file hash, compare release versions, enforce Stable / Preview channel policy, stage only trusted releases, write rollback-plan metadata, export public release descriptors, and retain a short local staging history. It never downloads updates in the background, executes candidate code, or silently replaces the running application.

## v1.8.0 — Diagnostics & Support Center

Bitcoin Miner Studio now includes a dedicated **Diagnostics & Support Center** with Quick and Full read-only health scans across runtime, security, storage, configuration, Bitcoin Core, pool state, ASIC state, monitoring and application-session evidence. The center classifies warnings/failures, provides guided next steps, and creates local privacy-sanitized support bundles that exclude credential secrets, publisher private keys, wallet seeds/mnemonics and the analytics database. No support bundle is uploaded automatically.

## v1.7.0 — Mining Academy

Bitcoin Miner Studio now includes a local **Mining Academy** with 12 structured lessons, persistent progress/XP/ranks and quizzes, plus five deterministic educational labs: Hash Explorer, Difficulty & Target Visualizer, 80-byte Block Header Lab, Merkle Tree Lab, and Nonce Mining Simulator. Academy functionality is deliberately isolated from wallets, credentials, ASIC controls, live mining workers, state-changing Bitcoin Core RPC and block submission.

## v1.6.0 — Benchmark Lab 2.0

Bitcoin Miner Studio now includes a dedicated local Benchmark Lab built on the existing SHA-256d CPU engine. It adds timed presets and custom runs, current/average/peak hashrate telemetry, stability analysis, a local BMS comparison score, persistent benchmark history, JSON/CSV exports, and an automated worker-scaling test. Benchmarking remains local-only and does not connect to a pool, wallet, Bitcoin Core, or ASIC.


## v0.4.0 — Bitcoin Core Integration

Bitcoin Miner Studio now includes a persistent Bitcoin Core JSON-RPC manager and a live holographic node dashboard.

### RPCs used

- `getblockchaininfo` — chain, height, headers, sync progress, IBD/pruning state
- `getmininginfo` — difficulty, network hash rate, mempool transaction count
- `getnetworkinfo` — node version, protocol version, network-active state, peers, relay fee, warnings

### Node dashboard

The Bitcoin Core page now shows:

- online / syncing / offline status
- chain
- block height
- sync percentage
- peer count
- difficulty
- estimated network hash rate
- mempool transaction count
- node/subversion
- blocks vs headers
- initial block download state
- pruned state
- protocol version
- relay fee
- best block hash
- warnings
- last check time and total RPC latency

### Automatic health checks

Bitcoin Miner Studio can poll Bitcoin Core automatically. The default health interval is 10 seconds and can be configured between 5 and 300 seconds from the Bitcoin Core page.

State-transition logging avoids filling the event log with identical repeated connection errors.

### RPC diagnostics

Connection errors are categorized for clearer troubleshooting:

- configuration error
- authentication / HTTP 401
- connection refused
- timeout
- HTTP transport error
- JSON-RPC error with RPC code
- invalid JSON/response

Passwords continue to use the existing credential backend and are not written to `settings.json`.

### v0.4.0 self-test

The self-test suite now starts a local mock Bitcoin Core JSON-RPC server and validates all three integration RPCs plus authentication-error classification.

v0.3.4 turns the ASIC workspace into a more complete operational fleet console.

## Persistent known-device list

Devices discovered or manually added to ASIC Control Center are now remembered.

On the next application start, Bitcoin Miner Studio attempts to refresh those
known private-LAN devices automatically.

Removing a device from the ASIC page also removes it from the persistent known
device list.

## Sortable fleet table

Click a fleet table column heading to sort.

Supported columns include:
- IP
- alias
- group
- model
- verification
- status
- health
- hashrate
- temperature
- fan
- availability
- offline duration
- pool

Click the same heading again to reverse sort order.

## Device notes

Each known device can now store a short local note.

Examples:
- Rack 2 top shelf
- PSU replaced 2026-08-14
- Needs fan inspection

Notes are stored locally in the normal Bitcoin Miner Studio settings file.

## Fleet configuration import/export

A fleet configuration JSON can now be exported and imported.

The configuration includes:
- known private-LAN device IPs
- aliases
- groups
- notes
- discovery subnet
- auto-refresh interval
- temperature alert threshold
- hashrate-drop threshold

Imported IPs are still validated as private/local addresses.

This configuration export does not contain pool or ASIC passwords.

## Alert / event timeline

Fleet history now also stores operational events such as:
- device offline
- device recovered
- status changes
- alert acknowledgement

The ASIC page displays a recent event timeline with:
- time
- IP
- event type
- severity
- message

The timeline is persisted with fleet monitoring history.

## Richer device trends

The selected miner now has:
- hashrate trend
- combined temperature/fan trend

The graphs are lightweight in-app trend visualizations based on the persistent
rolling telemetry samples.

## Health explanation

The selected-device panel now explains the inputs behind the current health
score, including:
- status
- temperature
- hashrate vs learned baseline
- hardware errors

The health score remains operational guidance, not a predictive failure model.

## Existing safety behavior

Unchanged:
- private/local IPv4 only
- maximum /24 discovery range
- explicit ownership/administration confirmation
- no public-IP scanning
- no password guessing
- no credential harvesting
- restart and pool switching require explicit confirmation

## Self-test

Run:

    selftest.bat

v0.3.4 validates:
- Bitcoin utility vectors
- local Stratum mining
- retained session reset
- mining.suggest_difficulty
- verified mock ASIC telemetry
- false-positive classification guard
- persistent fleet history
- health scoring/explanation
- offline tracking
- fleet event persistence
- alert acknowledgement
- JSON/CSV export

## Next

### v0.4.0 — Bitcoin Core / Solo Mining
- getblocktemplate
- coinbase payout configuration
- candidate block construction
- network target validation
- submitblock
- regtest integration suite


## v0.3.5 — Readability+

This release focuses on making the UI easier to read without changing the workflow.

### UI readability improvements
- larger base application font
- slightly increased Tk scaling
- larger titles, subtitles, and metric values
- larger entry and spinbox text
- larger table text and headings
- taller Treeview rows
- larger selected-device details text
- larger hashrate / temp / fan panel labels
- slightly taller 3D buttons
- slightly larger console/log text blocks

The goal is to keep the same layout and purple visual identity while reducing eye strain.


## v0.3.6 — Control Size+

This follow-up readability pass specifically enlarges the smaller ASIC Control
widgets that were still difficult to read.

### Enlarged controls
- LAN RANGE input
- SEARCH input
- GROUP FILTER dropdown
- Auto refresh interval spinbox
- TEMP ALERT °C spinbox
- HASH DROP % spinbox
- spacing around the ASIC control header widgets

This keeps the same layout and theme, but makes the top control strip much easier
to read and interact with.


## v0.3.7 — UI Scale Settings

Bitcoin Miner Studio now includes a persistent UI scale selector in the lower
left sidebar.

Available modes:

- Normal — 1.00×
- Large — 1.15×
- Extra Large — 1.35×

The current v0.3.6-sized interface corresponds to **Large**.

### Applying a new scale

Choose a size and press:

    Apply Scale

Bitcoin Miner Studio saves the setting and restarts itself so every Tk and ttk
widget is recreated at the new scale. This is more reliable than attempting to
resize an already-created Tk widget tree.

If mining, benchmarking, or the local test pool is active, the app asks for
confirmation because applying the scale stops that active session before the
restart.

The selected scale is stored in the normal application settings and is reused
the next time Bitcoin Miner Studio starts.


## v0.3.8 — UI Contrast+

This quick polish patch improves combobox readability, especially the **UI SCALE**
selector in the sidebar.

### Fixed
- darker visible combobox text
- readable readonly-state text color
- readable selected text color
- light field background for contrast
- improved dropdown arrow contrast

This specifically addresses the sidebar selector where the wording was too faint
to read against the field background.


## v0.3.9 — UI Scale Polish

This small follow-up pass finishes the new UI scale area.

### Improved
- bigger **UI SCALE** label
- more visible label color
- slightly roomier scale dropdown
- darker, easier-to-read dropdown popup list text
- clearer popup selection highlight
- bolder **Apply Scale** button text

The goal is to make the UI scale selector feel as readable and polished as the
rest of the app.


## v0.3.10 — Visual Match+

This visual refresh pushes Bitcoin Miner Studio much closer to the provided
reference style.

### UI refresh highlights
- deeper blue/purple neon color palette
- stronger panel outlines and glow treatment
- refreshed sidebar styling
- improved top header badge
- more polished dashboard operational strip
- redesigned metric cards with icon badges
- stronger active navigation highlight
- improved modern dashboard feel while keeping the existing workflows intact

This is still the same Tkinter application underneath, but the presentation now
tracks the reference dashboard much more closely.


## v0.3.11 — Reference Match

This release is a component-level visual rebuild rather than a palette tweak.

### New custom UI layer

Bitcoin Miner Studio now includes pure-Tk canvas widgets for:
- rounded neon panels
- rounded/glowing action buttons
- rounded navigation items
- icon-driven metric cards

No additional Python packages are required.

### Dashboard reference match

The Dashboard has been rebuilt to follow the supplied reference more closely:
- rounded status panel
- icon badge metric cards
- rounded purple/blue borders
- soft neon edge glow
- rounded Pool Mining / Local Benchmark panels
- rounded Recent Shares panel
- closer card spacing and proportions
- reference-style cyan/purple action treatment

### Sidebar reference match

The sidebar now uses:
- rounded active navigation
- rounded UI Scale panel
- rounded SHA-256d Engine panel
- closer icon/label spacing
- stronger active-page glow

The mining, Stratum, ASIC, Bitcoin Core, credential, monitoring, and fleet logic
remains the same; v0.3.11 focuses on presentation.


## v0.3.12 — Visual Match+

This build tightens the shell, sidebar, dashboard spacing, metric cards, and control panels to more closely mirror the provided neon reference screenshot.


## v0.3.13 — Purple Theme Tokens

Applied the exact user-supplied palette:
- Background `#07060B`
- Shell `#0E0A15`
- Card `#171020`
- Raised Surface `#21162E`
- Purple 900 `#35115D`
- Purple 700 `#6425A8`
- Purple 500 `#9654FF`
- Purple 400 `#B678FF`
- Purple 300 `#D3A5FF`
- Text Primary `#FAF7FF`
- Text Secondary `#CFC3DA`
- Text Muted `#9587A3`


## v0.3.14 — Shadow Depth+

Applied the requested 3D button shadow recipe:

```css
box-shadow:
  0 8px 0 #491B76,
  0 14px 24px rgba(117, 50, 190, .30),
  inset 0 1px 0 rgba(255,255,255,.30);
```

Tkinter canvas does not provide CSS blur/alpha shadows, so the 24px soft shadow is reproduced using multiple pre-blended rounded layers. The 8px hard purple depth and 30% white inset highlight are represented directly. Buttons also compress the visible depth slightly while pressed.


## v0.3.15 — PowerTools Holographic UI

This release replaces the primary desktop presentation layer with the user-supplied
**PowerTools — Purple Holographic UI** package.

### Actual source design used
The supplied `index.html`, `styles.css`, and `script.js` were used as the visual
foundation rather than approximating the design with native Tk rectangles.

The desktop front end now uses **pywebview** to render the real HTML/CSS design while
Python continues to run the mining, Stratum, ASIC, Bitcoin Core, credential, local
pool, and fleet-monitoring backends.

### Visual system carried over
- aurora background lighting
- grid/noise overlay
- glassmorphism shell and panels
- 260px holographic navigation sidebar
- responsive top search/action bar
- hero/status area
- animated holographic mining orb
- stat cards
- performance gauge and meters
- high-DPI canvas hashrate graphs
- 3D quick-action buttons
- responsive layouts

### Exact 3D shadow
Buttons use the requested depth recipe:

    box-shadow:
      0 8px 0 #491B76,
      0 14px 24px rgba(117, 50, 190, .30),
      inset 0 1px 0 rgba(255,255,255,.30);

### Theme tokens
The holographic UI uses the supplied Bitcoin Miner Studio palette:

    Background       #07060B
    Shell            #0E0A15
    Card             #171020
    Raised Surface   #21162E
    Purple 900       #35115D
    Purple 700       #6425A8
    Purple 500       #9654FF
    Purple 400       #B678FF
    Purple 300       #D3A5FF
    Text Primary     #FAF7FF
    Text Secondary   #CFC3DA
    Text Muted       #9587A3

### Runtime
Double-click `run.bat`. It installs `pywebview` if necessary, then opens the
holographic desktop UI. `legacy_main.py` remains available as the native Tk fallback.


## v0.3.17 — WebView Reliability+

### Fixed: giant white HASHRATE ACTIVITY area

The dashboard canvases now have explicit CSS heights before their backing-store
size is changed. The renderer also falls back to the parent panel width if
WebView2 temporarily reports a zero-width canvas during startup.

This prevents the 1-pixel-wide intrinsic canvas condition that could scale the
HASHRATE ACTIVITY canvas into an enormous white rectangle while scrolling.

The chart surface is explicitly painted with the app's dark background before
grid/line rendering, preventing transient white WebView2 backing-store flashes.

### Cleaner first launch

`run.bat` now:

- suppresses the harmless pip script-location warning
- checks installation failure explicitly
- closes the setup console after requirements are installed
- launches the application through `pyw`/`pythonw` when available
- includes a new `diagnose.bat` for startup troubleshooting

`launch.pyw` writes unexpected launch failures to `startup-error.log` and shows
a Windows error dialog instead of silently disappearing.


## v0.3.17 — Python Launcher Reliability+

This release fixes Windows startup on systems where the global `pyw.exe`
launcher points to a stale or removed Python installation.

### Root cause

The affected machine had a working interpreter at:

    C:\Python314\python.exe

but the global Windows Python windowed launcher attempted to create:

    C:\Users\...\Python\pythoncore-3.14-64\pythonw.exe

That target did not exist, so `pyw.exe launch.pyw` failed before Bitcoin Miner
Studio itself could start.

### New launch architecture

`run.bat` now resolves a working `python.exe` first and invokes `bootstrap.py`.
`bootstrap.py` then:

- installs/checks pywebview using that exact interpreter
- derives `pythonw.exe` from the same interpreter directory
- launches `launch.pyw` using its absolute path
- never uses the global `pyw.exe` association
- falls back to a detached `python.exe` process if matching `pythonw.exe` is not present

`diagnose.bat` uses the same interpreter-selection path, so diagnostics and normal
launch can no longer silently use different Python installations.


## v0.4.1 — Block Template Engine

Bitcoin Miner Studio now consumes and validates Bitcoin Core `getblocktemplate`
work data through the holographic Bitcoin Core workspace.

### Template data

The engine exposes:
- next block height
- previous block hash
- 256-bit target
- compact `bits`
- target-derived difficulty
- transaction count
- dependency count
- aggregate transaction fees
- coinbase value
- estimated block subsidy when fee data is complete
- transaction weight and sigop totals
- block weight / size / sigop limits
- nonce range
- current and minimum block times
- rules, mutable fields, capabilities, and witness commitment metadata

### Refresh behavior

Block templates have an independent automatic refresh setting. The default is
15 seconds and it can be configured from 5–300 seconds in the Bitcoin Core page.
The UI displays template age, next refresh countdown, RPC latency, and stale-state
indication.

### Validation

The template engine validates required fields and the 256-bit mining target. If
the explicit `target` field is unavailable, the target can be reconstructed from
compact `bits`. The self-test suite includes a mock `getblocktemplate` RPC and
checks target/difficulty conversion, transaction fees, coinbase value, subsidy,
weight, sigops, and dependency metadata.

This release does **not** submit blocks or construct payout coinbases yet; those
remain later v0.4.x milestones.


## v0.4.2.1 — Bitcoin Core Setup Assistant

The Bitcoin Core page now includes a local setup assistant designed to remove
most manual RPC configuration.

### Detection

The assistant checks local-only resources for:
- standard Bitcoin Core data directories
- `bitcoin.conf`
- Mainnet, Testnet3, Testnet4, Signet, and Regtest settings
- standard local RPC ports
- `.cookie` authentication
- common Bitcoin Core executable locations
- whether Bitcoin Core/bitcoind appears to be running
- the `server=1` setting when it is present in `bitcoin.conf`

No public network scanning is performed.

### `.cookie` authentication

Bitcoin Miner Studio can now authenticate with Bitcoin Core's rotating `.cookie`
credential. The cookie is read when an RPC request is made, so a Core restart and
cookie rotation do not require manually updating a password in Bitcoin Miner
Studio.

Manual `rpcuser` / `rpcpassword` authentication remains supported.

### Auto Configure

**Auto Configure** detects the local node and updates Bitcoin Miner Studio with:
- detected network
- correct localhost RPC port/URL
- Bitcoin data directory
- `.cookie` path
- recommended authentication method

Auto Configure does not silently edit `bitcoin.conf`.

### Recommended configuration

If Bitcoin Core GUI is not exposing RPC, **Show Recommended Config** displays a
local-only `bitcoin.conf` snippet using `server=1`, `rpcbind=127.0.0.1`, and
`rpcallowip=127.0.0.1`. The user remains in control of whether that file is
changed.


## v0.4.2.1 — Setup Detection Hotfix

- Missing default Bitcoin Core folders are no longer shown as detected paths.
- Auto Configure only saves data-directory and cookie paths that actually exist.
- The expected Windows default path is reported separately for guidance.
- Added Windows App Paths registry lookup and additional common executable locations.
- When no installation is found, the assistant clearly reports that Bitcoin Core must be installed or run once before local RPC/cookie detection can succeed.


## v0.4.2.2 — Core Location & Launch Assistant

This recovery release handles the case where automatic detection cannot find
Bitcoin Core.

### New setup recovery actions
- Locate Core EXE
- Choose Data Folder
- Start Bitcoin Core
- Open Data Folder
- Download Bitcoin Core

A manually selected executable must be `bitcoin-qt.exe` or `bitcoind.exe`.
The path is persisted and included in later automatic detection.

Auto Configure now fails clearly when no Bitcoin Core installation is known,
instead of applying a default RPC URL and appearing to succeed.

The app does not silently install software or rewrite bitcoin.conf.


## v0.4.2.3 — Windows Core Discovery Fix

- Uses `%LOCALAPPDATA%\Bitcoin` as the current Windows default data directory.
- Keeps `%APPDATA%\Bitcoin` as a legacy fallback.
- Reads Bitcoin-Qt's saved `strDataDir` from Windows QSettings registry keys.
- Reads the running `bitcoin-qt.exe` / `bitcoind.exe` executable path via CIM.
- Parses `-datadir` from the running process command line.
- Prioritizes verified process/registry paths over guessed defaults.

This fixes the case where RPC is listening and Core is running, but Miner Studio
still reports no executable, data directory, or `.cookie`.


## v0.4.2.4 — Python Bridge Reliability Fix

Fixes intermittent `ERROR: Python API is not ready.` on WebView2 startup.

- API calls now wait for `window.pywebview.api` instead of failing immediately.
- Adds a fallback polling path when `pywebviewready` fires before `script.js` subscribes.
- Prevents duplicate initialization/state timers.
- Core/template action controls remain disabled until the Python bridge is ready.
- If initial injection is delayed, the UI automatically recovers without restarting.
- Existing Bitcoin Core executable/data-dir values are preserved.


## v0.4.2.5 — Responsive Startup Hotfix

Fixes a regression in v0.4.2.4 that could make the WebView appear frozen or
"Not Responding", particularly while Bitcoin Core was busy with Initial Block
Download.

### Changed
- Initial Bitcoin Core discovery is now a background daemon task.
- Removed the high-frequency Python bridge wait loop.
- Removed the 250 ms bridge polling interval.
- Bridge fallback uses one lightweight 500 ms chained timeout.
- Live UI state polling is serialized at 1.5 seconds.
- A new state request cannot begin until the previous request has completed.
- Duplicate bridge-ready events cannot create duplicate state pollers.
- Existing Bitcoin Core executable/data-directory settings are preserved.


## v0.4.2.6 — Purple Dragon Security Foundation

Adds signed build provenance and tamper detection without putting a private
secret inside the application.

- Publisher-signed RSA-3072 integrity manifest.
- SHA-256 verification of critical backend and WebView files.
- Encoded Purple Dragon forensic provenance marker.
- Unique build/provenance tag.
- Local-only hashed install fingerprint for future license binding.
- Background integrity verification so startup remains responsive.
- `verify_build_integrity.bat` for owner verification.
- Publisher signing utility under `tools/`.
- The private publisher key is deliberately excluded from the application ZIP.

This makes unauthorized modification/resale easier to detect and establishes
the foundation for publisher-signed machine-bound licenses. It does not claim
that raw Python source is impossible to reverse engineer.


## v0.4.3 — Coinbase & Payout

Adds the transaction-construction stage between a live `getblocktemplate` and
future solo-mining header work.

- Local Base58Check, Bech32 and Bech32m payout-address validation.
- Mainnet/testnet4/testnet/signet/regtest network mismatch protection.
- P2PKH, P2SH, P2WPKH, P2WSH, Taproot and future witness-program support.
- BIP34 block-height coinbase scriptSig construction.
- `coinbaseaux.flags` preservation from Bitcoin Core.
- Configurable Purple Dragon coinbase tag and extranonce placeholder.
- Exact subsidy + template-fee + maximum coinbase-value accounting.
- BIP141 default witness commitment output and 32-byte reserved witness value.
- Coinbase TXID/WTXID, raw transaction, weight/vsize and script preview.
- Live preview automatically rebuilds when Bitcoin Core provides a fresh block
  template and a payout address has been saved.
- No wallet private key or seed phrase is requested, stored, or needed.

The coinbase builder prepares a candidate transaction only. It does not submit
blocks or claim that a candidate has satisfied the network target; those are
separate future solo-mining stages.


## v0.4.3.1 — Coinbase Responsiveness Hotfix

This hotfix isolates the new Coinbase & Payout feature from automatic background template work.

- Automatic `getblocktemplate` refresh no longer rebuilds coinbase previews.
- Saving payout configuration no longer constructs a coinbase transaction.
- Building a preview uses the already-ready template and does not trigger a nested RPC request.
- Coinbase preview construction is explicitly user-driven.
- The UI no longer forces an extra full-state refresh after build/save actions.
- Coinbase DOM rendering is de-duplicated and null-safe.
- A new block template invalidates the old preview and asks for an explicit rebuild.

This preserves the live Block Template Engine while removing the new v0.4.3 cross-thread work path most likely to cause WebView/Windows responsiveness problems.


## v0.4.5 — Block Assembly & Submission

Completes the guarded path from a target-valid Solo Mining Engine candidate to
Bitcoin Core's proposal-validation and block-submission RPCs.

### Full block assembly
- Preserves the exact template/work/coinbase tied to the successful header.
- Serializes header + CompactSize transaction count + coinbase + all raw template transactions.
- Recomputes and verifies the transaction merkle root.
- Re-hashes the 80-byte header and verifies the network target again.
- Verifies previous-block hash, nonce, witness commitment, block size and block weight.
- Keeps multi-megabyte raw block hex backend-only instead of pushing it through WebView state polling.

### Candidate preservation
Target-valid candidates are automatically archived under:

`~/.bitcoin-miner-studio/candidates/`

Each archive contains JSON metadata plus the full `.block.hex`.

### Bitcoin Core proposal validation
Before submission, Miner Studio:
1. calls `getbestblockhash` and rejects stale work;
2. calls `getblocktemplate` in proposal mode with the complete block;
3. surfaces Bitcoin Core's exact BIP22-style rejection reason;
4. checks `getbestblockhash` again immediately before submission.

### Controlled submitblock
- No arbitrary raw-block submission textbox or public API exists.
- Only the internally preserved target-valid candidate can reach `submitblock`.
- Explicit user authorization is required.
- Proposal validation is required by default.
- `submitblock` null is reported as accepted; rejection strings are preserved for diagnostics.

### Mainnet expectation
The **Test Block Assembly** button intentionally uses nonce 0 and normally shows
`Target met: NO` on mainnet. That verifies complete serialization without
pretending a normal hash is a valid block.

The next milestone is **v0.4.6 — Regtest Mining Laboratory**, where the complete
find → assemble → proposal → submitblock → accepted-block workflow can be tested
repeatedly at easy local difficulty.


## v0.4.5.1 — Submission Responsiveness Hotfix

Fixes the v0.4.5 WebView freeze / Windows "Not Responding" regression.

The first v0.4.5 build executed expensive full-block work directly inside
pywebview API calls. A current mainnet template can contain thousands of raw
transactions and several megabytes of data, and Bitcoin Core proposal/submission
RPCs can also take seconds. Blocking the bridge for that long could make the
window appear frozen.

### Fixed
- Test Block Assembly now launches a daemon background worker.
- Assemble Candidate now runs in the background.
- Bitcoin Core proposal validation now runs in the background.
- Controlled submitblock now runs in the background.
- Only one block/submission operation can run at a time.
- The WebView API returns immediately after starting an operation.
- UI buttons are disabled while a block operation is active.
- Completion/error text is delivered through the existing serialized state
  refresh loop instead of holding the bridge call open.
- No multi-megabyte raw block is returned through recurring WebView state.

All target, stale-work, proposal-validation and explicit-authorization guards
from v0.4.5 remain intact.


## v0.4.5.2 — Performance+ Mode

Adds a persistent **Performance+** toggle to the top bar.

Performance+ is designed to improve Bitcoin Miner Studio responsiveness and
reduce UI/GPU/background-monitoring overhead without weakening the mining work
freshness path.

### When enabled
- WebView state polling changes from 1.5 seconds to 3 seconds.
- A minimized/hidden window is throttled to a 10-second UI refresh.
- Holographic aurora, blur-heavy glass effects, animated orb/rings and several
  compositor-heavy shadows/transitions are reduced or disabled.
- Hashrate charts redraw every other state cycle.
- Log and ASIC tables update only when their data actually changes.
- UI-facing logs/recent-share payloads are smaller.
- Bitcoin Core informational health polling has a 20-second minimum interval.
- getblocktemplate monitoring remains at 15 seconds or faster to avoid
  sacrificing new-block work freshness.
- Solo Mining Engine uses an internal minimum batch size of 50,000 hashes to
  reduce Python loop/yield overhead.
- Full block assembly/proposal/submitblock remains on the v0.4.5.1 serialized
  background worker.

The user's normal settings remain intact; disabling Performance+ immediately
returns the standard visual/polling profile.


## v0.4.5.3 — Candidate Gating Hotfix

Fixes a state/UI bug discovered during live mainnet testing.

### Problem fixed
`Test Block Assembly` intentionally assembles a complete current-template block
with nonce 0. On mainnet this normally fails the network target, but the old UI
state marked every successfully assembled structure as `candidate_available`.
That could enable `Assemble Candidate` and `Validate with Core` even though the
display correctly showed `TARGET CHECK: FAIL`.

The backend submission guards still prevented a non-target-valid block from
reaching `submitblock`, but the UI state was misleading.

### New hard separation
- A **structure test** can be `assembled = true` while
  `candidate_available = false`.
- `Test Block Assembly` always returns `candidate_available = false`.
- Only a candidate preserved by Solo Mining after `hash <= target` receives
  `candidate_available = true`.
- **Assemble Candidate** requires both `candidate_available` and `target_valid`.
- **Validate with Core** requires both flags.
- **Submit Candidate** requires both flags plus all existing stale/proposal/
  authorization safeguards.
- Solo Mining labels now say **guarded submission** rather than the obsolete
  `submit disabled` wording.

This preserves the v0.4.5.1 background-worker responsiveness fix and the
v0.4.5.2 Performance+ profile.


## v0.4.5.4 — Dashboard Layout Polish

Reorganizes the main Dashboard without changing mining, RPC, Performance+,
candidate-gating, or submission behavior.

### Dashboard changes
- System Monitor moved out of the bottom-left corner.
- System Monitor now sits directly beside the Hashrate Activity chart.
- Recent Activity moved into a full-width row underneath.
- Recent Activity uses a compact multi-column layout on desktop.
- Responsive breakpoints collapse the panels naturally on smaller windows.
- Existing System Monitor IDs/data bindings are unchanged, so CPU/ASIC/share
  telemetry continues to update exactly as before.

This release preserves the v0.4.5.1 background block worker, v0.4.5.2
Performance+ Mode, and v0.4.5.3 candidate-gating safeguards.


## v0.4.5.5 — Clear Activity Log

Adds a **Clear Log** button beside **Refresh** on the Logs page.

- Clears the current in-app activity history through the Python backend.
- Recent Activity is cleared at the same time because it uses the same log source.
- Leaves one confirmation entry: `Activity log cleared.`
- Does not delete Bitcoin Core's `debug.log`, candidate archives, ASIC history,
  or any external/system log files.
- Works with Performance+ log de-duplication.

All mining, block assembly, candidate gating, Performance+, Purple Dragon, and
guarded submitblock behavior is unchanged.


## v0.4.6 — Regtest Mining Laboratory

Adds a dedicated local Bitcoin Core regression-test environment so the complete
mining/submission workflow can be exercised repeatedly without mainnet funds,
mainnet difficulty, or changes to the user's synced mainnet data directory.

### Isolation
The laboratory launches a second Bitcoin Core instance using:
- `-regtest=1`
- dedicated data directory: `~/.bitcoin-miner-studio/regtest-lab`
- dedicated loopback RPC: `127.0.0.1:19443`
- dedicated P2P port: `19444`
- P2P listening disabled
- discovery/DNS seeds/UPnP/NAT-PMP/Tor listening disabled
- cookie RPC authentication
- a dedicated wallet named `MinerStudioRegtest`
- a dedicated `bcrt1...` receiving address

The main Bitcoin Core configuration, mainnet data directory, mainnet wallet and
mainnet RPC settings are not switched or overwritten.

### Full mining laboratory cycle
For every requested regtest block, Bitcoin Miner Studio performs:

1. `getblocktemplate`
2. build a real coinbase paying the dedicated regtest wallet
3. build the transaction Merkle root
4. serialize the exact 80-byte block header
5. perform real double-SHA256 nonce search against regtest target
6. assemble the complete raw block
7. verify target/merkle/size/weight locally
8. call Bitcoin Core `getblocktemplate` proposal mode
9. call guarded `submitblock`
10. confirm the accepted hash using `getblockcount` + `getblockhash`

### Mine 101 Blocks
A dedicated **Mine 101 Blocks** button performs the complete pipeline 101 times.
This advances coinbase outputs to maturity so the Regtest Lab can demonstrate a
spendable wallet balance while stress-testing repeated template/assembly/
proposal/submission cycles.

### Responsiveness
Start, refresh, mining, stop and reset operations run through a serialized
`RegtestLabWorker` background thread. The WebView remains responsive during
longer 101-block runs.

### Reset safety
Reset requires an explicit checkbox and deletes only the dedicated
`~/.bitcoin-miner-studio/regtest-lab` directory.

The next milestone after successful live testing is **v0.4.7 — Solo Mining
Dashboard+ & Reliability**, followed by **v0.5.0 — ASIC Solo Mining Integration**.


## v0.4.6.1 — Regtest Lifecycle Hotfix

Fixes the first live Regtest Lab state-machine issue found during testing.

### Fixed
- `Refresh Lab` is disabled while the isolated lab is stopped.
- Backend `refresh_regtest_lab()` also rejects stopped refresh attempts.
- A missing Regtest `.cookie` before Start Lab is treated as a normal stopped
  state instead of a node/RPC failure.
- Every `RegtestLabWorker` success path now clears `busy` and `operation`.
- Start Lab returns to `Ready` after the isolated node is RPC-ready.
- Refresh Lab returns to `Ready` after a successful refresh.
- Stop/Reset jobs return to a clean `Stopped` state.
- Buttons no longer remain permanently disabled after a completed background job.

The mainnet Bitcoin Core node/data directory remains untouched.


## v0.4.6.2 — Backend Bridge Startup Hotfix

Fixes a startup regression where the HTML UI could remain on:

`Bitcoin Miner Studio backend is still starting.`

with the Bitcoin Core controls permanently disabled.

### Startup architecture change
The `WebBackend` constructor now performs only lightweight in-memory setup.
The following work is explicitly deferred until **after pywebview has exposed
the Python API bridge**:

- Bitcoin Core health monitor
- getblocktemplate monitor
- Purple Dragon integrity verification
- Bitcoin Core installation/data-directory discovery
- prior Regtest Lab reconnect probing
- known ASIC fleet reload

This prevents Windows filesystem/RPC/security work from racing pywebview's API
registration during window creation.

### Bridge recovery
- Removed the previous 20-second / 40-attempt retry limit.
- The UI now retries the Python bridge indefinitely with bounded backoff.
- API actions wait briefly for a late bridge instead of immediately throwing
  `backend is still starting`.
- The Bitcoin Core setup result box shows connection retry progress.
- Once `get_bootstrap` succeeds, the UI explicitly starts background services.

The Regtest v0.4.6.1 lifecycle hotfix, Performance+, candidate gating,
background block-submission worker, Clear Log, and mainnet isolation are all
preserved.


## v0.4.6.3 — WebView Bridge Rebuild

Fixes the persistent startup state:

`Connecting to Bitcoin Miner Studio backend... retry N`

### Bridge architecture change
The application no longer passes the complete `WebBackend` instance to
`create_window(..., js_api=backend)`.

v0.4.6 added nested Regtest Lab/controller state to the backend. v0.4.6.3
instead generates flat public `*args` wrappers and exposes those functions with
`window.expose(...)`.

Only callable API endpoints are exposed. Regtest controller objects, locks,
miners, RPC state, fleet objects and other backend internals are not handed to
pywebview's API-introspection layer.

### Local UI path
The UI is loaded as a local filesystem path instead of a `file://` URI, using
pywebview's normal local-content handling.

### Readiness/recovery
- `pywebviewready` is listened for on both `window` and `document`.
- Direct API detection remains enabled.
- Automatic bridge retries remain enabled.
- Background RPC/filesystem/security work still starts only after the bridge is live.

### Startup diagnostics
Every launch writes `startup-bridge.log` in the app folder. It records Python,
pywebview, UI path, bridge mode, exposed function count, and critical-function
exposure. If pywebview throws during startup, the traceback is written there.

Regtest functionality, lifecycle fixes, Performance+, candidate gating,
background submission and Clear Log are preserved.


## v0.4.6.4 — Bitcoin Core 31 Regtest Compatibility

Fixes the live Regtest Lab startup failure:

`Regtest Bitcoin Core exited during startup (code 1).`

Bitcoin Core v30 removed the legacy `-upnp` option. The Regtest launcher still
passed `-upnp=0`, so Bitcoin Core v31.1 rejected the command line and exited.

### Current-safe isolation profile
The laboratory now launches with:
- `-regtest=1`
- dedicated `-datadir`
- `-server=1`
- `-listen=0`
- `-networkactive=0`
- loopback-only RPC bind/allow
- dedicated RPC port `19443`

Removed obsolete/redundant P2P arguments:
- `-upnp=0`
- `-natpmp=0`
- `-listenonion=0`
- `-discover=0`
- `-dnsseed=0`
- custom P2P port

### Startup diagnostics
Bitcoin Core startup output is captured to:
- `regtest-startup.stdout.log`
- `regtest-startup.stderr.log`

If startup fails again, Miner Studio now surfaces the actual Bitcoin Core error
(or the tail of Regtest `debug.log`) instead of only an exit code.

The v0.4.6.3 WebView bridge rebuild and all Regtest/mainnet isolation safeguards
remain intact.


## v0.4.7 — Solo Mining Dashboard+ & Reliability

Turns the Solo Mining Engine into a richer live mining dashboard while adding
additional stale-work and monitor-failure safeguards.

### Dashboard+
The Solo Mining panel now displays:
- current / average / peak hashrate
- total hashes
- best difficulty
- best-hash / network-target ratio
- work-template age
- expected mean time to a block at the measured average hashrate
- time to a 50% cumulative success probability
- exact session success probability
- projected 1-hour, 24-hour and 7-day probabilities
- live best-work-to-target progress
- template switch count
- stale batch/hash discard counters
- stale candidate rejection counter
- effective hash batch size
- extranonce rolls
- a dedicated 90-sample Solo Hashrate chart
- recent session-best hash history

Probability values are informational mathematics based on the current target
and measured average hashrate. They do not imply a guaranteed block time.

### Stale-work protection
If Bitcoin Core reports a new chain-tip template while a CPU hash batch is
still executing:
1. the completed old-template batch is counted for performance telemetry;
2. its best-work result is not promoted;
3. a target-valid result from that superseded work is not preserved;
4. Miner Studio immediately switches to the queued fresh template.

The dashboard reports how many batches/hashes were discarded as stale work.

### Template-monitor reliability watchdog
When automatic fresh-template switching is enabled, three consecutive
`getblocktemplate` failures stop Solo Mining rather than allowing the engine to
continue indefinitely on aging work. A single transient RPC failure does not
stop mining.

### Candidate-safe reset
`Reset Stats` clears session metrics/history without deleting a target-valid
candidate that has already been preserved for the guarded submission pipeline.

### Existing systems preserved
- v0.4.6 Regtest Mining Laboratory
- Bitcoin Core 31 compatibility
- WebView bridge rebuild
- Performance+ Mode
- Purple Dragon provenance/integrity
- background block assembly/proposal/submitblock
- candidate gating
- Clear Log


## v0.5.0 — ASIC Solo Mining Integration

Adds a real **LAN-only Stratum V1 Solo Bridge** that connects authorized Bitcoin
ASIC hardware to the Bitcoin Core candidate/submission stack already built in
v0.4.x.

### ASIC Solo Bridge

The ASIC Control Center can launch:

`stratum+tcp://<private-LAN-IP>:3333`

The bridge:

- binds only to a literal private IPv4 interface;
- refuses wildcard (`0.0.0.0`), public, and loopback bind addresses for live ASIC use;
- rejects non-private client addresses;
- consumes the live normalized Bitcoin Core `getblocktemplate`;
- constructs coinbase transactions paying the configured public payout address;
- assigns a unique 4-byte `extranonce1` to each ASIC session;
- accepts a 4-byte miner `extranonce2`;
- broadcasts `mining.set_difficulty` and clean `mining.notify` jobs;
- supports subscribe, authorize, submit, extranonce.subscribe,
  suggest_difficulty, and a conservative `mining.configure` response;
- rejects stale, duplicate, malformed, and low-difficulty shares;
- independently reconstructs every submitted 80-byte block header.

### Share vs Bitcoin target

Normal ASIC shares are used for telemetry only.

A candidate is promoted only when:

`SHA256d(header) <= live Bitcoin Core network target`

The candidate is then independently reconstructed again and enters:

`ASIC → Stratum → target check → candidate preservation → full block assembly
→ current-tip check → Bitcoin Core proposal validation → explicit authorization
→ submitblock`

**v0.5.0 never auto-submits a block.**

### Best-effort ASIC pool assignment

For a device with a verified cgminer-compatible API, the new **Solo** action:

1. reads its current pool list;
2. reuses the local Miner Studio endpoint if it already exists;
3. otherwise attempts `addpool`;
4. switches to that pool with `switchpool`.

Existing pools are **not deleted**.

The new **Pool 0** action switches the device back to its existing pool index 0.

Many production ASIC firmwares intentionally make the cgminer API read-only.
When firmware rejects `addpool`, Miner Studio reports the refusal and the local
Solo Bridge endpoint can be entered through the miner's normal Web UI.

### Live ASIC Solo telemetry

The ASIC Control Center displays:

- current template height and job age;
- connected and authorized Stratum clients;
- accepted / rejected / stale shares;
- best submitted share difficulty;
- share-derived hashrate estimate;
- target-valid candidate count;
- current payout address / job / previous block;
- last share and candidate hashes;
- connected and recent worker table;
- per-device `ASSIGNED` / `CONNECTED` Solo state.

### Stale-work protection

The bridge receives new clean work directly from the Block Template Engine.
Three consecutive `getblocktemplate` failures stop the bridge so connected
ASICs do not continue hashing prolonged stale work.

### Boundary / authorization

This remains a visible local-control feature:

- the existing ownership/admin checkbox is required before starting the bridge
  or changing an ASIC pool;
- private LAN interfaces/clients only;
- no stealth operation;
- no persistence;
- no remote installation;
- no wallet seed phrase or private key;
- no deletion of existing ASIC pool entries.


## v0.5.0.1 — ASIC Discovery False-Positive Hotfix

Fixes automatic ASIC discovery incorrectly promoting ordinary LAN devices into
the MINERS table merely because they exposed an HTTP/HTTPS management interface
or answered a candidate probe.

### Positive evidence required

Automatic discovery now adds a device only when Miner Studio obtains at least
one ASIC-specific signal:

- a successfully parsed cgminer-compatible `summary` response; or
- a positively recognized Antminer / Bitmain, WhatsMiner / MicroBT, or
  Avalon / Canaan Web UI identity.

A generic router, PC, NAS, printer, console, access point, etc. is ignored even
if it exposes HTTP/HTTPS or a candidate management port.

### v0.5.0 cleanup

Running **Discover ASICs** again removes old auto-discovered false-positive
hosts that fail the new ASIC-specific verification.

Reachable generic Web devices from the previous v0.5.0 known-device list are
also cleaned up during reload/refresh.

An unreachable known device is not automatically deleted because a legitimate
ASIC may simply be powered off.

### Manual troubleshooting

**Add IP** still permits an unverified private LAN address. Such entries are
marked as manual and are retained for troubleshooting even if verification
fails.

### HTTP authentication handling

ASIC Web UIs commonly return HTTP 401/403. Miner Studio now reads the `Server`
and `WWW-Authenticate` headers from those responses so vendor-identifiable ASIC
interfaces can still be recognized without storing or requesting Web UI
credentials.


## v0.6.0 — Purple Dragon Security

Purple Dragon moves from a hidden signed-manifest mechanism to a visible
Security Center and an enforcement layer for critical operations.

### Signed release provenance v2

Every protected release contains a publisher-signed `purple_dragon_manifest.json`
using an embedded **public verification key**. The publisher private key is not
included in Bitcoin Miner Studio.

The v2 manifest binds:
- product and version;
- Purple Dragon security scheme;
- publisher verification-key ID;
- build ID / provenance tag;
- forensic release watermark and release seal;
- SHA-256 hashes for protected application files.

Verification is completely offline.

### Fail-safe critical-action gating

When the signed manifest, forensic marker, publisher signature, or any protected
file fails verification, Bitcoin Miner Studio remains open for diagnosis but
locks actions that can materially change mining/device state:

- Start Pool Mining
- Start Solo Mining
- Start ASIC Solo Bridge
- ASIC `addpool` / pool switching
- ASIC restart controls
- guarded `submitblock`

Stop controls, diagnostics, Bitcoin Core health views, logs, and other read-only
features remain available. This prevents integrity protection from blocking a
user from stopping an already-running operation.

### Purple Dragon Security Center

The new sidebar page shows:
- TRUSTED / CHECKING / LOCKED state;
- publisher signature status;
- verified/protected file count;
- build ID and provenance tag;
- publisher key ID;
- release watermark / release seal;
- privacy-reduced local install code;
- per-file VERIFIED / MODIFIED / MISSING status;
- one-click offline re-verification;
- copyable public security report.

### Forensic release footprint

The Purple Dragon phrase remains encoded, while v0.6.0 also embeds a unique
per-release watermark in multiple protected locations and binds it into the
publisher-signed manifest. This is intended to provide provenance evidence if a
build is modified or redistributed under another name.

It is deliberately **not described as a secret or unremovable watermark**. A
motivated reverse engineer can modify software. The signature/integrity system
makes those modifications detectable by an unmodified verifier.

### What Purple Dragon does not claim

No local software can truthfully guarantee that it can never be cracked,
copied, reverse engineered, or resold. v0.6.0 therefore avoids fake
anti-cracking claims, anti-debugging tricks, destructive behavior, or hidden
phone-home activation. It provides defense in depth through signed provenance,
tamper evidence, and fail-safe critical-control gating.


## v0.6.1 — Miner XP & Hash Hunt

Adds an optional local gamification layer without coupling progression to real
Bitcoin mining.

### Miner Rank

The Dashboard now contains a compact Miner Rank strip and the sidebar contains
a dedicated **Miner XP** workspace.

Miner Rank uses a cumulative XP curve:

`next threshold = 25 × level × (level + 1)`

Examples:

- Level 1 → 50 XP
- Level 2 → 150 XP
- Level 3 → 300 XP
- Level 4 → 500 XP
- Level 5 → 750 XP
- Level 6 → 1,050 XP

This intentionally matches the style of a `Level 6 · 992 / 1050 XP` progression
display.

### Hash Hunt

Hash Hunt runs one tiny browser-side double-SHA256 mini-game attempt per button
press. It does **not** hash a real Bitcoin block header and does not communicate
with Bitcoin Core, a pool, an ASIC, or the submission engine.

Difficulties:

- Casual — approximately 1/2 mini-game share target
- Standard — approximately 1/4
- Hard — approximately 1/8
- Purple Dragon — approximately 1/16, unlocked at Miner Level 7

Each difficulty has its own:
- per-attempt XP
- valid-share XP
- block-meter size
- cosmetic block-completion bonus

Valid shares add the first four hexadecimal characters of the simulated hash to
the current block meter. Completing the meter enables a manual **Claim Block
Bonus** button.

### Achievements

v0.6.1 includes:
- First Share
- Hot Streak
- Hash Apprentice
- Block Builder
- Purple Dragon Share
- Hash Hunter

Achievement XP is local and cosmetic.

### Cosmetic unlocks

- Level 3 — Bronze Hash Badge
- Level 5 — Holographic Rank Glow
- Level 7 — Purple Dragon difficulty
- Level 10 — Dragon's Lair accent
- Level 15 — Satoshi Elite coin glow

### Strict isolation

Miner XP and Hash Hunt:
- do not alter real hashrate;
- do not alter mining process counts;
- do not alter pool/ASIC settings;
- do not alter Bitcoin Core;
- do not alter payout addresses;
- do not alter network target or difficulty;
- do not create or submit blocks;
- do not call `submitblock`.

Progress is stored locally in the WebView profile using `localStorage` and may
be reset by the user. It has no monetary value and is deliberately not treated
as a protected transferable asset.

### Purple Dragon Security

All modified UI files remain inside the signed Purple Dragon protected-file
manifest. v0.6.1 receives a fresh release watermark, release seal, Build ID and
publisher signature.


## v0.7.0 — Pool & Stratum PowerTools 2.0

This release upgrades the existing Stratum V1 pool-mining path with explicit
multi-endpoint resilience and a dedicated protocol/diagnostics workspace.

### Explicit endpoint failover

The Pool page now accepts one primary endpoint plus up to three backups.

All endpoints are normalized and de-duplicated before a session starts.
Failover only cycles through endpoints explicitly configured by the user.

Backup endpoints reuse the same worker/password. The password remains in the
existing credential backend and is not copied into `settings.json`, endpoint
diagnostic output, or the Stratum Inspector.

On a connection/session failure:

`active endpoint → stop local hash workers → choose next configured endpoint →
reconnect → subscribe → authorize → wait for fresh job → resume mining`

The live session exposes:
- active endpoint and endpoint index
- connection attempts
- reconnect count
- failover count
- disconnect count / last disconnect reason

### Job-silence watchdog

After authorization, Miner Studio expects ongoing `mining.notify` work.

The configurable watchdog defaults to 120 seconds. If no new work is received
within that interval, the current Stratum connection is considered unhealthy
and enters the normal reconnect/failover path rather than hashing indefinitely
without fresh pool work.

Allowed range: 20–1800 seconds.

### Endpoint Diagnostics Lab

**Test All Endpoints** starts a background Python worker; the WebView does not
block while endpoints are tested.

Each configured endpoint is profiled through:
- URL validation
- DNS resolution
- TCP connect
- TLS handshake/version/cipher when applicable
- `mining.subscribe`
- `mining.authorize`
- first `mining.notify` observation
- extranonce2 size
- observed difficulty
- aggregate endpoint score

Passwords are never included in the diagnostic state/report.

### Stratum Inspector

A sanitized live protocol timeline records method names and non-secret context:

- connect
- `mining.subscribe`
- `mining.authorize`
- `mining.suggest_difficulty`
- `mining.set_difficulty`
- `mining.set_target`
- `mining.set_extranonce`
- `mining.notify`
- `mining.submit`
- client reconnect events
- local endpoint failovers

The password is never captured. Authorization history records only the worker
name, and submit history records only job-level context.

### Share analytics

The Pool page now exposes:
- accepted / rejected / stale shares
- average submit-response latency
- p95 submit-response latency
- best locally observed share difficulty
- recent share table with per-share latency and difficulty
- local duplicate-submit prevention counter
- current difficulty and difficulty-change history
- total jobs, clean jobs and incremental job updates
- current job age

### Pool Health

PowerTools computes a 0–100 live pool-session health score from:
- connectivity / authorization
- rejected and stale share ratio
- connection latency
- p95 share response latency
- job freshness
- failovers and disconnects

Before a mining session begins, the existing dashboard Ready state remains
100% rather than being treated as a failed pool connection.

### Local test pool

Starting the Local Test Pool intentionally clears configured backup endpoints
for that local session. This prevents a local validation run from unexpectedly
failing over to a previously configured real pool.

### Compatibility

Pool & Stratum PowerTools 2.0 remains a Stratum V1 implementation. It preserves:
- optional `mining.suggest_difficulty`
- `mining.set_target`
- `mining.set_extranonce`
- `client.show_message`
- `client.reconnect`
- existing CPU SHA-256d share search
- retained session statistics
- Performance+
- Purple Dragon critical-action gating


## v0.7.0.1 — Purple Dragon Startup Hotfix

Fixes a v0.7.0 WebView initialization regression introduced by the Pool &
Stratum PowerTools 2.0 page replacement.

The old Pool page contained a `credentialBackend` DOM element. v0.7.0 replaced
that page but `initFields()` still unconditionally executed:

`$('#credentialBackend').textContent = ...`

Because the element no longer existed, JavaScript threw during startup. The
initialization catch path then marked the Python bridge unavailable and retried,
leaving Purple Dragon on its static `CHECKING / 0 of 0` screen and disabling
`Verify Build Now`.

### Fixes

- restores the credential-backend indicator in Pool PowerTools;
- makes the credential-backend UI assignment null-safe;
- adds a dedicated `get_security_state` bridge method;
- independently polls Purple Dragon startup state so unrelated dashboard
  rendering failures cannot strand Security Center on CHECKING;
- surfaces backend initialization errors in the Security Center result box;
- adds a startup DOM-contract regression test that verifies every element
  referenced by `initFields()` exists before packaging.

Pool & Stratum PowerTools 2.0 functionality is otherwise unchanged.


## v0.7.0.2 — Local Test Pool Reliability Hotfix

Fixes two Local Test Pool edge cases exposed while validating Pool & Stratum
PowerTools 2.0.

### Ephemeral localhost ports

The built-in Local Test Pool asks Windows for an available localhost port.
For example:

`stratum+tcp://127.0.0.1:61103`

That port is valid only while that exact Local Test Pool instance is alive.

v0.7.0/v0.7.0.1 could save the dynamically allocated endpoint in the normal
pool configuration. After restarting Miner Studio, Endpoint Diagnostics could
therefore test a dead localhost port and report a low TCP-stage score such as
15/100.

v0.7.0.2 now:

- marks built-in Local Test Pool endpoints as ephemeral;
- preserves the user's previous non-local pool configuration before the local
  test begins;
- restores that configuration when the Local Test Pool stops;
- restores it automatically on the next launch after an interrupted/crashed
  local-test session;
- migrates the legacy `local.worker1 + 127.0.0.1:<dynamic-port>` form from
  v0.7.0/v0.7.0.1 instead of attempting to reuse the stale port;
- produces a clear diagnostic error if an app-owned Local Test Pool endpoint is
  selected while the local server is not running.

### Multi-client Local Test Pool

The original validation server handled one connected client at a time. If the
CPU pool miner already held that connection, Endpoint Diagnostics could connect
at the TCP layer but wait indefinitely for its Stratum subscription to be
processed.

The local server now accepts multiple concurrent clients on independent daemon
threads. This allows:

`Local CPU pool miner + Quick Test + Test All Endpoints`

to operate against the same local validation pool concurrently.

The server remains bound exclusively to `127.0.0.1`.


## v0.7.0.3 — Local Worker Autofill Hotfix

Fixes the built-in Local Test Pool reporting:

`Worker / Wallet is required.`

after a successful local pool start.

The backend already selected `local.worker1` with password `x`, but the
PowerTools WebView only replaced the endpoint field. Pressing **Start Mining**
therefore sent the still-empty visible Worker / Wallet field back to Python and
overwrote the correct local worker before Stratum startup validation.

### Fix

Starting Local Test Pool now synchronizes the full local test configuration to
the form:

- endpoint: the newly allocated temporary localhost port;
- Worker / Wallet: `local.worker1`;
- password: `x`;
- backup endpoints: cleared for the local validation session;
- automatic failover: disabled for the local validation session.

Stopping Local Test Pool restores the complete previous pool form, not only its
primary URL.

### Backend protection

The UI fix is not the only guard. While the built-in Local Test Pool is active,
the Python backend treats its endpoint and local worker as authoritative. A
blank or stale WebView Worker field cannot overwrite `local.worker1`, and a
stale password field cannot replace the local test password.

This protects Quick Test, Endpoint Diagnostics and Start Mining from the same
class of UI-state mismatch.


## v0.7.0.4 — Windows Mining Spawn Hotfix

Fixes multiple Bitcoin Miner Studio windows opening when CPU pool mining or
benchmark workers are started on Windows.

### Root cause

Windows `multiprocessing` uses the **spawn** start method. Every child hash
worker starts a fresh Python interpreter and re-executes the original
application entry script.

`launch.pyw` previously called `main()` at module top level rather than behind
an `if __name__ == "__main__"` guard. When Windows re-executed that file as the
multiprocessing `__mp_main__` module, the child hash worker also launched the
WebView application.

With multiple mining processes configured, this could produce multiple visible
Bitcoin Miner Studio windows.

### Fix

`launch.pyw` now:

- has a proper `if __name__ == "__main__"` entry guard;
- calls `multiprocessing.freeze_support()`;
- contains a second `MainProcess` identity guard;
- never imports/starts the GUI when re-executed as a worker child.

`main.py` has the same secondary child-process guard for console/fallback
launches.

The Benchmark engine now also uses an explicit `spawn` multiprocessing context,
matching the real Stratum CPU miner, so both paths follow the same Windows
process model.

### Expected process layout

Starting 4 CPU mining processes should now look conceptually like:

`1 visible Bitcoin Miner Studio window + 4 headless SHA-256d worker processes`

not:

`5 Bitcoin Miner Studio windows`

### Regression coverage

The self-test re-executes `launch.pyw` and `main.py` under the special
`__mp_main__` module name used by Python multiprocessing preparation and asserts
that the GUI entry function is never called.


## v0.7.0.5 — Diagnostics Freshness Hotfix

Fixes a Pool PowerTools state mismatch where the active Local Test Pool could
be running on one temporary endpoint while **Endpoint Diagnostics Lab** still
showed completed results from an older localhost port.

For example, an active session on `127.0.0.1:59449` could still display a
retained diagnostic row for `127.0.0.1:61103`. The 15/100 result belonged to
the old endpoint, not the live mining session.

Diagnostics now record the exact normalized endpoint set they tested. Any
primary/backup endpoint change invalidates previous results. Starting or
stopping Local Test Pool also invalidates diagnostics tied to the former
temporary port, so obsolete rows disappear until **Test All Endpoints** is run
again.

The Local Test Pool now also forces `mining.suggest_difficulty` off for its
session. Persisted real-pool values such as difficulty `1.0` can no longer make
local validation shares unnecessarily rare; the local server uses its own fast
test difficulty and the user's normal preference is restored afterward.


## v0.8.0 — Monitoring & Analytics

Adds a persistent, local-only observability layer across the existing mining
stack. Monitoring is intentionally independent of mining correctness: disabling
or clearing analytics never starts/stops a miner, changes a pool, modifies
Bitcoin Core, changes an ASIC, or alters block-submission behavior.

### Local telemetry recorder

Operational samples are recorded to:

`~/.bitcoin-miner-studio/analytics.sqlite3`

Default policy:
- enabled;
- 10-second sampling;
- 30-day retention;
- SQLite WAL mode for responsive concurrent reads;
- automatic retention pruning;
- maximum history view downsampling to keep the WebView responsive.

Sampling may be configured from 5–300 seconds and retention from 1–365 days.

### Recorded operational fields

Pool:
- current/average hashrate;
- accepted/rejected/stale counters;
- acceptance rate;
- p95 share response latency;
- session health;
- job age;
- reconnect/failover counters.

Solo:
- current/average/peak hashrate;
- best difficulty / target ratio;
- stale-work batch counter.

Bitcoin Core:
- connected state;
- total RPC health-check latency;
- peers;
- sync percentage;
- block height.

ASIC fleet:
- device/online counts;
- aggregate hashrate;
- average/max temperature;
- average fleet health score.

### Analytics workspace

The new **Monitoring** sidebar page provides:
- 1H / 6H / 24H / 7D / 30D ranges;
- pool and solo hashrate history;
- pool-share and Bitcoin Core RPC latency history;
- pool health history;
- Bitcoin Core peer history;
- ASIC hashrate, temperature and health history;
- range summaries and accepted/rejected/stale deltas;
- local database size/sample status;
- operational event timeline.

### Operational events

Threshold activation and recovery events are stored for:
- low pool health;
- high p95 share latency;
- elevated rejected/stale share ratio;
- Bitcoin Core RPC offline/high latency;
- solo stale-work batches;
- ASIC offline state;
- ASIC temperature >= 80 °C.

The event system is informational. It does not automatically restart miners,
change pools, submit blocks, or alter ASIC configuration.

### Export

The current range can be exported to CSV or JSON under:

`~/.bitcoin-miner-studio/exports/`

### Privacy boundary

The analytics schema has no fields for:
- pool passwords;
- RPC passwords;
- wallet seed phrases;
- private keys;
- signing keys;
- raw authorization credentials.

The feature has no cloud endpoint, analytics service, telemetry server, or
phone-home mechanism. Monitoring data stays on the local machine unless the user
explicitly exports a file.


## v0.9.0 — Release Candidate

v0.9.0 begins the feature-frozen release-candidate phase before v1.0.0.

Major feature families are intentionally frozen. The v0.9.x line is for
release blockers, regressions, compatibility, security hardening, packaging,
diagnostics, documentation, accessibility and UI polish.

### RC Readiness

A new **RC Readiness** workspace performs local release preflight checks for:

- Python runtime and architecture;
- pywebview availability;
- cryptography publisher-verification runtime;
- SQLite runtime;
- required UI/startup/security assets;
- application-data write access and free-space signal;
- Windows multiprocessing GUI spawn guards;
- accidental publisher-private-key inclusion;
- Purple Dragon signed-build state;
- configuration type/range validation;
- accidental pool/RPC passwords in `settings.json`;
- Monitoring recorder readiness;
- previous clean/unclean application shutdown signal.

The result is summarized as:

- `RC READY`
- `RC READY · REVIEW WARNINGS`
- `SHIP BLOCKED`

Optional feature configuration such as not having an ASIC, external pool, or
Bitcoin Core path configured is not treated as a release blocker by itself.

### Feature freeze

Allowed in v0.9.x:
- bug fixes;
- compatibility fixes;
- crash/startup fixes;
- security hardening;
- performance-regression fixes;
- release diagnostics;
- packaging;
- accessibility/UI polish;
- documentation.

Frozen unless required to resolve a blocker:
- new mining protocol families;
- new major mining engines;
- large architectural rewrites;
- major persistent-data migrations;
- new remote-control surfaces.

### Crash-safe session signal

Miner Studio records a tiny local runtime-session marker.

On normal shutdown it records a clean exit. If the next launch sees that the
previous session never reached clean shutdown, RC Readiness shows a warning so
startup/crash logs can be reviewed.

This is diagnostic only and never disables mining.

### Local support bundle

**Create Support Bundle** writes a ZIP under:

`~/.bitcoin-miner-studio/support/`

The bundle is created locally and **is not uploaded anywhere**.

It may contain:
- RC preflight report;
- runtime/platform summary;
- sanitized settings;
- redacted in-app activity log;
- redacted Pool PowerTools diagnostic report;
- startup-error/startup-bridge logs when present;
- public Purple Dragon signed manifest.

It explicitly excludes:
- pool/RPC passwords;
- wallet seed phrases;
- private keys;
- publisher private signing key;
- payout addresses/worker identifiers from support text;
- the Monitoring SQLite database;
- automatic cloud upload.

### Release metadata

`release_info.json` identifies:
- version `0.9.0`;
- channel `Release Candidate`;
- feature freeze enabled;
- support/preflight schema versions;
- cloud telemetry disabled;
- automatic support upload disabled.

### v1.0 promotion gate

The current target for v1.0.0 Stable is:
- no known blocking startup/mining crashes;
- trusted Purple Dragon release;
- repeatable clean startup/close;
- stable Pool/Solo/Core/ASIC/Regtest paths;
- stable Monitoring & Analytics;
- reproducible release diagnostics;
- no credentials embedded in release/support artifacts.

### Isolated self-test profile

The Release Candidate regression suite now creates a temporary application-data
home before importing Miner Studio modules. Self-tests therefore cannot read,
overwrite, clear, or migrate the user's real settings, Monitoring SQLite
history, Regtest Lab files, fleet history, support bundles, or runtime-session
marker. Multiprocessing test children inherit the same isolated test profile.


## v0.9.0.1 — RC Preflight Cleanup Hotfix

Fixes the Release Candidate screenshot state where RC Readiness could show
`96/100` with one warning:

`An interrupted Local Test Pool session marker is still set.`

The Local Test Pool endpoint/marker is intentionally ephemeral. If the built-in
local server is not running, stale ephemeral metadata is now normalized before
RC scoring and persisted back to settings.

The marker is preserved while the Local Test Pool is genuinely running.

### Configuration readiness tile

A completely clean configuration previously produced no configuration issue
rows, causing the RC summary tile to render `—`.

Clean validation now emits an explicit `Configuration validation: PASS` gate,
so the summary tile correctly shows `PASS`.

Expected clean result:

`RC READY · 100/100 · 0 blockers · 0 warnings`


If the Local Test Pool is intentionally running during preflight, its live
ephemeral marker remains untouched but is excluded from RC scoring because it
is expected operational state, not a release warning.


## v0.9.0.2 — Theme Studio

Theme Studio is a Release Candidate UI-polish update. It does not add or alter
mining protocols, mining engines, Bitcoin Core behavior, ASIC controls, pool
credentials, payouts, or block-submission behavior.

The top toolbar now includes a **Theme** control with ten persistent presets:

- Purple — original Bitcoin Miner Studio holographic look;
- Graphite — neutral grey;
- Obsidian — black / monochrome;
- Frost — true light/white presentation;
- Sapphire — blue;
- Crimson — red;
- Emerald — green;
- Cyan — electric cyan/teal;
- Amber — gold/orange;
- Rose — pink.

The selected preset is stored as the non-sensitive `ui_theme` setting and is
restored on the next launch.

Theme variables drive the application shell, glass panels, navigation,
holographic borders, 3D buttons, form controls, glows, status accents and
canvas charts. Monitoring and live hashrate charts read the active CSS palette
instead of using fixed purple values.

Unsupported/corrupted theme values safely fall back to Purple.

### Frost / white theme

Frost is not merely a grey accent on the dark UI. It switches to light surfaces,
dark typography, lighter shadows, adjusted borders, light result panels, and a
light RC readiness ring while preserving contrast.

### Safety boundary

Theme changes are cosmetic only. They cannot start mining, modify pool/ASIC
settings, change payout addresses, alter Bitcoin Core, bypass Purple Dragon
security, or submit blocks.


## v0.9.0.3 — Theme Studio Overlay Hotfix

Fixes Theme Studio opening underneath Dashboard/other glass panels.

The root cause was CSS stacking contexts created by `backdrop-filter`. Even
though the Theme Studio popover had its own `z-index`, it was trapped inside
the topbar stacking context while later page glass panels could paint above
that entire context.

The hotfix gives the toolbar an explicit overlay layer and keeps the page
content below it:

- topbar: layer 500;
- top actions: layer 510;
- Theme picker: layer 520;
- Theme Studio popover: layer 1000;
- active views/cards: layer 1.

The content/topbar/theme-picker containers also explicitly allow visible
overflow so the menu cannot be clipped as it expands below the toolbar.

This is cosmetic UI layering only; no mining, pool, Bitcoin Core, ASIC,
security, payout, or block-submission behavior changed.


## v0.9.0.4 — Project Support / PayPal Donation

A new **Support the Project** card appears in the sidebar.

Selecting it opens:

`the fixed configured PayPal.me support endpoint`

in the user's default external browser.

The donation button follows the active Theme Studio palette and is kept
separate from mining, Pool, Bitcoin Core, ASIC, wallet, payout, Monitoring,
and Purple Dragon controls.

### External-link boundary

The WebView does not pass a URL into Python. The signed backend method accepts
no URL argument and opens one fixed PayPal.me destination only. This prevents
the donation bridge from becoming a general-purpose arbitrary URL launcher.

Donations are optional and do not unlock features, improve hashrate, change
Miner XP, affect mining priority, or alter Release Candidate readiness.


## v1.0.0 — Stable Release

Bitcoin Miner Studio is now on the **Stable** release channel.

v1.0.0 intentionally promotes the hardened v0.9.0.4 golden Release Candidate
without introducing a new mining protocol or mining engine.

The Release Candidate workspace is now presented as **Release Readiness**, and
a clean build reports:

`STABLE READY · 100/100 · 0 blockers`

### Maintenance policy

The v1.0.x line is maintenance-focused: bug fixes, compatibility, security,
performance regressions, packaging, diagnostics and UI/accessibility polish.

Major post-stable features such as the Mining Assistant, profitability center
and broader compatibility work belong in v1.1+.

### Packaging helpers

- `package_portable.bat` creates a clean portable source ZIP on Windows.
- `package_pyinstaller.bat` provides an optional executable-build path when
  PyInstaller is already installed on the packaging machine.
- neither helper downloads dependencies or silently installs software;
- executable/installer code signing remains a separate publisher-controlled
  release step using a trusted certificate.

See `CHANGELOG.md`, `STABLE_RELEASE.md` and `RELEASE_CHECKLIST.md`.


## v1.0.1 — Official App Icon

The approved Purple Dragon holding a Bitcoin coin is now the official icon.

- `assets/BitcoinMinerStudio.png`
- `assets/BitcoinMinerStudio.ico`

The source Windows launcher applies the ICO to the pywebview window, and
`package_pyinstaller.bat` embeds the same ICO into a packaged executable.


## v1.1.0 — Mining Assistant

Mining Assistant adds a dedicated beginner-oriented **Can I Mine?** workspace
with six guided goals and local readiness cards for CPU benchmarking, Pool,
Bitcoin Core, authorized ASICs, solo prerequisites and Purple Dragon trust.

It is advisory only. It never starts mining, launches LAN discovery, changes a
pool, controls an ASIC, changes Bitcoin Core, changes payout configuration, or
submits a block by itself.


## v1.1.0.1 — Mining Assistant Polish Hotfix

This maintenance update fixes the Recommended Path renderer, makes the hero
status follow the selected goal, and improves the Windows CPU model display.

Examples:

- Pool Mining → `SETUP NEEDED` or `CONFIGURED`
- Bitcoin Core → `SYNCED`, `SYNCING`, `DETECTED` or `NOT DETECTED`
- Solo Mining → `PREPARED` or `SETUP NEEDED`

No mining-control behavior changed.


## v1.2.0 — Profitability & Power Center

The new local calculator estimates expected mining production and power economics
from user-provided hardware and market assumptions.

Inputs include hashrate, watts, electricity rate, pool fee, BTC price, network
difficulty, block subsidy and optional average transaction fees per block.

When Bitcoin Core is connected, **Use Bitcoin Core** fills the local chain
height, difficulty and consensus block subsidy. BTC price remains a manual
input; Miner Studio does not phone home to a market-price service.

Outputs are estimates only and are not promises of profit.


## v1.3.0 — Hardware Compatibility Center

The Hardware Compatibility Center explains **why** Miner Studio recognizes a
device and which capabilities are actually available from current evidence.

Compatibility levels:

- **Verified Runtime** — ASIC API evidence plus a recognized family;
- **Supported Family** — recognized ASIC-family Web UI, with privileged controls still gated;
- **Generic / Limited** — ASIC-specific API evidence without confident model-family mapping;
- **Not Promoted** — no positive ASIC evidence.

The built-in registry recognizes Antminer/Bitmain, WhatsMiner/MicroBT,
Avalon/Canaan and generic cgminer-compatible ASIC evidence. Exact firmware
behavior can vary, so pool control/restart/telemetry are enabled only when the
device itself proves those capabilities at runtime.

The Center is read-only and performs no discovery scan or hardware changes.


## v1.3.0.1 — Hardware Compatibility Hotfix

Fixes a pywebview bridge serialization issue where Hardware Compatibility family
examples could arrive in JavaScript as a non-array value. The backend now emits
JSON-safe lists and the UI defensively normalizes the value before rendering.

ASIC discovery, compatibility evidence rules and device-control permissions are
unchanged.


## v1.3.0.2 — Bitcoin Core Data-Dir Reliability

Miner Studio now treats the configured Bitcoin data directory as a pinned node
identity rather than a best-effort hint.

`Start Bitcoin Core` always launches the node with an explicit:

`-datadir=<configured folder>`

If the configured directory is missing, Miner Studio stops instead of silently
allowing Bitcoin Core to create/use its default Windows profile directory.

The Core Setup Assistant also reports a **Data-Dir Guard** state:

- `READY` — no Core process is running; the next launch is pinned;
- `MATCH` — running Core explicitly uses the pinned folder;
- `LIKELY MATCH` — Bitcoin-Qt's saved Windows folder matches;
- `MISMATCH` — a running Core instance uses another folder;
- `UNVERIFIED RUNNING` — a running Core folder cannot be proved;
- `UNCONFIGURED` — choose a data folder before launching.

This specifically prevents accidental second blockchain syncs when the intended
node data already exists on another drive.


## v1.3.0.3 — Global Dropdown Theme Hotfix

Native WebView2 dropdown popups are now explicitly themed at the control and
option level. Dark themes use opaque dark option surfaces and readable light
text; Frost uses an explicit light popup with dark text.

This applies globally to every native `<select>` rather than patching individual
pages.


## v1.3.0.4 — Publisher Branding

Bitcoin Miner Studio is created and published by **Purple Dragon Foundation ltd**. The Windows
application identity, signed Purple Dragon provenance, sidebar credit,
executable metadata and default mining coinbase tags use the Foundation brand.

The donation action still uses the existing fixed PayPal routing endpoint, but
the personal payment handle is not used as creator/publisher branding.


## v1.3.0.5 — Foundation Visual Branding

The official Purple Dragon Foundation ltd banner and logo artwork are now
integrated directly into the Miner Studio interface.

- Foundation logo: sidebar publisher mark and support surface;
- Foundation banner: Purple Dragon Security Center;
- Foundation logo: Security Center publisher identity header.

The Bitcoin/dragon Miner Studio artwork remains the application icon. The
Foundation images are protected by the signed Purple Dragon release manifest.


## v1.4.0 — Pool Profiles & Smart Failover

Pool Profiles provide reusable local Stratum configurations without putting pool
passwords in JSON settings or profile files. Each profile can contain a primary
endpoint, up to three backups, worker identity, fee assumption, watchdog,
mining-process settings and one of four failover policies.

Smart Failover policies:

- **Manual Only** — reconnect only to the selected endpoint;
- **Conservative** — two consecutive failures before moving to a backup;
- **Balanced** — switch after one confirmed failure and retry primary after 5 minutes;
- **Aggressive** — switch after one confirmed failure and retry primary after 1 minute.

Per-profile passwords use Windows Credential Manager on Windows. Sanitized
exports exclude both passwords and free-form profile notes.


## v1.4.0.1 — Foundation Asset Loading Hotfix

Purple Dragon Foundation images used by the WebView are now mirrored under `ui/assets/` and referenced without parent-directory traversal. This fixes broken-image placeholders in the sidebar, Support Purple Dragon card and Purple Dragon Security Center.


## v1.4.0.2 — Foundation Branding Layout

Small UI surfaces now show the emblem only. The Security Center uses a compact split header and restrained company banner. No supplied artwork is altered; the emblem presentation is a CSS crop of the protected original logo.


## v1.5.0 — Windows Tray & Background Monitoring

On Windows, Miner Studio can remain available in the notification area while the main window is hidden. The tray offers Open, Current Status, Hide Window and Exit only. Existing monitoring threads continue locally; the tray does not add remote control or mining-control shortcuts.

Default behavior: tray enabled, minimize-to-tray enabled, close button exits normally, health notifications enabled, 10-second status polling.
