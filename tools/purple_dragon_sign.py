#!/usr/bin/env python
"""
Purple Dragon publisher signing tool.

The publisher PRIVATE key must never be included in a public release.
Usage:
    python tools\\purple_dragon_sign.py C:\\Secure\\PurpleDragon-Private-Key.pem
"""
import base64
import hashlib
import json
import sys
import time
from pathlib import Path

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except Exception:
    raise SystemExit("Install the developer dependency first: py -m pip install cryptography")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from purple_dragon_security import SECURITY_SCHEME, marker_digest, publisher_key_id, release_watermark, watermark_digest
from branding import PUBLISHER_NAME
MANIFEST = ROOT / "purple_dragon_manifest.json"

PROTECTED_FILES = [
    "main.py",
    "launch.pyw",
    "bootstrap.py",
    "legacy_main.py",
    "webview_app.py",
    "windows_native_bridge.py",
    "app_runtime.py",
    "app_events.py",
    "service_registry.py",
    "workspace_manager.py",
    "api_contract.py",
    "release_candidate.py",
    "release_info.json",
    "windows_version_info.txt",
    "CHANGELOG.md",
    "STABLE_RELEASE.md",
    "RELEASE_CHECKLIST.md",
    "coinbase_builder.py",
    "solo_miner.py",
    "block_submission.py",
    "regtest_lab.py",
    "purple_dragon_security.py",
    "bitcoin_core.py",
    "block_template.py",
    "core_setup.py",
    "config.py",
    "branding.py",
    "ui_theme.py",
    "neon_widgets.py",
    "mining_assistant.py",
    "profitability_center.py",
    "hardware_compatibility.py",
    "assets/BitcoinMinerStudio.png",
    "assets/BitcoinMinerStudio.ico",
    "assets/PurpleDragonFoundationBanner.png",
    "assets/PurpleDragonFoundationLogo.png",
    "ui/assets/BitcoinMinerStudio.png",
    "ui/assets/PurpleDragonFoundationBanner.png",
    "ui/assets/PurpleDragonFoundationLogo.png",
    "requirements.txt",
    "run.bat",
    "package_portable.bat",
    "package_pyinstaller.bat",
    "diagnose.bat",
    "verify_build_integrity.bat",
    "selftest.bat",
    "tools/purple_dragon_sign.py",
    "tools/prepare_v2_0_2.py",
    "selftest.py",
    "credentials.py",
    "connections.py",
    "bitcoin_utils.py",
    "stratum_miner.py",
    "miner_engine.py",
    "benchmark_lab.py",
    "mining_academy.py",
    "diagnostics_center.py",
    "update_release_center.py",
    "pool_powertools.py",
    "pool_profiles.py",
    "analytics_monitor.py",
    "windows_tray.py",
    "local_test_pool.py",
    "asic_manager.py",
    "asic_solo_bridge.py",
    "fleet_monitor.py",
    "ui/index.html",
    "ui/styles.css",
    "ui/script.js",
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(payload):
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


if len(sys.argv) != 2:
    raise SystemExit("Usage: python tools\\purple_dragon_sign.py <publisher-private-key.pem>")

key_path = Path(sys.argv[1]).expanduser().resolve()
private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)

manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
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

signature = private_key.sign(
    canonical(manifest),
    padding.PKCS1v15(),
    hashes.SHA256(),
)
manifest["signature"] = base64.b64encode(signature).decode("ascii")
MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("Signed:", MANIFEST)
