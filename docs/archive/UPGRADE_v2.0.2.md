# Upgrading to Bitcoin Miner Studio v2.0.2

v2.0.2 is a reliability/public-readiness hotfix over v2.0.1. It does not replace the BMS-ARCH-2 application model or change user mining profiles intentionally.

## What changes

- deterministic Bitcoin Core setup tests on PCs that already have Bitcoin Core installed/running;
- stricter Stratum endpoint validation and transport cleanup;
- atomic settings writes;
- native direct-WebView2-aware release diagnostics;
- corrected final Windows package metadata;
- checksum-pinned embedded CPython 3.12.10 download;
- Purple Dragon protection expanded to the native Python bridge (68 files in the final signed manifest).

## Upgrade procedure

1. Stop mining and close Bitcoin Miner Studio cleanly.
2. Keep your existing `%USERPROFILE%\.bitcoin-miner-studio` application-data directory; do not copy it into the release folder.
3. Extract the complete v2.0.2 Windows x64 package to a new folder.
4. Verify the published SHA-256 checksum.
5. Start `BitcoinMinerStudio.exe` and confirm Purple Dragon reports `TRUSTED` before starting mining or critical ASIC/block actions.

Do not mix individual files from v2.0.1 and v2.0.2. Purple Dragon is designed to lock critical controls when protected release files do not match the signed manifest.
