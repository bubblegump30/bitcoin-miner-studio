# v2.0.3 — Post-Release Reliability & Support (development)

Branch: `release/v2.0.3-reliability-support`.

Baseline: `aecc2ea1a94ea916839bc7ba94e9834670bf1098`, the signed source
identified by the published v2.0.2 Windows release. This intentionally does
not use the older v2.0.2 tag or import the separate Setup & Profile QoL line.
The repository already contains a v2.0.3 tag for that other line. The owner
explicitly requested retaining this milestone/branch name and preserving all
existing tags. Resolve the final publication identifier before releasing;
never move either existing tag or overwrite its assets.

## Initial implementation

- Damaged JSON, invalid root values, non-finite JSON numbers and invalid UTF-8
  recover to fresh defaults after moving original bytes to a unique local
  `settings.corrupt-<id>.json`. These files may contain private data and must
  not be uploaded or placed in support bundles. If preservation fails, saving
  refuses to overwrite the original. Known setting types are validated before
  consumers use them, and mutable defaults are copied independently.
- Settings saves use unique temporary files in the same directory, flush and
  fsync before atomic replacement, and remove failed temporary writes.
- Support sanitization now traverses dictionaries inside nested lists and
  strips additional secret-key spellings. Text redaction handles quoted
  passwords with spaces, URL credentials, bearer tokens and PEM private keys.
  Free text redaction is best effort; review generated bundles before sharing.
- Supplied checksums must contain exactly 64 hexadecimal characters and apply
  to package files. Folder inspection cannot silently ignore a checksum.
- Native startup bounds WebView2 initialization, reports safe error type and
  HRESULT diagnostics under LocalAppData, and stops the backend on failure.
  Unexpected backend exit is handled even when its exit code is zero.
- A session-scoped mutex prevents concurrent native hosts across extracted
  folders; abandoned ownership is recoverable after a crash. Smoke tests have
  a separate identity. A second launch tells the user how to restore the first.
- Native minimize, close and backend hide requests require a visible tray
  icon. Disabling the tray restores a hidden window.

## Validation and release gates

Run `python -m unittest discover -s tests -p test_reliability.py -v`.
The new read-only CI workflow runs these tests on Python 3.12 x64 Windows.
Tests use temporary directories and do not read user settings or start mining.

Local evidence on 2026-11-07:

- Nine new Python regressions and four existing Node preset tests passed.
- Existing release/support, diagnostics/support, tray/background, preflight
  cleanup and startup DOM regression groups passed.
- Native host compiled with the pinned WebView2 SDK and .NET Framework C#
  compiler. One existing unused-field warning remains (`_navigationReady`).
- Full selftest stops at the publisher integrity assertion, as expected for
  edited protected source. The release-folder regression likewise rejects the
  unsigned development tree. These gates were not bypassed.

The existing signing key, verifier, manifest, release metadata and publishing
workflows are preserved. The signer list includes the new Python test file so
the existing unsigned-code rejection remains enforceable. No private key is
required for development. This tree remains intentionally untrusted until a
publisher signs the finalized source using an appropriately versioned helper.
It is not a release candidate and must not be packaged as a trusted release.

Remaining acceptance work before release:

1. Exercise the native host on embedded Python 3.12 with missing/broken/slow
   WebView2, abrupt backend exit, repeated launch, crash/relaunch, session exit,
   tray toggles, Explorer restart and active background tasks.
2. Extend recovery evidence into the visible Diagnostics UI; validate malformed
   setting ranges and persisted workspace/profile/session state recovery.
3. Exercise both actual ZIP support bundle entry sets against adversarial
   nested and free-text fixtures, interrupted writes and disk-full failures.
4. Finalize the version/publication identity, prepare branch-specific signing
   tooling without changing historical helpers, sign offline, then run the full
   signed regression suite and Windows package smoke test.
5. Verify final archive checksum, embedded runtime, manifest coverage and
   publisher trust from extracted release bytes before any publication.
