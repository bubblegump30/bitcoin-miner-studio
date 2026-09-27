# Optional pool presets

Implements the editor-only portion of issue #2. Choosing a preset previews it;
checking the replacement acknowledgement and clicking Apply to editor writes only
the primary URL and editable fee assumption. No save, activation, connection,
mining start, credential write, or failover update occurs. Custom remains the
default. All existing manual controls remain available.

Worker formats and public password defaults are guidance only. They never replace
wallets, account names, worker identities, typed passwords, or stored credentials.
Existing backups are preserved: users must review whether those backups accept
the identity they intend to use with the new primary endpoint. The editor shares
its fields with explicit mining actions, so review before Start Mining as well as
before Save Profile. Test Profile operates on the saved profile, not unsaved edits.

## Catalog review — 2026-09-27

| Entry | Endpoint | Model / fee assumption | Official sources |
| --- | --- | --- | --- |
| Braiins Pool | `stratum+tcp://stratum.braiins.com:3333` | FPPS / standard 2.5%; account discounts and payout fees may differ | https://academy.braiins.com/braiins-pool/btc-mining-setup and https://academy.braiins.com/braiins-pool/rewards-and-payouts |
| CKPool Solo | `stratum+tcp://stratum.ckpool.org:3333` | Solo / 2%; ordinary shares do not generate regular payouts | https://solo.ckpool.org/ |

Both entries use the documented Stratum V1 TCP endpoint, without encryption.
Documentation review is not a live compatibility, availability, or payout audit.
Braiins documents ASIC support and excludes CPU/GPU support. No user account,
wallet address, or real password was used to verify these entries.

BTC PoW Lab is deferred, not rejected. The issue supplies an endpoint and discloses
that Carlos Monzon / Power CM Software operates the service, with no paid-placement
or referral arrangement claimed. Before inclusion, require official documentation
of protocol/transport, endpoint, authentication/worker format, fees, and exact
hybrid-solo reward allocation. Do not infer those values from the proposal or give
the service preferred placement. The feature does not depend on its inclusion.

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
