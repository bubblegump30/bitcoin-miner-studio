import base64
import hashlib
import json
import platform
import socket
import sys
import uuid
from pathlib import Path

from branding import PUBLISHER_NAME

PRODUCT_NAME = "Bitcoin Miner Studio"
SECURITY_SCHEME = "PD-PROVENANCE-2"
SECURITY_CENTER_VERSION = "1.0"
PUBLIC_EXPONENT = 65537
PUBLIC_MODULUS = 3327338891455529228499902625334714944624202490271320441761500918600162513712161733162054209241187043495905973622810632738075240114182520584416508940907000891400119989930572258478107630465336089641188571247555007695823912117183247898260061146853500689450946075082373944664985431211593241306872880374080080768230521325253045404123875612292307860447426023034850112225997133501822424075568425193961851829347788593128041659430591371160426515350883946267744199027044529370776376794354428706419482513045167046013315448285252078351391808802636462213267944748165494386730369011046942512663323552052973551330463573477515035304544997881040178196287409542509601136749020665304677640688087926165928582647938959064205521729093437250995313664960481811704103974741692299071850659830283281049481233832543026609689605666329774423240130124576012671460313547195051332164253703307932063145741286886044095037460605873318472266628023360847991856043

# Forensic markers are intentionally encoded rather than stored as plain text.
# They are provenance clues, not cryptographic secrets and not DRM.
_FOOTPRINT_HEX = "507572706c6520447261676f6e"
_RELEASE_WATERMARK_HEX = "50443230312D393938383033313042364242323336423739323045374437"
_SHA256_DER_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _footprint_bytes():
    return bytes.fromhex(_FOOTPRINT_HEX)


def release_watermark():
    try:
        return bytes.fromhex(_RELEASE_WATERMARK_HEX).decode("utf-8")
    except Exception:
        return ""


def _base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _manifest_path(base_dir=None):
    return Path(base_dir or _base_dir()) / "purple_dragon_manifest.json"


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _canonical_payload(manifest):
    unsigned = dict(manifest)
    unsigned.pop("signature", None)
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _verify_rsa_pkcs1_v15_sha256(data, signature_b64):
    """Pure-Python RSA PKCS#1 v1.5 SHA-256 verification."""
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception:
        return False

    key_bytes = (PUBLIC_MODULUS.bit_length() + 7) // 8
    if len(signature) != key_bytes:
        return False

    sig_int = int.from_bytes(signature, "big")
    decoded = pow(sig_int, PUBLIC_EXPONENT, PUBLIC_MODULUS).to_bytes(key_bytes, "big")
    digest_info = _SHA256_DER_PREFIX + hashlib.sha256(data).digest()
    if len(decoded) < len(digest_info) + 11 or not decoded.startswith(b"\x00\x01"):
        return False
    try:
        separator = decoded.index(b"\x00", 2)
    except ValueError:
        return False
    padding_bytes = decoded[2:separator]
    if len(padding_bytes) < 8 or any(b != 0xFF for b in padding_bytes):
        return False
    return decoded[separator + 1:] == digest_info


def publisher_key_id():
    key_bytes = PUBLIC_MODULUS.to_bytes((PUBLIC_MODULUS.bit_length() + 7) // 8, "big")
    return "PDK-" + hashlib.sha256(key_bytes).hexdigest().upper()[:24]


def _windows_machine_guid():
    if not sys.platform.startswith("win"):
        return ""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value or "")
    except Exception:
        return ""


def install_fingerprint():
    """
    Local-only hashed installation fingerprint. Raw machine values are never
    returned or transmitted. This is intentionally not a remote activation ID.
    """
    raw_parts = [
        _windows_machine_guid(),
        platform.system(),
        platform.machine(),
        socket.gethostname(),
        str(uuid.getnode()),
        PRODUCT_NAME,
        SECURITY_SCHEME,
    ]
    return hashlib.sha256("|".join(raw_parts).encode("utf-8", "ignore")).hexdigest()


def marker_digest():
    return hashlib.sha256(
        _footprint_bytes()
        + b"|"
        + PRODUCT_NAME.encode()
        + b"|"
        + SECURITY_SCHEME.encode()
    ).hexdigest()


def watermark_digest(version):
    return hashlib.sha256(
        _footprint_bytes()
        + b"|"
        + release_watermark().encode()
        + b"|"
        + PRODUCT_NAME.encode()
        + b"|"
        + str(version or "").encode()
        + b"|"
        + SECURITY_SCHEME.encode()
    ).hexdigest()


def security_policy():
    return {
        "critical_actions_gated": True,
        "private_signing_key_embedded": False,
        "public_verification_key_embedded": True,
        "offline_verification": True,
        "anti_debugging": False,
        "code_obfuscation": False,
        "remote_activation": False,
        "claim": "Tamper-evident signed provenance; not a guarantee against cracking or copying.",
    }


def checking_state():
    return {
        "checked": False,
        "verified": False,
        "signature_valid": False,
        "critical_actions_allowed": False,
        "status": "checking",
        "trust_level": "CHECKING",
        "security_scheme": SECURITY_SCHEME,
        "security_center_version": SECURITY_CENTER_VERSION,
        "publisher_name": PUBLISHER_NAME,
        "publisher_key_id": publisher_key_id(),
        "build_id": "",
        "provenance_tag": "",
        "release_watermark": release_watermark(),
        "release_seal": "",
        "protected_file_count": 0,
        "verified_file_count": 0,
        "modified_files": [],
        "missing_files": [],
        "file_status": [],
        "install_fingerprint_short": install_fingerprint()[:16].upper(),
        "error": "Build verification is still running.",
        "policy": security_policy(),
    }


def verify_integrity(base_dir=None):
    base = Path(base_dir or _base_dir())
    manifest_file = _manifest_path(base)
    result = checking_state()
    result.update({
        "checked": True,
        "status": "locked",
        "trust_level": "LOCKED",
        "manifest_found": manifest_file.exists(),
        "marker_digest": marker_digest(),
        "error": "",
    })

    if not manifest_file.exists():
        result["error"] = "Signed Purple Dragon provenance manifest is missing."
        return result

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        result["error"] = f"Could not read Purple Dragon manifest: {exc}"
        return result

    result["manifest_schema"] = int(manifest.get("schema") or 0)
    result["build_id"] = str(manifest.get("build_id", ""))
    result["provenance_tag"] = str(manifest.get("provenance_tag", ""))
    result["release_watermark"] = str(manifest.get("release_watermark", ""))
    result["release_seal"] = str(manifest.get("release_seal", ""))
    result["release_version"] = str(manifest.get("version", ""))
    result["publisher_name"] = str(manifest.get("publisher_name", ""))
    result["manifest_security_scheme"] = str(manifest.get("security_scheme", ""))

    if str(manifest.get("product", "")) != PRODUCT_NAME:
        result["error"] = "Purple Dragon manifest product mismatch."
        return result
    if int(manifest.get("schema") or 0) < 2:
        result["error"] = "Purple Dragon v2 manifest schema is required."
        return result
    if str(manifest.get("security_scheme", "")) != SECURITY_SCHEME:
        result["error"] = "Purple Dragon security scheme mismatch."
        return result
    if str(manifest.get("publisher_name", "")) != PUBLISHER_NAME:
        result["error"] = "Purple Dragon publisher-name mismatch."
        return result
    if str(manifest.get("publisher_key_id", "")) != publisher_key_id():
        result["error"] = "Publisher verification-key identifier mismatch."
        return result

    signature_valid = _verify_rsa_pkcs1_v15_sha256(
        _canonical_payload(manifest),
        str(manifest.get("signature", "")),
    )
    result["signature_valid"] = signature_valid
    if not signature_valid:
        result["error"] = "Publisher signature verification failed."
        return result

    if str(manifest.get("marker_digest", "")) != marker_digest():
        result["error"] = "Purple Dragon forensic marker mismatch."
        return result

    embedded_watermark = release_watermark()
    if str(manifest.get("release_watermark", "")) != embedded_watermark:
        result["error"] = "Embedded Purple Dragon release watermark mismatch."
        return result

    expected_watermark_digest = watermark_digest(manifest.get("version", ""))
    if str(manifest.get("watermark_digest", "")) != expected_watermark_digest:
        result["error"] = "Purple Dragon release-watermark digest mismatch."
        return result

    files = dict(manifest.get("files") or {})
    result["protected_file_count"] = len(files)
    verified_count = 0
    file_status = []

    for relative, expected_hash in files.items():
        path = base / relative
        entry = {
            "path": str(relative),
            "status": "MISSING",
            "expected": str(expected_hash)[:12].upper(),
            "actual": "",
        }
        if not path.exists() or not path.is_file():
            result["missing_files"].append(relative)
            file_status.append(entry)
            continue
        try:
            actual_hash = _sha256_file(path)
        except Exception as exc:
            result["modified_files"].append(relative)
            entry["status"] = "ERROR"
            entry["actual"] = type(exc).__name__
            file_status.append(entry)
            continue

        entry["actual"] = actual_hash[:12].upper()
        if actual_hash.lower() != str(expected_hash).lower():
            result["modified_files"].append(relative)
            entry["status"] = "MODIFIED"
        else:
            verified_count += 1
            entry["status"] = "VERIFIED"
        file_status.append(entry)

    result["verified_file_count"] = verified_count
    result["file_status"] = file_status
    result["verified"] = (
        result["signature_valid"]
        and verified_count == len(files)
        and not result["missing_files"]
        and not result["modified_files"]
    )
    result["critical_actions_allowed"] = bool(result["verified"])

    if result["verified"]:
        result["status"] = "verified"
        result["trust_level"] = "TRUSTED"
        result["error"] = ""
    else:
        result["status"] = "locked"
        result["trust_level"] = "LOCKED"
        result["error"] = "One or more protected application files were changed or removed."
    return result


def provenance_report(base_dir=None):
    state = verify_integrity(base_dir)
    lines = [
        "PURPLE DRAGON SECURITY REPORT",
        "",
        f"Product: {PRODUCT_NAME}",
        f"Security scheme: {state.get('security_scheme') or SECURITY_SCHEME}",
        f"Trust level: {state.get('trust_level')}",
        f"Build ID: {state.get('build_id') or 'unknown'}",
        f"Provenance tag: {state.get('provenance_tag') or 'unknown'}",
        f"Release seal: {state.get('release_seal') or 'unknown'}",
        f"Publisher: {state.get('publisher_name') or PUBLISHER_NAME}",
        f"Publisher key ID: {state.get('publisher_key_id') or publisher_key_id()}",
        f"Publisher signature: {'VALID' if state.get('signature_valid') else 'INVALID'}",
        f"Protected files: {state.get('verified_file_count', 0)} / {state.get('protected_file_count', 0)} verified",
        f"Critical controls: {'ENABLED' if state.get('critical_actions_allowed') else 'LOCKED'}",
        f"Local install code: {state.get('install_fingerprint_short')}",
    ]
    if state.get("missing_files"):
        lines.append("Missing: " + ", ".join(state["missing_files"]))
    if state.get("modified_files"):
        lines.append("Modified: " + ", ".join(state["modified_files"]))
    if state.get("error"):
        lines.append("Status: " + state["error"])
    lines.extend([
        "",
        "Purple Dragon provides signed provenance and tamper evidence. It does not make software impossible to copy, reverse engineer, or crack.",
    ])
    return "\n".join(lines)
