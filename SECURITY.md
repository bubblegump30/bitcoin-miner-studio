# Purple Dragon Security

Publisher identity: **Purple Dragon Foundation ltd**.

Bitcoin Miner Studio uses a signed provenance/integrity layer called **Purple Dragon**.

## What it provides

The runtime contains only a publisher **public key**. The matching private key is
kept outside the application package. A signed manifest authenticates the build
and SHA-256 hashes critical Python/UI files. At startup, Bitcoin Miner Studio
verifies the publisher signature and file hashes in a background thread.

A hidden forensic marker is encoded into the runtime and represented by a
signed marker digest and build-specific provenance tag. The owner can run
`verify_build_integrity.bat` to retrieve the build ID and provenance tag.

The install fingerprint is a SHA-256 digest calculated locally from machine
attributes. Raw machine identifiers are not returned by the security module and
nothing is transmitted over the network. This is reserved for a future
publisher-signed license system.

## Limits

This is defense-in-depth, not a claim that desktop software is impossible to
reverse engineer. Raw Python source is inherently easier to modify than a
compiled executable. For commercial distribution, compile the release
(Nuitka/Cython), sign the Windows executable with an Authenticode certificate,
and require publisher-signed licenses. Never ship the publisher private key.

## v0.4.3 protected surface

The signed integrity manifest now also protects `coinbase_builder.py`, including payout validation and coinbase construction logic.


## v0.4.5 submission guards

`block_submission.py` is included in the Purple Dragon signed integrity set.
The WebView cannot pass arbitrary block hex to the submit path. `submitblock`
only receives the internally assembled candidate preserved after a local
SHA-256d result meets the live template target. Submission requires explicit
authorization and, by default, successful Bitcoin Core proposal validation.


v0.4.5.1 moves expensive block assembly/proposal/submission work to one serialized background worker. Submission authorization and target-valid candidate guards remain unchanged.


v0.4.5.2 Performance+ changes only local rendering/polling/batch behavior. It does not add stealth execution, persistence, remote control, or hidden mining, and all v0.4.5 submission guards remain unchanged.


v0.4.5.3 adds explicit separation between a non-target block-structure test and a real target-valid mining candidate. Proposal and submission UI controls require both candidate provenance and target validity; existing backend target/proposal/stale-work/authorization guards remain in force.


v0.4.5.4 is a dashboard-only layout change. Mining, RPC, candidate validation, Performance+, and submitblock security guards are unchanged.


v0.4.5.5 adds an in-app activity-log clear action only. It does not delete Bitcoin Core debug logs, candidate archives, fleet history, or other persistent diagnostic/security records.


## v0.4.6 Regtest Lab isolation

`regtest_lab.py` is included in the Purple Dragon signed integrity set.
The laboratory uses a dedicated data directory and loopback RPC port and does
not alter the user's configured mainnet node/data directory. P2P listening and
network discovery are disabled for the lab instance. Reset is scoped to the
dedicated lab directory and requires explicit UI authorization.


v0.4.6.1 fixes Regtest Lab lifecycle/UI state only. Isolation, dedicated data directory/RPC port, reset scoping, proposal validation, and submitblock guards are unchanged.


v0.4.6.2 defers security/RPC/filesystem background work until after the pywebview API bridge is live. This changes startup ordering only; Purple Dragon verification and all mining/submission isolation guards remain enabled.


v0.4.6.3 replaces whole-object js_api introspection with flat public window.expose wrappers. Private/nested backend objects remain outside the JavaScript API surface. Existing mining, submission, Purple Dragon and Regtest isolation safeguards are unchanged.


v0.4.6.4 replaces obsolete Regtest launch flags with -listen=0 and -networkactive=0 while preserving loopback-only RPC and the dedicated lab data directory. Mainnet state remains untouched.


## v0.4.7 stale-work safeguards

Solo Mining now rejects target-valid results when a newer chain-tip template
was queued during the active CPU batch. Such work is counted only as discarded
stale telemetry and is never promoted to the candidate/submission pipeline.

With automatic template switching enabled, three consecutive
`getblocktemplate` failures stop Solo Mining to avoid prolonged stale search.
All existing proposal, chain-tip, target-validation and explicit submitblock
authorization guards remain active.


## v0.5.0 ASIC Solo Mining boundary

The ASIC Solo Stratum listener can bind only to a literal private IPv4
interface. Wildcard/public/loopback live binds and non-private clients are
rejected. Starting the listener or changing a miner's pool requires explicit
ownership/administration authorization in the UI.

ASIC target-valid results do not bypass the existing submission controls. The
coinbase and 80-byte header are independently reconstructed, the full block is
assembled and target-checked again, the current Bitcoin Core chain tip is
checked, proposal mode is required by default, and `submitblock` still requires
explicit user authorization.

Automatic ASIC assignment never deletes existing pool entries.


## v0.5.0.1 ASIC discovery verification

Port availability and generic HTTP/HTTPS management interfaces are no longer
treated as sufficient ASIC evidence. Automatic fleet promotion requires either
a successfully parsed mining API response or an ASIC-vendor-specific Web UI
identity. This reduces accidental interaction with unrelated LAN devices.
Manual private-IP troubleshooting remains explicit and user initiated.


## v0.6.0 Purple Dragon Security

Purple Dragon v2 is an offline publisher-signature and file-integrity system.
The application embeds only the public RSA verification key; the publisher
private key is never shipped in a release.

If signature, manifest metadata, forensic watermark, or protected-file hashes
fail verification, Bitcoin Miner Studio enters **LOCKED** trust state. Critical
start/write/submission actions are denied by the Python backend itself, not only
by disabled HTML buttons. Stop and diagnostic controls remain usable.

The forensic marker is provenance evidence rather than a cryptographic secret.
Purple Dragon does not claim to make Python/desktop software impossible to
reverse engineer or copy.


## v0.6.1 Miner XP / Hash Hunt boundary

Hash Hunt is an isolated cosmetic browser-side mini-game. It performs a single
local double-SHA256 operation per user-triggered attempt but never receives a
Bitcoin Core block template and never calls the real pool-mining, CPU
solo-mining, ASIC Solo Bridge, ASIC write-control, block-assembly, proposal, or
`submitblock` APIs.

Miner XP is local UI state with no monetary or mining value. Users can reset or
modify that local progression without gaining real mining capability.

The HTML/CSS/JavaScript that implements the feature remains covered by the
Purple Dragon signed protected-file manifest.


## v0.7.0 Pool & Stratum PowerTools boundary

Pool failover is limited to endpoints explicitly configured in the Pool UI.
There is no automatic Internet-wide endpoint discovery.

Diagnostic and protocol-inspector output deliberately excludes Stratum
passwords. The worker identifier may be displayed because it is already
user-visible configuration; the password remains in the existing credential
backend/session secret.

Endpoint diagnostics are read-only pool protocol tests and run on a background
thread. Starting real pool mining remains protected by Purple Dragon
critical-action gating.

`pool_powertools.py` is part of the Purple Dragon signed protected-file set.


## v0.7.0.1 Security startup availability

Purple Dragon verification now has a lightweight state-only WebView bridge
endpoint and startup poll independent of the full dashboard snapshot. Critical
actions remain locked until signed-build verification actually completes; this
change only prevents unrelated UI rendering failures from hiding the completed
security state.


## v0.7.0.2 Local Test Pool lifecycle

The built-in Local Test Pool remains loopback-only. Its dynamically assigned
port is explicitly treated as ephemeral and is not considered a reusable
external pool identity across application restarts.

Multi-client support changes only concurrency inside the loopback validation
server; it does not expose the listener to LAN or public interfaces.


## v0.7.0.3 Local Test Pool form authority

When the built-in loopback Local Test Pool is active, its generated endpoint,
`local.worker1`, password `x`, empty backup list and disabled failover state are
authoritative for that local test session. This prevents stale WebView form
state from redirecting a local validation start to another endpoint or from
breaking the known local credential pair.


## v0.7.0.4 Windows child-process boundary

CPU hash workers are intentionally headless multiprocessing children. The
windowed launcher and main entrypoint both reject GUI startup outside Python's
`MainProcess`.

`launch.pyw`, `bootstrap.py`, and `miner_engine.py` are now covered by the
Purple Dragon protected-file manifest because launcher/process-boundary changes
can materially affect mining behavior and application integrity.


## v0.7.0.5 Diagnostic provenance

Endpoint diagnostic results are bound to the normalized endpoint set they were
generated from. Changing that set invalidates the previous result state so an
obsolete localhost or external-pool test cannot be presented as current.


## v0.8.0 Monitoring & Analytics data boundary

`analytics_monitor.py` uses a fixed credential-free SQLite schema. The recorder
accepts normalized operational counters/metrics only; it does not serialize the
full application configuration or Stratum/RPC request payloads.

Monitoring does not expose a network listener and makes no outbound telemetry
requests. CSV/JSON export is explicit and local. Clearing analytics deletes only
the analytics samples/events database and cannot delete Bitcoin Core chain data,
wallet data, Regtest data, or mining configuration.

`analytics_monitor.py` is covered by the Purple Dragon signed protected-file
manifest.


## v0.9.0 Release Candidate hardening

Release Candidate preflight and support-bundle creation are local
release-engineering features. They do not start mining, alter pool/ASIC/Core
configuration, submit blocks, or transmit telemetry.

### Support bundle privacy

Support bundles are never uploaded automatically. Password/secret fields are
omitted, worker/payout identifiers are redacted, home-directory paths are
normalized, Pool endpoint hostnames are redacted, and the persistent analytics
database is not included.

### Publisher-key gate

RC preflight scans the release root for PEM private-key material. Finding a
publisher private key is a blocking release failure.

### Protected release surface

The Purple Dragon manifest now additionally protects release-engineering and
launch artifacts including:
- `release_candidate.py`
- `release_info.json`
- `requirements.txt`
- `run.bat`
- `diagnose.bat`
- `verify_build_integrity.bat`
- `selftest.py`

This makes unauthorized modifications to the release/preflight/diagnostic
surface visible to the same signed provenance system protecting mining code.

### Self-test isolation

`selftest.py` redirects HOME/USERPROFILE to a temporary test profile before
Miner Studio modules are imported. Release validation cannot consume or mutate
the operator's production Miner Studio configuration or telemetry.


## v0.9.0.1 RC state normalization

Release preflight now distinguishes active Local Test Pool state from stale
ephemeral session metadata. Only inactive stale metadata is cleared. No pool
connection is started, stopped, redirected, or modified by this normalization.


## v0.9.0.2 Theme Studio boundary

`ui_theme` is a cosmetic, non-secret preference. Backend theme selection is
restricted to the signed preset registry and unsupported values normalize to
the Purple default. Theme switching does not invoke mining, ASIC, Bitcoin Core,
credential, payout, or submitblock APIs.

`ui_theme.py` and the HTML/CSS/JavaScript theme implementation are covered by
Purple Dragon release integrity.


## v0.9.0.3 Theme overlay isolation

The Theme Studio stacking fix changes presentation layers only. It does not
alter the backend theme whitelist or expose new application APIs. The popover
remains inside the signed UI surface protected by Purple Dragon.


## v0.9.0.4 PayPal donation link boundary

The project-support action opens one compile-time fixed HTTPS destination:
the fixed configured PayPal.me support endpoint.

`open_paypal_donation()` accepts no URL parameter. The WebView therefore cannot
use this action to navigate to arbitrary external destinations.

The donation action has no connection to mining authorization, credentials,
payout addresses, Purple Dragon trust, or critical-action gates.


## v1.0.0 Stable security baseline

The Stable release preserves the Release Candidate security boundaries:

- Purple Dragon signed provenance and protected-file verification;
- critical-action lockout on integrity failure;
- publisher private signing key excluded from the release;
- pool/RPC secrets excluded from settings and support bundles;
- Local Test Pool bound to loopback only;
- ASIC Solo Bridge restricted to explicit private-LAN operation;
- automatic block submission disabled;
- no cloud telemetry, automatic support upload, or silent auto-update.

The Windows packaging helpers are publisher-side conveniences. They do not
download packaging dependencies and do not claim to replace Authenticode code
signing.


## Mining Academy safety boundary

Mining Academy is an intentionally local educational subsystem. Its bridge methods expose curriculum state and deterministic learning labs only. The Academy module does not import or expose pool credentials, wallet access, ASIC control, live mining start/stop, state-changing Bitcoin Core RPC, or block submission. Progress is stored locally in `academy_progress.json`.

## v1.9.0 Update package verification

`update_release_center.py` is part of the Purple Dragon protected surface. Candidate releases are treated as untrusted input: the Update & Release Center does not import or execute candidate Python. It parses release metadata, verifies the publisher signature with the embedded public key, hashes every protected file listed in the candidate manifest, and rejects unsafe archive paths before extraction. Only a fully trusted candidate that passes channel policy can be staged. Staging copies files into local application data and records rollback metadata; it does not overwrite the running application. Automatic downloads and silent apply remain disabled.


## v2.0.0 BMS-ARCH-2 security boundary

Bitcoin Miner Studio v2 replaces implicit WebView reflection with **API contract schema 2**. Only methods listed in `api_contract.py` are exposed to the JavaScript bridge; adding an arbitrary public helper to `WebBackend` no longer exposes it automatically. Bridge construction fails closed if the signed contract references a missing backend method.

`app_runtime.py`, `app_events.py`, `service_registry.py`, `workspace_manager.py` and `api_contract.py` are part of the Purple Dragon protected executable surface. The local event bus is in-process and bounded; it has no network transport. Workspace state stores navigation/preferences only and contains no pool/RPC credentials or signing material.

Diagnostics schema 3 consumes a sanitized architecture-health snapshot. Support bundles include service identifiers/states but intentionally omit free-form service messages that could accidentally contain sensitive operational detail. The v2 UX Command Palette intentionally excludes direct start-mining, pool-switch, ASIC-control, Bitcoin Core mutation and block-submission commands.


## v2.0.1 Diagnostics / RPC reliability boundary

The v2.0.1 hotfix changes background monitoring semantics only. A single Bitcoin Core or getblocktemplate timeout may preserve the last-known-good UI snapshot, but explicit/manual refresh continues to expose the timeout. Preserved block-template snapshots retain their original fetch time and therefore become stale normally. Consecutive template failures still increment Solo Mining / ASIC Solo Bridge safety counters and can stop stale work after the existing threshold. Diagnostics now excludes its own summary entries and zero-count failure phrases from recent-error classification while continuing to flag genuine error/failure log entries. Purple Dragon verification remains mandatory for protected code and critical actions.
