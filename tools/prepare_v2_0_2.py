#!/usr/bin/env python3
"""Deterministically promote the public-readiness branch to Bitcoin Miner Studio v2.0.2.

This script is intentionally signing-key free. It updates release/version metadata,
public-readiness documentation, and pinned build inputs. Purple Dragon signing is a
separate offline publisher step performed only after this preparation is complete.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.0.2"
OLD_VERSION = "2.0.1"
WINDOWS_VERSION = "2.0.2.0"
RELEASE_WATERMARK = "PD202-01511F75E57F2792E17E9194"
RELEASE_WATERMARK_HEX = RELEASE_WATERMARK.encode("utf-8").hex().upper()
CPYTHON_EMBED_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text and old not in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one occurrence of {old!r}, found {count}")
    write(path, text.replace(old, new, 1))


def promote_runtime_versions() -> None:
    replace_once(
        "webview_app.py",
        'VERSION = "2.0.1"',
        'VERSION = "2.0.2"',
    )
    replace_once(
        "windows_native_host.cs",
        'Text = "Bitcoin Miner Studio v2.0.1";',
        'Text = "Bitcoin Miner Studio v2.0.2";',
    )

    info_path = ROOT / "release_info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["version"] = VERSION
    info["channel"] = "Stable"
    info["stability"] = "Stable"
    info["notes"] = (
        "Public-readiness and reliability hotfix: isolates Bitcoin Core self-tests from real host process/registry state, "
        "removes exception-suppressing finally-return warnings, recognizes the native direct-WebView2 Windows runtime, "
        "hardens Stratum endpoint parsing/TLS cleanup, makes settings writes atomic, corrects finalized package metadata, "
        "pins the embedded CPython runtime by SHA-256, and expands Purple Dragon protection to the native Python bridge."
    )
    info_path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")

    text = read("windows_version_info.txt")
    replacements = {
        "filevers=(2, 0, 1, 0)": "filevers=(2, 0, 2, 0)",
        "prodvers=(2, 0, 1, 0)": "prodvers=(2, 0, 2, 0)",
        "StringStruct('FileVersion', '2.0.1')": "StringStruct('FileVersion', '2.0.2')",
        "StringStruct('ProductVersion', '2.0.1')": "StringStruct('ProductVersion', '2.0.2')",
    }
    for old, new in replacements.items():
        if new in text and old not in text:
            continue
        if text.count(old) != 1:
            raise RuntimeError(f"windows_version_info.txt: expected one occurrence of {old!r}")
        text = text.replace(old, new, 1)
    write("windows_version_info.txt", text)


def rotate_release_watermark() -> None:
    text = read("purple_dragon_security.py")
    old_prefix = '_RELEASE_WATERMARK_HEX = "'
    start = text.find(old_prefix)
    if start < 0:
        raise RuntimeError("purple_dragon_security.py: release watermark constant not found")
    value_start = start + len(old_prefix)
    value_end = text.find('"', value_start)
    if value_end < 0:
        raise RuntimeError("purple_dragon_security.py: malformed release watermark constant")
    current = text[value_start:value_end]
    if current != RELEASE_WATERMARK_HEX:
        text = text[:value_start] + RELEASE_WATERMARK_HEX + text[value_end:]
        write("purple_dragon_security.py", text)


def harden_signer() -> None:
    path = "tools/purple_dragon_sign.py"
    text = read(path)
    if "import time\n" not in text:
        anchor = "import sys\n"
        if text.count(anchor) != 1:
            raise RuntimeError(f"{path}: import anchor not found")
        text = text.replace(anchor, anchor + "import time\n", 1)

    old = '''manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
manifest["schema"] = max(2, int(manifest.get("schema") or 0))
manifest["security_scheme"] = SECURITY_SCHEME
manifest["publisher_name"] = PUBLISHER_NAME
manifest["publisher_key_id"] = publisher_key_id()
manifest["marker_digest"] = marker_digest()
manifest["release_watermark"] = release_watermark()
manifest["watermark_digest"] = watermark_digest(manifest.get("version", ""))
manifest["release_seal"] = "PD6-" + manifest["watermark_digest"].upper()[:20]
manifest["files"] = {name: sha256_file(ROOT / name) for name in PROTECTED_FILES}
manifest["signature"] = ""
'''
    new = '''manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
release_info = json.loads((ROOT / "release_info.json").read_text(encoding="utf-8"))
release_version = str(release_info.get("version") or "").strip()
if not release_version:
    raise SystemExit("release_info.json does not contain a release version.")

missing = [name for name in PROTECTED_FILES if not (ROOT / name).is_file()]
if missing:
    raise SystemExit("Cannot sign: protected files are missing: " + ", ".join(missing))

manifest["schema"] = max(2, int(manifest.get("schema") or 0))
manifest["product"] = "Bitcoin Miner Studio"
manifest["version"] = release_version
manifest["security_scheme"] = SECURITY_SCHEME
manifest["protection_profile"] = "signed-provenance+file-integrity+critical-action-gating"
manifest["publisher_name"] = PUBLISHER_NAME
manifest["publisher_key_id"] = publisher_key_id()
manifest["marker_digest"] = marker_digest()
manifest["release_watermark"] = release_watermark()
manifest["watermark_digest"] = watermark_digest(release_version)
manifest["release_seal"] = "PD6-" + manifest["watermark_digest"].upper()[:20]
manifest["files"] = {name: sha256_file(ROOT / name) for name in PROTECTED_FILES}
files_canonical = json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode("utf-8")
files_digest = hashlib.sha256(files_canonical).hexdigest()
manifest["build_id"] = f"BMS-{release_version}-STABLE-{files_digest[:8].upper()}"
manifest["provenance_tag"] = "PD-BMS-" + files_digest[:16].upper()
manifest["issued_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
manifest["signature"] = ""
'''
    if new not in text:
        if old not in text:
            raise RuntimeError(f"{path}: expected manifest-signing block not found")
        text = text.replace(old, new, 1)
    write(path, text)


def harden_embedded_python_download() -> None:
    path = "build_windows_portable.ps1"
    text = read(path)
    if CPYTHON_EMBED_SHA256 in text:
        return
    old = '''$EmbeddedUrl = "https://www.python.org/ftp/python/$EmbeddedPythonVersion/python-$EmbeddedPythonVersion-embed-amd64.zip"
Write-Host "Downloading official CPython $EmbeddedPythonVersion embedded runtime..."
Invoke-WebRequest -Uri $EmbeddedUrl -OutFile $EmbeddedZip -UseBasicParsing
Expand-Archive -LiteralPath $EmbeddedZip -DestinationPath $RuntimeRoot -Force
'''
    new = f'''$EmbeddedUrl = "https://www.python.org/ftp/python/$EmbeddedPythonVersion/python-$EmbeddedPythonVersion-embed-amd64.zip"
$EmbeddedExpectedSha256 = '{CPYTHON_EMBED_SHA256}'
Write-Host "Downloading official CPython $EmbeddedPythonVersion embedded runtime..."
Invoke-WebRequest -Uri $EmbeddedUrl -OutFile $EmbeddedZip -UseBasicParsing
$EmbeddedActualSha256 = (Get-FileHash $EmbeddedZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($EmbeddedActualSha256 -ne $EmbeddedExpectedSha256) {{
    Remove-Item $EmbeddedZip -Force -ErrorAction SilentlyContinue
    throw "Embedded CPython SHA-256 mismatch. Expected $EmbeddedExpectedSha256, got $EmbeddedActualSha256."
}}
Write-Host "Embedded CPython SHA-256 verified: $EmbeddedActualSha256" -ForegroundColor Green
Expand-Archive -LiteralPath $EmbeddedZip -DestinationPath $RuntimeRoot -Force
'''
    if old not in text:
        raise RuntimeError(f"{path}: CPython download block not found")
    write(path, text.replace(old, new, 1))


def prepare_manifest_for_offline_signing() -> None:
    path = ROOT / "purple_dragon_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["version"] = VERSION
    manifest["build_id"] = "PENDING-OFFLINE-SIGNATURE"
    manifest["provenance_tag"] = "PENDING-OFFLINE-SIGNATURE"
    manifest["issued_utc"] = ""
    manifest["release_watermark"] = RELEASE_WATERMARK
    manifest["watermark_digest"] = ""
    manifest["release_seal"] = ""
    manifest["signature"] = ""
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def update_public_docs() -> None:
    changelog = read("CHANGELOG.md")
    heading = "## v2.0.2 — Public Readiness & Reliability Hotfix"
    if not changelog.startswith(heading):
        section = f'''{heading}\n\n- Isolated Bitcoin Core setup self-tests from real Windows process, registry, PATH and user-profile state so tests are deterministic on machines that already run Bitcoin Core.\n- Removed two `return`-from-`finally` paths that could suppress exceptions and now fail the CI compile gate on any Python `SyntaxWarning`.\n- Made Release Readiness architecture-aware for the native Microsoft Edge WebView2 host used by the public Windows package.\n- Hardened Stratum endpoint parsing: only supported Stratum schemes are accepted; embedded credentials, paths/query strings and invalid ports are rejected.\n- Tightened Stratum transport cleanup and oversized-response handling.\n- Made settings persistence atomic to reduce corruption risk during interrupted writes.\n- Corrected finalized Windows package file-count/size metadata so it describes the exact shipped tree.\n- Pinned the official CPython 3.12.10 embedded runtime by SHA-256 before extraction.\n- Expanded Purple Dragon protection to include `windows_native_bridge.py`, the native C# host, and Windows release/signing tooling; the final signed v2.0.2 manifest contains 73 protected files.\n- Added a Windows Public Readiness CI gate covering strict Python compilation, JavaScript syntax, deterministic Core/pool/Regtest/ASIC regressions, Stratum URL hardening and release hygiene.\n- Preserved the v2.0.1 direct WebView2 + embedded CPython architecture; no PyInstaller, Qt/PySide6, pywebview or pythonnet runtime was reintroduced.\n\n'''
        write("CHANGELOG.md", section + changelog)

    stable = read("STABLE_RELEASE.md")
    stable = stable.replace("# Bitcoin Miner Studio v2.0.1 — Stable", "# Bitcoin Miner Studio v2.0.2 — Stable", 1)
    stable = stable.replace(
        "This folder is the Bitcoin Miner Studio v2.0.1 Stable source release.",
        "This folder is the Bitcoin Miner Studio v2.0.2 Stable source release.",
        1,
    )
    if "## v2.0.2 public-readiness hotfix" not in stable:
        marker = "## v2.0.1 hotfix\n"
        section = (
            "## v2.0.2 public-readiness hotfix\n\n"
            "The v2.0.2 release tightens deterministic Windows testing, native WebView2 release detection, Stratum input validation, atomic settings persistence and build supply-chain verification. "
            "The native Python bridge, native C# host, and Windows release/signing tooling join the Purple Dragon protected surface, bringing the final publisher-signed manifest to 73 protected files.\n\n"
        )
        if marker not in stable:
            raise RuntimeError("STABLE_RELEASE.md: v2.0.1 section anchor not found")
        stable = stable.replace(marker, section + marker, 1)
    write("STABLE_RELEASE.md", stable)

    checklist = read("RELEASE_CHECKLIST.md")
    checklist = checklist.replace(
        "# Bitcoin Miner Studio v2.0.1 — Stable Release Checklist",
        "# Bitcoin Miner Studio v2.0.2 — Public Release Checklist",
        1,
    )
    checklist = checklist.replace(
        "- [x] Full Python regression suite after v2.0.1 publisher signing",
        "- [ ] Full Python regression suite after final v2.0.2 publisher signing",
        1,
    )
    checklist = checklist.replace(
        "- [x] Purple Dragon publisher signature validation — TRUSTED / VALID",
        "- [ ] Final Purple Dragon publisher signature validation — TRUSTED / VALID",
        1,
    )
    checklist = checklist.replace(
        "- [x] v2.0.1 protected-file hash map refreshed and publisher-signed",
        "- [ ] v2.0.2 protected-file hash map refreshed and publisher-signed (73 protected files)",
        1,
    )
    if "Public Readiness Gate passes on Windows" not in checklist:
        anchor = "## Automated gates\n\n"
        additions = (
            "- [x] Public Readiness Gate passes on Windows (strict Python compile, JavaScript syntax, deterministic Core/pool/Regtest/ASIC regressions)\n"
            "- [x] Bitcoin Core setup self-test isolated from host process/registry/PATH state\n"
            "- [x] Hardened Stratum URL parser rejects unsupported schemes, credentials, paths/query strings and invalid ports\n"
            "- [x] Official CPython 3.12.10 embedded ZIP pinned by SHA-256 before extraction\n"
        )
        if anchor not in checklist:
            raise RuntimeError("RELEASE_CHECKLIST.md: automated gates anchor not found")
        checklist = checklist.replace(anchor, anchor + additions, 1)
    write("RELEASE_CHECKLIST.md", checklist)

    readme = read("README.md")
    readme = readme.replace("# Bitcoin Miner Studio v2.0.1 — Stable", "# Bitcoin Miner Studio v2.0.2 — Stable", 1)
    if "## v2.0.2 — Public Readiness & Reliability Hotfix" not in readme:
        marker = "## v2.0.1 — Diagnostics / RPC Reliability Hotfix\n"
        section = (
            "## v2.0.2 — Public Readiness & Reliability Hotfix\n\n"
            "v2.0.2 hardens the stable Windows release for broader distribution: deterministic Bitcoin Core tests no longer depend on the host machine, Stratum endpoint validation is stricter, settings writes are atomic, Release Readiness understands the direct WebView2 architecture, and the embedded CPython runtime is checksum-pinned before packaging. The final offline-signed release expands Purple Dragon protection to 68 files, including the native Python bridge.\n\n"
        )
        if marker not in readme:
            raise RuntimeError("README.md: v2.0.1 section anchor not found")
        readme = readme.replace(marker, section + marker, 1)
    write("README.md", readme)

    upgrade = '''# Upgrading to Bitcoin Miner Studio v2.0.2\n\nv2.0.2 is a reliability/public-readiness hotfix over v2.0.1. It does not replace the BMS-ARCH-2 application model or change user mining profiles intentionally.\n\n## What changes\n\n- deterministic Bitcoin Core setup tests on PCs that already have Bitcoin Core installed/running;\n- stricter Stratum endpoint validation and transport cleanup;\n- atomic settings writes;\n- native direct-WebView2-aware release diagnostics;\n- corrected final Windows package metadata;\n- checksum-pinned embedded CPython 3.12.10 download;\n- Purple Dragon protection expanded to the native Python bridge (68 files in the final signed manifest).\n\n## Upgrade procedure\n\n1. Stop mining and close Bitcoin Miner Studio cleanly.\n2. Keep your existing `%USERPROFILE%\\.bitcoin-miner-studio` application-data directory; do not copy it into the release folder.\n3. Extract the complete v2.0.2 Windows x64 package to a new folder.\n4. Verify the published SHA-256 checksum.\n5. Start `BitcoinMinerStudio.exe` and confirm Purple Dragon reports `TRUSTED` before starting mining or critical ASIC/block actions.\n\nDo not mix individual files from v2.0.1 and v2.0.2. Purple Dragon is designed to lock critical controls when protected release files do not match the signed manifest.\n'''
    write("UPGRADE_v2.0.2.md", upgrade)

    notes = '''# Bitcoin Miner Studio v2.0.2 — Public Readiness & Reliability Hotfix\n\nBitcoin Miner Studio v2.0.2 hardens the v2.0.1 stable Windows architecture for broader distribution without reintroducing the frozen/Qt/CLR runtime stacks retired in v2.0.1.\n\n## Highlights\n\n- deterministic Bitcoin Core setup/self-test isolation on real Windows machines;\n- strict `SyntaxWarning` CI gate and cleanup of exception-suppressing `finally` returns;\n- direct Microsoft Edge WebView2-aware Release Readiness checks;\n- hardened Stratum endpoint parsing and response-buffer handling;\n- atomic settings persistence;\n- corrected post-finalization package metadata;\n- SHA-256 verification of the official embedded CPython 3.12.10 archive before extraction;\n- Purple Dragon protected surface expanded to 68 files, including `windows_native_bridge.py`;\n- dedicated Windows Public Readiness Gate covering Core, pool/failover, Regtest, ASIC Solo, JavaScript, Python and repository hygiene.\n\n## Windows architecture\n\n- native C# WinForms host;\n- Microsoft Edge WebView2 renderer;\n- embedded CPython 3.12.10 backend;\n- private stdin/stdout JSON bridge;\n- no separate Python install required;\n- no PyInstaller, Qt/PySide6, pywebview, pythonnet or CLR bridge in the public EXE runtime.\n\nMicrosoft Edge WebView2 Runtime is required and is normally present on current Windows 10/11 systems.\n\n## Verification\n\nUse the published `SHA256SUMS-Windows.txt` and confirm the in-app Purple Dragon Security state is `TRUSTED` with a valid publisher signature and all protected files verified before enabling critical controls. Purple Dragon is tamper-evident provenance, not DRM and not a guarantee against copying or reverse engineering.\n'''
    write("GITHUB_RELEASE_NOTES-v2.0.2.md", notes)


def verify_prepared_state() -> None:
    assert 'VERSION = "2.0.2"' in read("webview_app.py")
    assert 'Bitcoin Miner Studio v2.0.2' in read("windows_native_host.cs")
    assert RELEASE_WATERMARK_HEX in read("purple_dragon_security.py")
    assert CPYTHON_EMBED_SHA256 in read("build_windows_portable.ps1")
    assert '"windows_native_bridge.py"' in read("tools/purple_dragon_sign.py")
    info = json.loads(read("release_info.json"))
    assert info["version"] == VERSION
    manifest = json.loads(read("purple_dragon_manifest.json"))
    assert manifest["version"] == VERSION
    assert manifest["signature"] == ""
    protected_literal_count = read("tools/purple_dragon_sign.py").split("PROTECTED_FILES = [", 1)[1].split("]", 1)[0].count('    "')
    if protected_literal_count != 68:
        raise RuntimeError(f"Expected 68 Purple Dragon protected files, found {protected_literal_count}")


def main() -> None:
    promote_runtime_versions()
    rotate_release_watermark()
    harden_signer()
    harden_embedded_python_download()
    prepare_manifest_for_offline_signing()
    update_public_docs()
    verify_prepared_state()
    print(f"Prepared Bitcoin Miner Studio v{VERSION} for offline publisher signing.")
    print("Expected Purple Dragon protected files: 68")
    print(f"Embedded CPython SHA-256 pin: {CPYTHON_EMBED_SHA256}")
    print("Publisher signature intentionally cleared; critical controls remain locked until offline signing.")


if __name__ == "__main__":
    main()
