# Mining Safety and Financial Disclaimer

Bitcoin Miner Studio is a mining, benchmarking, diagnostics, hardware-management, and educational tool. It does not guarantee Bitcoin rewards, profitability, uptime, pool availability, or hardware compatibility.

## CPU mining

Bitcoin mainnet SHA-256 mining is dominated by specialized ASIC hardware. CPU mining on a normal Windows PC may be useful for learning, benchmarking, protocol validation, and low-scale experimentation, but it should not be treated as an expectation of meaningful profit.

CPU mining can create sustained processor load, increased power consumption, higher temperatures, fan noise, and additional wear. Monitor system temperatures and stability and stop mining if the computer becomes unstable or exceeds safe operating limits for its hardware.

## Electricity and profitability

Mining consumes electricity. Pool fees, network difficulty, Bitcoin price, hardware efficiency, downtime, taxes, and electricity rates can materially affect results. Profitability calculations in Bitcoin Miner Studio are estimates based on the values supplied to the application and are not financial advice.

## Wallets and payouts

Use only a public Bitcoin receive/payout address where requested. Bitcoin Miner Studio does not need a wallet seed phrase or private key to perform the supported mining workflows. Never disclose a seed phrase or private key to the application, a mining pool, an issue report, or a support bundle.

Confirm payout addresses and pool account/worker details before mining. Cryptocurrency transactions and mining payouts may be irreversible.

## Pools and third-party services

Mining pools and other third-party services are independent of Purple Dragon Foundation ltd. Their availability, terms, fees, payout rules, security, and behavior may change. Verify current pool documentation before connecting real mining hardware or expecting payouts.

## ASIC and network controls

Only discover, monitor, restart, or reconfigure ASIC devices that you own or are authorized to administer. Bitcoin Miner Studio intentionally restricts automatic ASIC discovery/control to private-network and verified-capability workflows, but the operator remains responsible for authorization and network safety.

## Bitcoin Core and block submission

Solo-mining and block-submission features depend on the user's own Bitcoin Core configuration and synchronization state. Target-valid candidate submission is guarded by integrity checks, chain-tip checks, proposal validation by default, and explicit user authorization. These safeguards reduce accidental submission risk but do not replace careful operator review.

## Release verification

Before enabling critical mining, ASIC, or block-submission controls, verify the published package checksum and confirm Purple Dragon reports `TRUSTED` with a valid publisher signature and all protected files verified.
