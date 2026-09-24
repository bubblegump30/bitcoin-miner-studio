## Summary

Describe what changed and why.

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] UI/UX change
- [ ] Mining or hardware behavior
- [ ] Performance/reliability improvement
- [ ] Architecture/refactor
- [ ] Documentation
- [ ] Build/release change

## Affected areas

List the Bitcoin Miner Studio components, mining modes, services, or files affected by this pull request.

## Validation

Check the validation you performed:

- [ ] `python selftest.py`
- [ ] Application startup/manual smoke test
- [ ] Mining-mode-specific test where applicable
- [ ] Release/integrity verification where applicable
- [ ] Windows release build verification where applicable

Documentation-only pull requests may mark unrelated runtime checks as not applicable.

## Mining safety and user control

- [ ] No wallet private keys, seed phrases, RPC passwords, pool credentials, API tokens, or signing keys are included.
- [ ] The change does not silently start mining.
- [ ] The change does not redirect payout addresses or mining work.
- [ ] Potentially destructive ASIC, process, filesystem, networking, or Bitcoin Core actions remain explicit and reviewable.
- [ ] Relevant guidance in `MINING_SAFETY.md` remains accurate.

## Release integrity and security

- [ ] Publisher-signature and protected-file verification are not weakened.
- [ ] The offline publisher private key is not included or exposed.
- [ ] SHA-256/release-trust checks are preserved where applicable.
- [ ] Release-hygiene gates are not silently bypassed.
- [ ] Sensitive diagnostics are sanitized.

## UI changes

If this changes the interface, include before/after screenshots and confirm that the result remains consistent with the Purple Dragon UI/UX.

## Release impact

Describe any packaging, update, migration, compatibility, provenance, or signing implications.

## Checklist

- [ ] The change is focused and does not include unrelated refactoring.
- [ ] Documentation was updated when behavior changed.
- [ ] I reviewed the final diff for accidental files, secrets, private keys, and generated build output.
- [ ] The change is ready for maintainer review.
