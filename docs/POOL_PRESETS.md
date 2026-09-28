# Optional pool presets

Implements the editor-only portion of issue #2. Choosing a preset previews it;
checking the replacement acknowledgement and clicking Apply to editor writes
the primary URL and, for conventional fee models, the editable fee assumption. No save, activation, connection,
mining start, credential write, or failover update occurs. Custom remains the
default. All existing manual controls remain available.

Worker formats and public password defaults are guidance only. They never replace
wallets, account names, worker identities, typed passwords, or stored credentials.
Existing backups are preserved: users must review whether those backups accept
the identity they intend to use with the new primary endpoint. The editor shares
its fields with explicit mining actions, so review before Start Mining as well as
before Save Profile. Test Profile operates on the saved profile, not unsaved edits.

In v2.0.3, the preview names the two values that Apply replaces. Switching to
Custom leaves all current edits intact. Save Profile checks the entered endpoint,
worker and fee fields and points to the first invalid field; errors do not copy
typed secrets into the validation message. Loading a saved profile refreshes the
preview after its fields are populated.

## Catalog review — 2026-09-28

| Entry | Endpoint | Model / fee assumption | Official sources |
| --- | --- | --- | --- |
| Braiins Pool | `stratum+tcp://stratum.braiins.com:3333` | FPPS / standard 2.5%; account discounts and payout fees may differ | https://academy.braiins.com/braiins-pool/btc-mining-setup and https://academy.braiins.com/braiins-pool/rewards-and-payouts |
| BTC PoW Lab | `stratum+tcp://stratum.btcpowlab-pool.com:3333` | Hybrid Solo / no ordinary fee assumption applied; 85% finder, 10% eligible Community, 5% infrastructure | https://btcpowlab-pool.com/start, https://btcpowlab-pool.com/community and https://btcpowlab-pool.com/terms |
| CKPool Solo | `stratum+tcp://stratum.ckpool.org:3333` | Solo / 2%; ordinary shares do not generate regular payouts | https://solo.ckpool.org/ |

All entries use the documented Stratum V1 TCP endpoint, without encryption.
Documentation review is not a live compatibility, availability, or payout audit.
Braiins documents ASIC support and excludes CPU/GPU support. No user account,
wallet address, or real password was used to verify these entries.

BTC PoW Lab is operated by Carlos Monzon / Power CM Software, who proposed the
entry and disclosed no paid-placement or referral arrangement. Its public guide
documents address.worker identity and public `x` password example; neither is
filled into user fields. The published 85/10/5 hybrid allocation is not a 5%
conventional pool fee. Applying this preset changes only the primary endpoint,
leaving the generic fee field as entered; the app's generic profitability estimate
cannot model hybrid finder and Community rewards. The operator reports no block
payout history as of this review. Its published terms say automatic Community
payout broadcasting is disabled; amounts enter payout processing after 100-block
maturity and are subject to the 546-sat minimum and terms. Users should consult
current pool terms before making decisions. External DNS was unavailable in the
local workspace. A one-time
GitHub Actions probe on 2026-09-28 confirmed the public Stratum V1 endpoint
responded to `mining.subscribe` without a wallet or worker. This does not verify
worker authorization, live mining, block finding, or payout behavior.

## Maintenance and release

- Apply the same documented inclusion criteria to every provider. Sort by name;
  never preselect a provider or add referral links, rankings, or sponsored labels.
- Review sources and dates before release; remove or defer unverifiable entries.
- Catalog lives in protected `ui/script.js`; no remote catalog or background probe.
- Run `node --test tests/pool_presets.test.cjs`, JavaScript syntax validation, and
  the existing WebView DOM and pool-profile regression checks.
- On Windows, verify keyboard selection, preview scrolling, acknowledgement reset,
  edit/apply/save/reload, explicit Test/Activate, and unchanged runtime/failover.
- Regenerate final protected-file hashes through the normal publisher signing
  process after review. Verify TRUSTED / VALID on the final package. This source
  change intentionally does not forge or replace the existing signed manifest;
  the old signature cannot validate modified UI files. No integrity bypass.

Do not close issue #2 as fully delivered until release validation is complete.
