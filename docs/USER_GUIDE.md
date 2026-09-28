# Bitcoin Miner Studio v2.0.3 — User Guide

Bitcoin Miner Studio is a Windows x64 workspace for SHA-256d CPU benchmarking and pool mining, authorized ASIC monitoring, Bitcoin Core integration, diagnostics, and mining education. This guide covers the current v2.0.3 release. Pool terms and endpoints can change; check a provider's current documentation before connecting.

## 1. Download and install

1. Download `BitcoinMinerStudio-v2.0.3-Windows-x64.zip` and `SHA256SUMS-Windows.txt` from the [v2.0.3 release](https://github.com/bubblegump30/bitcoin-miner-studio/releases/tag/v2.0.3).
2. In PowerShell, from the download folder, run:

   ```powershell
   Get-FileHash .\BitcoinMinerStudio-v2.0.3-Windows-x64.zip -Algorithm SHA256
   ```

3. Compare the result with the release checksum file. The published ZIP hash for v2.0.3 is `b1aab4ee20a42ff44b719eff81cf29e1399f96b24332e8121a343216230a88af` (letter case does not matter). If it differs, download the ZIP again from the official release.
4. Extract the ZIP into its own folder, then run `BitcoinMinerStudio.exe` from the extracted folder. Do not run it from inside the ZIP. Python is bundled; the Microsoft Edge WebView2 Runtime is required on Windows 10/11.
5. The EXE does not have a Microsoft Authenticode signature. Verify the published ZIP checksum and open **Purple Dragon** in the app. The official v2.0.3 release should show **TRUSTED** and **74/74 protected files** before you use critical mining controls.

## 2. Learn the workspace

| Area | Use it for |
| --- | --- |
| **Dashboard** | Current hashrate, shares, uptime, pool/job information, health, and quick actions. |
| **Benchmark Lab** | Local CPU SHA-256d runs and worker scaling without a pool or wallet. |
| **Mining Assistant** | Guided readiness advice for benchmark, pool, ASIC, Bitcoin Core, and solo goals. |
| **Profitability & Power** | Estimate revenue and electricity costs from your own assumptions. |
| **Pool PowerTools** | Pool endpoints, worker identity, profiles, failover, and connection tests. |
| **ASIC Control** | Authorized private-network device inventory and telemetry. |
| **Hardware Compatibility** | Understand recognized ASIC families and available capabilities. |
| **Bitcoin Core** | Configure and monitor your own Bitcoin Core node. |
| **Monitoring** and **Logs** | Inspect trends, status changes, and errors. |
| **Tray & Background** | Configure notification-area and window behavior. |
| **Diagnostics & Support** | Run health checks and generate a local, sanitized support bundle. |
| **Mining Academy** | Learn proof-of-work concepts through lessons and local labs. |
| **Purple Dragon** | Check package integrity and publisher signature. |
| **Update & Release** | Inspect and stage a downloaded release package. |

You can press **Ctrl+K** to open the Command Palette for navigation and supported utility actions. The **Theme** control changes appearance only. **Performance+** can reduce interface overhead during longer sessions.

**Mining Assistant** can guide a first-time setup, but it does not start mining or change configuration for you. **Mining Academy** includes lessons and local labs on SHA-256d, difficulty, block headers, Merkle trees, and nonces. These are good places to learn the terms before configuring a live pool.

## 3. Run a local benchmark

Open **Benchmark Lab**, select a timed preset and worker count, then click **Start Timed Run**. The presets are Quick (10 seconds), Standard (30 seconds), Sustained (60 seconds), and Stress (2 minutes). Start with Standard and a modest worker count. Review current, average, and peak hashrate, stability, total hashes, and BMS Score.

BMS Score is for comparing this PC with its own previous runs, not a universal CPU ranking. **Worker Scaling Test** compares different worker counts so you can see whether additional workers help. Mining and benchmarking can sustain high CPU load; monitor temperatures and stop if the computer becomes unstable or exceeds its hardware limits.

## 4. Try the local test pool

From **Dashboard**, start **Local Test Pool**, then click **Start Mining**. This exercises the Stratum mining workflow on the local machine without using a public pool or a payout address. Watch the Dashboard and Logs for connection, job, and share activity. Click **Stop Mining** when finished, and stop the local test pool before moving to a public endpoint. The local test workflow is isolated from the normal pool configuration.

## 5. Configure a public mining pool

Open **Pool PowerTools**. Enter the values required by your chosen pool:

| Field | What to enter |
| --- | --- |
| **Primary endpoint** | A documented Stratum URL such as `stratum+tcp://POOL-HOST:PORT` or, if supported by the pool, `stratum+ssl://POOL-HOST:PORT`. Do not put credentials in the URL. |
| **Worker / Wallet** | The pool's required public identity, such as `account.worker1` or a public Bitcoin receiving address plus worker suffix. |
| **Password** | Only the pool's Stratum password, if required. Some providers document `x`. |
| **Backup endpoints** | Up to three endpoints you choose. Check that each accepts the configured worker identity. |
| **Mining Processes** | The number of CPU mining workers; use Worker Scaling Test to choose a practical count. |
| **Failover policy** | Manual Only, Conservative, Balanced, or Aggressive, depending on how quickly you want configured backups used after a failure. |
| **Pool fee assumption** | The fee used for ordinary profitability estimates; confirm it against the provider's current terms. |

Never enter a wallet seed phrase, private key, or recovery phrase. Bitcoin Miner Studio does not need one to mine. Confirm the payout identity before starting, as pool payouts may be irreversible.

### Optional pool presets

The v2.0.3 editor offers **Custom**, **Braiins Pool**, **BTC PoW Lab**, and **CKPool Solo**. Choosing a provider shows a preview. Acknowledging and clicking **Apply to editor** changes only the documented primary endpoint and, for conventional fee models, the editable fee assumption. It does not save, test, activate, connect, or start mining. Your worker, password, backup endpoints, and failover settings stay as entered. **Custom** leaves your current edits intact.

BTC PoW Lab has a hybrid reward allocation (85% finder, 10% eligible Community, 5% infrastructure). Its preset changes the primary endpoint but leaves the ordinary fee assumption alone: a standard pool fee estimate cannot model its hybrid rewards. Its published Community payout terms have additional limitations. Review [pool preset sources and limitations](POOL_PRESETS.md) and the provider's current terms before using any preset. The software does not endorse a provider or guarantee its availability, compatibility, or payouts.

### Save, test, activate, start

1. Review the endpoint, worker identity, password, backups, fee assumption, and failover policy.
2. Enter a profile name and click **Save Profile**. Correct any validation errors shown in the editor.
3. Click **Test Profile**. **This tests the saved profile**, so save again after any edits before retesting.
4. When the saved configuration is ready, click **Activate**. Activation alone does not start mining.
5. Check **Purple Dragon** for **TRUSTED**, then click **Start Mining** in Pool PowerTools or on the Dashboard.

The connection should progress through subscription, worker authorization, receiving jobs, hashing, and share submission. On the Dashboard, watch hashrate, accepted/rejected shares, difficulty, uptime, current job, and active workers. Click **Stop Mining** to end the session before making substantial configuration or hardware changes.

CPU SHA-256d mining is useful for learning and testing, but modern Bitcoin mainnet mining is dominated by specialized ASICs. Do not assume a desktop CPU will generate meaningful profit. The **Profitability & Power** page offers estimates based on values you provide; electricity rates, difficulty, price, hardware efficiency, downtime, and pool payout rules affect real outcomes.

## 6. Optional integrations

### ASIC Control

Add or discover only devices you own or are authorized to administer on your private network. **ASIC Control** can remember known devices, refresh telemetry, show health and availability, and retain local notes. Supported controls depend on capability evidence from the device; review a device and confirm any restart or pool change explicitly. **Hardware Compatibility** explains the recognized family and available capabilities.

### Bitcoin Core

Configure the node's RPC connection in **Bitcoin Core**, then use **Test Bitcoin Core** to check authentication and connectivity. The page shows chain synchronization, height, peers, difficulty, network information, and node health. The app stores RPC passwords through its credential backend rather than ordinary settings JSON.

Bitcoin Core solo mining and block submission require a properly configured, synchronized node and careful review of the proposed work. Learn the benchmark, local test pool, and standard pool workflows first. A valid share at pool difficulty is not the same as finding a Bitcoin block.

### Monitoring and background behavior

Use **Monitoring** to inspect session and system trends and **Logs** to investigate connection, authorization, rejection, failover, or security events. **Tray & Background** configures Windows notification-area behavior; hiding the window does not automatically stop an active session. Use **Stop Mining** when you intend to end one.

## 7. Troubleshooting

| Symptom | Check |
| --- | --- |
| Interface will not open | Extract the ZIP fully and ensure Microsoft Edge WebView2 Runtime is installed. |
| Mining controls are unavailable | Check **Purple Dragon** for a valid publisher signature and **TRUSTED**, with all 74 v2.0.3 protected files verified. |
| Pool URL is rejected | Use a supported `stratum+tcp://` or `stratum+ssl://` host and port, without embedded credentials or query strings. |
| Test Profile uses old values | Click **Save Profile** after editing, then run **Test Profile** again. |
| Worker authorization fails | Compare the worker identity and password with the provider's current instructions; see **Logs**. |
| No accepted shares | Check endpoint, authorization, connection state, share difficulty, hardware compatibility, and **Logs**. Shares may take time at low hashrate. |
| High temperature or instability | Stop mining or benchmarking, reduce workers, and inspect cooling and the system's safe operating limits. |
| Bitcoin Core connection fails | Use **Test Bitcoin Core** and review RPC credentials, node state, configured data directory, and the reported error category. |

Use **Diagnostics & Support** for Quick or Full health scans. A support bundle is created locally and sanitizes sensitive material; it is not uploaded automatically. Review any bundle yourself before sharing it in an issue. **Update & Release** can verify a downloaded package's checksum, Purple Dragon signature, protected-file hashes, version, and channel policy before staging; it does not silently replace the running app.

## First-session checklist

1. Download the [official release](https://github.com/bubblegump30/bitcoin-miner-studio/releases) and verify its checksum.
2. Extract and launch; confirm **Purple Dragon → TRUSTED**.
3. Run a Standard benchmark and optionally a Worker Scaling Test.
4. Try **Local Test Pool**, then stop the local session.
5. Read **Mining Academy** and configure a pool according to its current documentation.
6. **Save Profile → Test Profile → Activate → Start Mining**.
7. Monitor the Dashboard and Logs; stop if the system is unstable.

For the publisher and its other projects, visit the [Purple Dragon Foundation website](https://www.purpledragonfoundationltd.xyz/).

For more detail, see [Mining Safety](../MINING_SAFETY.md), [Pool Presets](POOL_PRESETS.md), and the [project README](../README.md). Bitcoin Miner Studio does not guarantee mining rewards, profit, pool availability, or hardware compatibility.
