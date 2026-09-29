# Bitcoin Miner Studio

A local-first Windows x64 workspace for SHA-256d CPU benchmarking, pool mining, Bitcoin Core integration, authorized ASIC monitoring, diagnostics, and mining education. Published by **Purple Dragon Foundation ltd**.

## Download v2.0.3

[Windows x64 ZIP](https://github.com/bubblegump30/bitcoin-miner-studio/releases/download/v2.0.3/BitcoinMinerStudio-v2.0.3-Windows-x64.zip) · [SHA-256 checksums](https://github.com/bubblegump30/bitcoin-miner-studio/releases/download/v2.0.3/SHA256SUMS-Windows.txt) · [Release notes](https://github.com/bubblegump30/bitcoin-miner-studio/releases/tag/v2.0.3)

1. Compare the ZIP's SHA-256 with `SHA256SUMS-Windows.txt` (expected: `b1aab4ee20a42ff44b719eff81cf29e1399f96b24332e8121a343216230a88af`).
2. Extract it into a new folder and run `BitcoinMinerStudio.exe` on Windows 10/11 x64. Microsoft Edge WebView2 Runtime is required; Python is included.
3. Open **Purple Dragon Security** and confirm **TRUSTED · 74/74 protected files** before using critical mining controls.

The EXE has no Microsoft Authenticode signature. The Purple Dragon manifest is publisher-signed and checks the protected files; the ZIP checksum checks the downloaded archive.

## What's in the app

- **Mining and profiles:** local SHA-256d CPU mining, Stratum pool profiles, backups and failover, connection tests, and ASIC monitoring.
- **Bitcoin Core:** node dashboard, setup assistance, and controlled solo-mining tools.
- **Tools:** local benchmark lab, Mining Academy, diagnostics and sanitized support bundles, and signed-package inspection in Update & Release Center.
- **v2.0.3 setup improvements:** clearer pool fields, a preview of preset changes, Custom selection that keeps edits, and field-specific validation before saving.

Optional presets include Braiins Pool, CKPool Solo, and BTC PoW Lab. Selecting a preset only previews it; applying BTC PoW Lab changes the primary endpoint while leaving worker, password, backups, failover, and the ordinary fee assumption as entered. Its 85/10/5 hybrid reward allocation cannot be represented by the generic fee estimate. Review [preset sources and limitations](docs/POOL_PRESETS.md) and current provider terms before mining. No pool is selected or endorsed automatically.

## Guides and project information

- [Complete v2.0.3 user guide](docs/USER_GUIDE.md) — setup, profiles, testing, mining, and troubleshooting
- [Pool preset documentation](docs/POOL_PRESETS.md) · [Mining safety](MINING_SAFETY.md) · [Changelog](CHANGELOG.md)
- [Historical project notes](docs/README_HISTORY.md) — detailed older feature and design descriptions
- [Purple Dragon Foundation website](https://www.purpledragonfoundationltd.xyz/) · [Support the project](https://www.paypal.com/paypalme/KyleAustin85)

Mining rewards and profit are never guaranteed. Pool access, compatibility, and payout terms depend on the provider. The app does not silently start mining, download updates, or upload support bundles.
