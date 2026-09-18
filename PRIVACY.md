# Bitcoin Miner Studio Privacy

Bitcoin Miner Studio is designed as a local-first Windows application. Purple Dragon Foundation ltd does not operate an application telemetry service for Bitcoin Miner Studio v2.0.2.

## Local application data

Bitcoin Miner Studio may store local settings, workspace state, benchmark history, Mining Academy progress, monitoring/analytics data, pool-profile metadata, known ASIC device information, candidate archives, update staging metadata, and support/diagnostic artifacts under the current Windows user profile.

Operational analytics use a local SQLite database. Analytics are not uploaded automatically.

## Credentials and wallet safety

Pool and Bitcoin Core passwords are handled through the application's credential backend/session secret handling and are intentionally excluded from `settings.json`, sanitized pool-profile exports, and support bundles.

Bitcoin Miner Studio does not require a Bitcoin wallet seed phrase or private key for mining. Use a public payout/receive address only. Never enter a wallet seed phrase or private key into a pool configuration, support bundle, issue report, or project file.

## Network connections

Network activity occurs when the user enables or invokes features that require it, including:

- connections to user-configured Stratum mining pools;
- JSON-RPC connections to the user's configured Bitcoin Core node;
- private-LAN communication with ASIC devices the user owns or administers;
- opening fixed external project/support or official download pages in the user's default browser.

The built-in Local Test Pool is loopback-only. The ASIC Solo Bridge is restricted to private-LAN operation by design.

Bitcoin Miner Studio v2.0.2 does not include cloud telemetry, automatic support-bundle uploads, silent update downloads, advertising SDKs, or rotating third-party ad scripts.

## Support bundles and exports

Support bundles are created locally and are never uploaded automatically. The application is designed to exclude credential secrets, publisher private keys, wallet seeds/mnemonics, and the persistent analytics database. Operational identifiers and paths are sanitized/redacted where supported by the relevant export.

Before sharing any diagnostic file publicly, review it yourself for information you do not want to disclose.

## Publisher signing key

The Purple Dragon publisher private key is not part of the application or repository release. Release packages contain only the public verification material required to validate publisher provenance.

## Changes

Privacy-relevant behavior changes should be documented in the project changelog and release notes.
