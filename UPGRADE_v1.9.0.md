# Bitcoin Miner Studio v1.9.0 — Update & Release Center Upgrade

Upgrade from v1.8.0 by replacing the application source folder with the **complete signed v1.9.0 release**. Preserve user data under `.bitcoin-miner-studio`; do not merge individual protected source files between signed versions.

## v1.9.0 additions

- Update & Release Center
- `.7z` / `.zip` / extracted-folder candidate inspection
- optional package SHA-256 verification
- Purple Dragon candidate publisher-signature + protected-file verification
- Stable / Preview update-channel policy
- trusted local staging
- rollback-plan metadata
- local update history
- public release-descriptor export
- integrated Stable Release Readiness

## Safety model

The center does not execute candidate code, perform background update downloads, or replace the running Bitcoin Miner Studio folder. A package must verify as a trusted Purple Dragon release before staging. Applying or rolling back a release remains an explicit offline operation after Bitcoin Miner Studio is closed.

## User data

Existing settings, Benchmark Lab history, Mining Academy progress, Analytics data, Pool Profiles, Diagnostics support artifacts and other app-data remain under the existing `.bitcoin-miner-studio` location.

## Security

Use the complete signed v1.9.0 folder. Any post-signing change to a protected file causes Purple Dragon trust verification to fail until the intended build is regenerated and re-signed by the publisher.
