# Bitcoin Miner Studio — CPU Mining Tutorial

This tutorial walks through using **Bitcoin Miner Studio** on a Windows PC for CPU-based SHA-256d mining tests and real Stratum pool connectivity.

> **Important:** Bitcoin mainnet mining is dominated by ASIC hardware. A desktop CPU can perform valid SHA-256d work and may submit valid pool shares, but expected Bitcoin earnings are generally negligible compared with electricity usage. Treat CPU mining primarily as a learning, testing, and validation workflow.

## 1. Before you start

Make sure:

- Bitcoin Miner Studio launches normally.
- Purple Dragon security reports the build as trusted before using critical mining controls.
- Your PC has adequate cooling and airflow.
- You are prepared to monitor CPU temperature and system responsiveness.
- You have a Bitcoin wallet receive address if your chosen pool requires one.

### Security rule

Only use a **public Bitcoin receive address** where required.

Never enter any of the following into Bitcoin Miner Studio, a mining pool, or a support request:

- wallet seed phrase
- mnemonic
- private key
- wallet backup secret

## 2. Benchmark the CPU first

Open:

**Bitcoin Miner Studio → Benchmark Lab 2.0**

Run a CPU benchmark for approximately **5–10 minutes**.

Record:

- CPU model
- logical thread count
- average SHA-256d hashrate
- peak hashrate
- stability result
- CPU temperature, if available

The benchmark gives you a baseline before connecting to a real pool.

## 3. Choose a safe starting worker count

Do not begin real mining with every logical CPU thread.

A reasonable first test is approximately **50–75% of available logical threads**.

Examples:

| Logical threads | Suggested first test |
| ---: | ---: |
| 4 | 2–3 workers |
| 8 | 4–6 workers |
| 12 | 6–9 workers |
| 16 | 8–12 workers |
| 24 | 12–18 workers |
| 32 | 16–24 workers |

Bitcoin Miner Studio currently supports up to **64 CPU mining workers**.

Increase the worker count only after checking temperatures, system responsiveness, and stability.

## 4. Test the Stratum path locally

Before connecting to a real mining pool, use the built-in **Local Test Pool**.

This validates the complete mining path without involving real Bitcoin:

```text
Bitcoin Miner Studio
        ↓
Local Stratum connection
        ↓
Worker authorization
        ↓
Mining job
        ↓
CPU SHA-256d hashing
        ↓
Share submission
        ↓
Accepted / rejected result
```

Confirm that Bitcoin Miner Studio can start hashing and process share responses correctly.

## 5. Prepare a real mining pool

For real pool mining, obtain the current configuration directly from the mining pool you choose.

You normally need:

- Stratum hostname
- Stratum port
- worker or wallet name
- worker password, if required
- payout configuration on the pool account

A typical Bitcoin Miner Studio configuration looks like:

```text
Pool URL:     stratum+tcp://POOL_HOST:PORT
Worker:       your-wallet-or-account.worker1
Password:     x
CPU Workers:  start around 50–75% of logical threads
Difficulty:   Auto/default initially
```

Some pools use account-based workers, while others may use a wallet address in the worker field. Follow the pool's current documentation.

Bitcoin Miner Studio requires a valid pool URL and worker identity before starting. If no password is required, the miner can use the conventional value `x`.

## 6. Run Pool PowerTools diagnostics

Open:

**Mining Assistant → Pool Mining → Pool PowerTools**

Before starting a real session, use the available endpoint diagnostics.

Verify that:

- DNS resolves correctly
- the Stratum endpoint is reachable
- the port accepts a connection
- TLS is used when the selected endpoint requires it
- authorization succeeds

Do not start a long mining session until the endpoint checks are clean.

## 7. Start a short real mining session

Start with a short test session using the worker count chosen earlier.

A healthy Stratum startup sequence should look similar to:

```text
Connecting
→ Subscribing
→ Authorized
→ mining.notify received
→ Hashing
→ Share submitted
→ ACCEPTED
```

Bitcoin Miner Studio tracks operational mining telemetry including:

- hashrate
- accepted shares
- rejected shares
- stale shares
- submitted shares
- connection latency
- difficulty changes
- reconnects
- failover events
- best share difficulty

The important confirmation is that the miner is not merely hashing locally — it must also receive pool work and successfully submit shares.

## 8. Watch temperatures and responsiveness

During the first real session:

- monitor CPU temperature
- confirm cooling remains stable
- make sure the PC remains responsive
- check for thermal throttling
- check accepted/rejected/stale share ratios

If temperatures are too high or the PC becomes sluggish, stop the session and reduce the worker count.

## 9. Do not force share difficulty initially

Bitcoin Miner Studio can request a specific Stratum share difficulty, but the pool may ignore or reject that request.

For the first real session, leave suggested difficulty on **Auto/default** unless the pool specifically documents a recommended setting for low-hashrate workers.

## 10. CPU mining expectations

A normal Windows desktop CPU is useful for:

- validating Bitcoin Miner Studio's mining engine
- testing Stratum connectivity
- learning how Bitcoin pool mining works
- comparing CPU performance
- testing accepted/rejected/stale share handling
- experimenting before buying an ASIC

It is **not competitive with modern Bitcoin ASIC hardware** for mainnet mining profitability.

For serious Bitcoin mining, Bitcoin Miner Studio's ASIC workflows are the intended next step.

## 11. Pool mining vs. solo mining

### Pool mining

Recommended for initial real-world testing.

Bitcoin Core is not required for normal external Stratum pool mining.

### Solo mining

Bitcoin Miner Studio also contains guarded solo-mining tools, but solo mining requires additional preparation, including:

- a synchronized Bitcoin Core node
- fresh block templates
- a valid public payout address
- trusted Purple Dragon build state

CPU solo mining on Bitcoin mainnet has extraordinarily low odds of finding a block and should be treated as educational unless using competitive ASIC hardware.

## 12. Troubleshooting

### Stuck on Connecting

Check:

- pool hostname
- pool port
- firewall rules
- internet connectivity
- whether the pool requires TLS

### Connected but not Authorized

Check:

- worker/account name
- wallet/worker format required by the pool
- worker password
- whether the pool account has been fully created

### Authorized but no work arrives

Bitcoin Miner Studio expects `mining.notify` work from the pool. If no job arrives, verify that the selected endpoint is an active Stratum mining endpoint rather than a web/API endpoint.

### Hashing but no accepted shares

Possible causes include:

- CPU hashrate is too low for the pool's current share difficulty
- incorrect worker configuration
- excessive latency
- stale work
- pool-side difficulty policy

Use Pool PowerTools diagnostics and the mining telemetry before changing settings.

### Too many rejected or stale shares

Check:

- network latency
- pool endpoint health
- system load
- whether the miner is frequently reconnecting
- whether the selected pool is appropriate for very low-hashrate CPU miners

## 13. Recommended first-session checklist

- [ ] Purple Dragon trust verified
- [ ] CPU benchmark completed
- [ ] CPU temperature checked
- [ ] Worker count set conservatively
- [ ] Local Test Pool completed successfully
- [ ] Public receive address prepared if required
- [ ] Real pool Stratum endpoint copied from official pool documentation
- [ ] Worker/account details configured
- [ ] Pool diagnostics passed
- [ ] Short real mining test started
- [ ] `Authorized` confirmed
- [ ] `mining.notify` received
- [ ] Hashing confirmed
- [ ] At least one accepted share observed, if pool difficulty allows
- [ ] Temperature and system responsiveness acceptable

---

**Publisher:** Purple Dragon Foundation ltd  
**Project:** Bitcoin Miner Studio  
**Tutorial scope:** Windows CPU mining, local Stratum validation, and real pool setup
