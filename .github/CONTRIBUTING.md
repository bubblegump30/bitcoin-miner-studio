# Contributing to Bitcoin Miner Studio

Thank you for considering a contribution to Bitcoin Miner Studio.

Bitcoin Miner Studio is a Windows desktop toolkit for Bitcoin mining, benchmarking, diagnostics, ASIC management, Bitcoin Core integration, monitoring, and mining education. Contributions should preserve safety, release integrity, publisher provenance, and the established Purple Dragon interface.

## Development environment

Recommended development environment:

- Windows 10 or Windows 11 x64
- Python 3.12 x64 for Windows release-build work
- Python 3.11 or later for supported source workflows
- Git
- PowerShell

Install Python dependencies from the repository root:

```powershell
python -m pip install -r requirements.txt
```

The source/developer launcher is:

```powershell
.\run.bat
```

## Required validation

Before opening a pull request for code changes, run the relevant project checks.

At minimum:

```powershell
python selftest.py
```

When release or protected-source integrity is affected, also use the repository's release verification and integrity tooling, including the applicable scripts documented in `RELEASE_CHECKLIST.md`, `STABLE_RELEASE.md`, and `WINDOWS_BUILD.md`.

For Windows release-container changes, validate the native WebView2 + embedded CPython build path documented in `WINDOWS_BUILD.md`.

Documentation-only pull requests do not need unrelated mining, runtime, or packaging tests.

## Contribution guidelines

- Keep each pull request focused on one logical change.
- Explain what changed and why.
- Include the testing you performed.
- Include screenshots for meaningful UI changes.
- Note compatibility, mining-safety, privilege, networking, release, or security implications when relevant.
- Avoid unrelated refactoring in feature and bug-fix pull requests.
- Update documentation when behavior changes.
- Preserve Purple Dragon Foundation ltd publisher identity and the established UI/UX unless a change explicitly targets branding.
- Prefer root-cause fixes over temporary patches.
- Do not replace real telemetry or mining state with decorative or fabricated values.

## Mining and wallet safety

Bitcoin Miner Studio can interact with mining hardware, Bitcoin Core, Stratum endpoints, payout addresses, and system resources.

Contributions must therefore follow these rules:

- Never commit wallet private keys, seed phrases, RPC passwords, API keys, access tokens, signing keys, or other secrets.
- Never hard-code a developer or contributor payout address into a user-facing mining flow.
- Preserve explicit user control over payout addresses and mining endpoints.
- Do not silently start mining, alter payout destinations, or redirect mining work.
- Keep potentially destructive ASIC, process, filesystem, networking, or Bitcoin Core actions explicit and reviewable.
- Preserve safety controls documented in `MINING_SAFETY.md`.
- Treat real-mainnet behavior differently from regtest/test workflows where the project already does so.

## Release integrity and publisher trust

Bitcoin Miner Studio uses signed provenance and protected-file integrity checks.

Do not:

- weaken publisher-signature verification;
- bypass protected-file integrity checks;
- commit or expose the offline publisher private key;
- silently disable release-hygiene gates;
- weaken SHA-256 verification or release trust checks;
- remove provenance or publisher identity from release artifacts without explicit maintainer approval.

Release-related changes require extra review because they can affect every distributed build.

## Bug reports

Use the repository issue forms when possible.

A useful bug report should include:

- Bitcoin Miner Studio version
- Windows version and architecture
- build/runtime type
- affected mining mode or project area
- clear reproduction steps
- expected behavior
- observed behavior
- sanitized logs or screenshots when useful

Do not include secrets, private keys, seed phrases, RPC credentials, pool credentials, or sensitive system information.

## Pull requests

Before submitting a pull request:

- base the branch on the current default branch;
- verify the application starts when your change affects runtime behavior;
- run the relevant validation described above;
- review the diff for accidental files, credentials, private keys, build output, or unrelated edits;
- explain any changes to mining, payout, update, provenance, release, or security behavior;
- keep release-related changes especially narrow and well tested.

Maintainers may request revisions, additional testing, or a narrower scope before merging.

## Project documentation

Relevant project documents include:

- `README.md`
- `SECURITY.md`
- `MINING_SAFETY.md`
- `RELEASE_CHECKLIST.md`
- `STABLE_RELEASE.md`
- `WINDOWS_BUILD.md`
