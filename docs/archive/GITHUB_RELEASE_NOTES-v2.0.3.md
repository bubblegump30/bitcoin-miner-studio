# Bitcoin Miner Studio v2.0.3 — Setup & Profile QoL

The signed Windows x64 build improves the Pool Profile Center with clearer connection examples, a precise preview of preset changes, value-preserving Custom selection, and field-specific validation before saving.

BTC PoW Lab joins the optional catalog as a Hybrid Solo preset. Applying it changes only the primary public Stratum endpoint. The worker/wallet, password, backup endpoints, failover settings, and ordinary fee assumption remain as entered. The preset explains the published 85% finder / 10% Community / 5% infrastructure allocation, the absence of block payout history reported by the operator, and the current limitation on automatic Community payout broadcasting. The app's generic fee estimate cannot represent hybrid rewards; review the provider's current terms before mining. No pool is endorsed or selected automatically.

The publisher-signed Purple Dragon manifest verifies 74 protected files. The signed Windows release candidate passed the full Python regression suite, JavaScript checks, package build/smoke test, and final metadata validation. The public Stratum endpoint responded to a one-time subscribe probe without a wallet or worker; worker authorization and payouts were not verified by that probe.

Extract the ZIP into a new folder, check its SHA-256 against `SHA256SUMS-Windows.txt`, run `BitcoinMinerStudio.exe`, and confirm **TRUSTED · 74/74** in Purple Dragon Security. Microsoft Edge WebView2 Runtime is required. The EXE does not have a Microsoft Authenticode signature.

Pool documentation: https://github.com/bubblegump30/bitcoin-miner-studio/blob/v2.0.3/docs/POOL_PRESETS.md
