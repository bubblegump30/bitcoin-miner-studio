# v2.0.3 — Post-Release Reliability & Support

Branch: `release/v2.0.3-reliability-support`.

Baseline: `aecc2ea1a94ea916839bc7ba94e9834670bf1098`, the signed source identified by the published v2.0.2 Windows release. This does not import the separate Setup & Profile QoL line. The owner requested retaining this milestone and branch name while preserving all existing tags. The existing v2.0.3 tag refers to that other line. This reliability candidate is distinguished by branch, commit, signed build ID and checksum. Do not move historical tags or replace their assets.

## Implemented behavior

- Strict finite JSON parsing and validation recover invalid settings types, ranges, device lists and interrupted local-pool restore data before startup consumers use them. Original bytes are preserved in a unique local recovery file; preservation failure blocks writes. Session-sticky recovery evidence is visible in Diagnostics. Mutable defaults are independently copied.
- Workspaces recover invalid history/preferences/command usage, and profiles preserve damaged storage before recovery. Settings, workspaces, profiles, session markers and update history share durable atomic JSON writes using unique temporary files, flush/fsync and replacement. Malformed or non-boolean session markers cannot falsely report a clean shutdown.
- Native startup has a session-scoped single-instance mutex, abandoned-owner recovery, separate smoke-test identity, bounded WebView2 and overall startup, safe early assembly-load errors, and renderer/backend failure handling. A second launch directs the user to the existing window/tray.
- Hide/minimize/close-to-tray require an available icon. Disabling the tray restores a hidden window. Background monitor generations own separate cancellation events so restarting cannot reactivate a slow stopped generation.
- Diagnostics recognizes native WinForms/WebView2 packaging without requiring legacy GUI imports. Production startup diagnostics go to LocalAppData; smoke-test diagnostics and browser state stay in the isolated fixture.
- Both support paths sanitize every JSON/text archive entry, including nested lists, quoted passwords, URL credentials, bearer tokens and PEM keys. Known logs are bounded; symlink logs, recovery files and analytics databases are excluded. Unique ZIPs are published atomically; write failure leaves no advertised partial archive. Free-text redaction remains best effort: review bundles before sharing.
- Supplied checksums require 64 hexadecimal characters and a package file. Inaccessible package inspection returns a blocked result. Folder staging revalidates copied signature/files and the originally inspected manifest, rejecting changed folders and removing partial staging.
- CPython 3.12.10 and WebView2 SDK 1.0.4191.47 archives are pinned by SHA-256. Native WinForms + WebView2 + embedded Python, the offline publisher identity and critical-action verification policy remain intact.

## Validation

Run the new tests with `python -m unittest discover -s tests -p test_reliability.py -v`.
Run the existing development groups with `python -u tests/run_development_regressions.py`.
Run native lifecycle checks with `tests/run_native_reliability.ps1`, supplying the verified SDK and a scratch output directory.
Run all signed groups with `python -W error::SyntaxWarning selftest.py` after fresh publisher signing.

The development runner runs 44 existing groups and explicitly reports three publisher-signature-dependent groups as pending. It never patches keys, verifiers, manifests or assertions. Full signed acceptance runs all 47 groups. The new suite contains 21 failure-path regressions.

Evidence before signing on 2026-11-07:

- 44 existing development groups, 21 new Python tests and four Node preset tests passed. Loopback integration tests required access outside the restricted network sandbox and used isolated simulated servers/settings.
- The native .NET Framework harness passed eight lifecycle assertions, including separate-process mutex ownership, second launch, abandoned ownership, missing runtime, close-to-tray and disposal. Native compilation is clean.
- The real WinForms/WebView2/embedded Python 3.12.10 fixture passed clean startup, settings/workspace/profile corruption recovery, tampered-bridge rejection, missing Python, abrupt backend termination and successful relaunch.
- Missing WebView2 Core or WinForms assemblies produced controlled failure. The SDK still started without the standalone loader DLL on this machine; this does not establish support for incomplete packages.
- Both actual support ZIP paths passed nested/text privacy fixtures, archive checks, collision avoidance and simulated disk-full cleanup.

## Signing and packaging

`sign_reliability_release.ps1` requires a clean reviewed branch and the existing publisher key outside the repository. The signer supports a private PEM/key or the existing publisher-key ZIP, reading its private entry only in memory. It checks public-key identity before signing. The helper verifies trust and complete protected coverage before committing the manifest. It does not create tags or publish assets. Historical signing helpers remain unchanged.

The new signed-candidate workflow requires fresh publisher trust, runs all signed selftests and new regressions, builds/finalizes the native package and uploads candidate artifacts for review. The development workflow separately runs strict compilation, development groups, new regressions and the native lifecycle harness. No private key enters CI.

Final signed-suite, package and checksum results must be recorded with the candidate commit/build ID. A prior signature or development smoke test does not replace those gates.

## Remaining manual coverage

Explorer restart, Windows logoff/shutdown, machine-wide WebView2 uninstall/repair, long-running sleep/resume and active production mining/hardware sessions have not been exercised by isolated checks. No live pool, wallet, ASIC or Bitcoin Core settings were used. Retain these limits when reporting readiness. A public release needs a distinct publication identity because the original v2.0.3 tag is occupied.


## Final native-runtime seal

Extracted-package acceptance found that third-party runtime Python modules were outside the source-only signature. Native distributions now require a separate `purple_dragon_runtime.json` signed by the same offline publisher key and bound to the exact source-manifest hash. It authenticates the embedded Python, native EXE, WebView2 libraries, Python dependencies and runtime bytecode. Unexpected runtime code, forged inventories, changed source bindings and tampered runtime files block inspection/staging. Native critical actions stay locked until this final seal is present and valid. The host disables bytecode writes to keep sealed runtime bytes stable.

CI produces a source-signed build input, without any private key. After downloading and verifying its artifact digest, the publisher runs `python tools/sign_runtime_inventory.py <extracted-distribution> <external-key-or-key-zip>` offline. Final archive/checksum metadata is generated only after this seal and extracted-package verification. The private key stays outside the repository and is never uploaded to CI. The source verifier and distribution verifier report their distinct coverage counts.
