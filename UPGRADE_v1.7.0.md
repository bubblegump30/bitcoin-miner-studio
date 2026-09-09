# Bitcoin Miner Studio v1.7.0 — Mining Academy Upgrade

This release upgrades the complete v1.6.0 Benchmark Lab 2.0 codebase in place. Existing assets, configuration, benchmark history and other local application data are preserved.

## v1.7.0 additions

- Mining Academy navigation workspace
- 12 beginner/intermediate/advanced lessons
- Local lesson progress, quiz state, Academy XP and ranks
- Hash Explorer (SHA-256 / SHA-256d)
- Difficulty & Target Visualizer
- 80-byte Block Header Lab with Bitcoin genesis-header defaults
- Merkle Tree Lab
- Educational Nonce Mining Simulator
- Contextual Learn This links from Benchmark Lab and Profitability & Power Center
- `academy_progress.json` local persistence
- Purple Dragon protection for `mining_academy.py`

## Safety boundary

Mining Academy has no wallet, credential, ASIC-control, live-mining, state-changing Bitcoin Core RPC, pool-connection or block-submission controls.
