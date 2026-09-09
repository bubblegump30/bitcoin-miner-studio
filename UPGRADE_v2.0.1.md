# Upgrade to Bitcoin Miner Studio v2.0.1

Upgrade from v2.0.0 by replacing the complete application folder with the signed v2.0.1 release. Do not copy individual protected files across versions.

## Fixed

- Diagnostics no longer creates a false ATTENTION state by counting its own `0 failure(s)` summary messages.
- Isolated background Bitcoin Core RPC timeouts no longer make a healthy node briefly appear Offline when a last-known-good snapshot is available.
- Isolated background getblocktemplate timeouts preserve the last-known-good template for display while stale age continues to advance.
- Manual refreshes still report timeout errors explicitly.
- Existing three-consecutive-template-failure stale-work shutdown behavior remains active for Solo Mining and ASIC Solo Bridge.

## Verification

Run `verify_build_integrity.bat` after extraction. The release must report TRUSTED, publisher signature VALID, and all protected files verified before using critical controls.
