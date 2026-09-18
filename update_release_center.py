"""Bitcoin Miner Studio v2.0.2 — Update & Release Center.

Local-first update inspection and release engineering orchestration.

Security / safety boundaries:
- no background update downloads;
- no silent self-update or in-place replacement of the running application;
- no execution of files from candidate packages;
- candidate releases are cryptographically verified before staging;
- staging only copies a package/folder into app-data and records rollback metadata;
- release descriptors contain no credentials or private signing material.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from branding import PUBLISHER_NAME
from purple_dragon_security import (
    PRODUCT_NAME,
    PUBLIC_EXPONENT,
    PUBLIC_MODULUS,
    SECURITY_SCHEME,
    publisher_key_id,
)

UPDATE_CENTER_SCHEMA = 1
RELEASE_DESCRIPTOR_SCHEMA = 1
DEFAULT_APP_DATA_DIR = Path.home() / ".bitcoin-miner-studio"
_ALLOWED_CHANNELS = ("stable", "preview")
_SHA256_DER_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?\s*$", re.I)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _human_bytes(value: int | float) -> str:
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


_STAGE_IGNORED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def _stage_copy_ignore(_directory: str, names: list[str]) -> set[str]:
    """Exclude VCS/runtime cache metadata from a staged release folder."""
    return {name for name in names if name in _STAGE_IGNORED_NAMES}


def _remove_tree(path: Path) -> None:
    """Remove a staged tree even when Windows copied read-only metadata/files."""
    path = Path(path)

    def _onerror(func, name, _exc_info):
        try:
            os.chmod(name, stat.S_IWRITE)
            func(name)
        except Exception:
            raise

    shutil.rmtree(path, onerror=_onerror)


def _canonical_manifest(manifest: dict[str, Any]) -> bytes:
    unsigned = dict(manifest or {})
    unsigned.pop("signature", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify_rsa_pkcs1_v15_sha256(data: bytes, signature_b64: str) -> bool:
    try:
        signature = base64.b64decode(str(signature_b64 or ""), validate=True)
    except Exception:
        return False
    key_bytes = (PUBLIC_MODULUS.bit_length() + 7) // 8
    if len(signature) != key_bytes:
        return False
    decoded = pow(int.from_bytes(signature, "big"), PUBLIC_EXPONENT, PUBLIC_MODULUS).to_bytes(key_bytes, "big")
    digest_info = _SHA256_DER_PREFIX + hashlib.sha256(data).digest()
    if len(decoded) < len(digest_info) + 11 or not decoded.startswith(b"\x00\x01"):
        return False
    try:
        separator = decoded.index(b"\x00", 2)
    except ValueError:
        return False
    padding_bytes = decoded[2:separator]
    return bool(len(padding_bytes) >= 8 and all(b == 0xFF for b in padding_bytes) and decoded[separator + 1:] == digest_info)


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(str(value or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(match.group(i) or 0) for i in (1, 2, 3))


def compare_versions(candidate: str, current: str) -> int:
    """Return 1 when candidate is newer, 0 when equal, -1 when older."""
    c = _version_tuple(candidate)
    cur = _version_tuple(current)
    return (c > cur) - (c < cur)


def _safe_archive_member(name: str) -> bool:
    raw = str(name or "").replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        return False
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    return bool(parts and all(p != ".." for p in parts))


def _find_release_root(extracted: Path) -> Path | None:
    extracted = Path(extracted)
    if (extracted / "release_info.json").is_file() and (extracted / "purple_dragon_manifest.json").is_file():
        return extracted
    candidates: list[Path] = []
    for info in extracted.glob("*/release_info.json"):
        root = info.parent
        if (root / "purple_dragon_manifest.json").is_file():
            candidates.append(root)
    return candidates[0] if len(candidates) == 1 else None


def _extract_package(package: Path, destination: Path) -> tuple[bool, str, Path | None]:
    package = Path(package)
    suffix = package.suffix.lower()
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(package, "r") as zf:
                names = zf.namelist()
                if not names or any(not _safe_archive_member(name) for name in names if not name.endswith("/")):
                    return False, "Archive contains an unsafe or invalid path.", None
                zf.extractall(destination)
        elif suffix == ".7z":
            try:
                import py7zr  # type: ignore
            except Exception:
                return False, "7z inspection requires the py7zr dependency. Run run.bat to install/update dependencies.", None
            with py7zr.SevenZipFile(package, mode="r") as archive:
                names = archive.getnames()
                if not names or any(not _safe_archive_member(name) for name in names if not str(name).endswith("/")):
                    return False, "Archive contains an unsafe or invalid path.", None
                archive.extractall(path=destination)
        else:
            return False, "Supported update packages are .7z and .zip, or an extracted release folder.", None
    except Exception as exc:
        return False, f"Package extraction failed: {exc}", None

    root = _find_release_root(destination)
    if root is None:
        return False, "Could not locate a single Bitcoin Miner Studio release root inside the package.", None
    return True, "", root


def verify_release_folder(root: Path) -> dict[str, Any]:
    """Verify a candidate release without importing/executing candidate code."""
    root = Path(root).resolve()
    manifest_path = root / "purple_dragon_manifest.json"
    release_info_path = root / "release_info.json"
    result: dict[str, Any] = {
        "trusted": False,
        "signature_valid": False,
        "files_verified": 0,
        "files_total": 0,
        "missing_files": [],
        "modified_files": [],
        "errors": [],
        "version": "",
        "channel": "",
        "build_id": "",
        "release_seal": "",
        "publisher_key_id": "",
        "publisher": "",
    }
    if not manifest_path.is_file() or not release_info_path.is_file():
        result["errors"].append("release_info.json or purple_dragon_manifest.json is missing.")
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        info = json.loads(release_info_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["errors"].append(f"Release metadata could not be parsed: {exc}")
        return result

    result.update({
        "version": str(manifest.get("version") or info.get("version") or ""),
        "channel": str(info.get("channel") or ""),
        "build_id": str(manifest.get("build_id") or ""),
        "release_seal": str(manifest.get("release_seal") or ""),
        "publisher_key_id": str(manifest.get("publisher_key_id") or ""),
        "publisher": str(manifest.get("publisher_name") or info.get("publisher") or ""),
    })

    if manifest.get("product") != PRODUCT_NAME or info.get("product") != PRODUCT_NAME:
        result["errors"].append("Product identity mismatch.")
    if str(manifest.get("security_scheme") or "") != SECURITY_SCHEME:
        result["errors"].append("Purple Dragon security scheme mismatch.")
    if str(manifest.get("publisher_key_id") or "") != publisher_key_id():
        result["errors"].append("Publisher verification-key identifier mismatch.")
    if str(manifest.get("publisher_name") or "") != PUBLISHER_NAME:
        result["errors"].append("Publisher name mismatch.")
    if str(info.get("version") or "") != str(manifest.get("version") or ""):
        result["errors"].append("Release-info version does not match the signed manifest.")

    signature_valid = _verify_rsa_pkcs1_v15_sha256(_canonical_manifest(manifest), str(manifest.get("signature") or ""))
    result["signature_valid"] = signature_valid
    if not signature_valid:
        result["errors"].append("Publisher signature verification failed.")

    files = dict(manifest.get("files") or {})
    result["files_total"] = len(files)

    # Candidate folders must not contain symlinks. A signed relative filename
    # must resolve to a real file inside the candidate release root.
    for candidate_path in root.rglob("*"):
        try:
            if candidate_path.is_symlink():
                result["errors"].append(f"Candidate release contains a symbolic link: {candidate_path.relative_to(root).as_posix()}")
        except Exception:
            result["errors"].append("Candidate release contains an unreadable filesystem entry.")
            break

    for relative, expected in files.items():
        rel = str(relative).replace("\\", "/")
        if not _safe_archive_member(rel):
            result["errors"].append(f"Unsafe protected-file path in manifest: {relative}")
            continue
        path = root / rel
        try:
            resolved = path.resolve(strict=True)
            if path.is_symlink() or (resolved != root and root not in resolved.parents):
                result["errors"].append(f"Protected file escapes the candidate release root: {rel}")
                continue
        except Exception:
            result["missing_files"].append(rel)
            continue
        if not resolved.is_file():
            result["missing_files"].append(rel)
            continue
        try:
            actual = _sha256_file(resolved)
        except Exception:
            result["modified_files"].append(rel)
            continue
        if actual != str(expected):
            result["modified_files"].append(rel)
        else:
            result["files_verified"] += 1

    # v1.9+ signs every executable source/UI/batch surface. This prevents a
    # package from appending or replacing unsigned code while retaining an
    # otherwise valid manifest signature. Older official releases retain their
    # historical protection profile for rollback compatibility.
    if _version_tuple(result.get("version", "")) >= (1, 9, 0):
        protected_names = {str(name).replace("\\", "/") for name in files}
        code_like = {
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in {".py", ".pyw", ".js", ".html", ".css", ".bat"}
            and "__pycache__" not in p.parts
        }
        unsigned_code = sorted(code_like - protected_names)
        if unsigned_code:
            result["errors"].append(
                "Unsigned executable/code surface in v1.9+ candidate: " + ", ".join(unsigned_code[:8])
                + (" ..." if len(unsigned_code) > 8 else "")
            )
            result["unsigned_code_files"] = unsigned_code

    if result["missing_files"]:
        result["errors"].append(f"{len(result['missing_files'])} protected file(s) missing.")
    if result["modified_files"]:
        result["errors"].append(f"{len(result['modified_files'])} protected file(s) failed SHA-256 verification.")

    result["trusted"] = bool(
        not result["errors"]
        and signature_valid
        and result["files_total"] > 0
        and result["files_verified"] == result["files_total"]
    )
    return result


class UpdateReleaseCenter:
    """Local update staging + signed release metadata center."""

    def __init__(self, root: Path, version: str, *, app_data_dir: Path | None = None):
        self.root = Path(root).resolve()
        self.version = str(version)
        self.app_data_dir = Path(app_data_dir or DEFAULT_APP_DATA_DIR)
        self.update_dir = self.app_data_dir / "updates"
        self.staging_dir = self.update_dir / "staged"
        self.export_dir = self.update_dir / "release-exports"
        self.settings_file = self.update_dir / "update-settings.json"
        self.history_file = self.update_dir / "update-history.json"
        self.rollback_file = self.update_dir / "rollback-plan.json"
        self._last_inspection: dict[str, Any] = {}
        self._state = self._build_state()

    def _load_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default
        except Exception:
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _release_info(self) -> dict[str, Any]:
        return dict(self._load_json(self.root / "release_info.json", {}) or {})

    def _manifest_summary(self) -> dict[str, Any]:
        manifest = dict(self._load_json(self.root / "purple_dragon_manifest.json", {}) or {})
        return {
            "build_id": str(manifest.get("build_id") or ""),
            "provenance_tag": str(manifest.get("provenance_tag") or ""),
            "release_seal": str(manifest.get("release_seal") or ""),
            "publisher_key_id": str(manifest.get("publisher_key_id") or ""),
            "protected_files": len(dict(manifest.get("files") or {})),
            "signed": bool(manifest.get("signature")),
        }

    def _settings(self) -> dict[str, Any]:
        settings = dict(self._load_json(self.settings_file, {}) or {})
        channel = str(settings.get("channel") or "stable").lower()
        if channel not in _ALLOWED_CHANNELS:
            channel = "stable"
        return {"channel": channel, "automatic_download": False, "silent_apply": False}

    def _history(self) -> list[dict[str, Any]]:
        data = self._load_json(self.history_file, [])
        return list(data)[:25] if isinstance(data, list) else []

    def _build_state(self) -> dict[str, Any]:
        info = self._release_info()
        staged = sorted(self.staging_dir.glob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True) if self.staging_dir.exists() else []
        staged_path = staged[0] if staged else None
        return {
            "schema": UPDATE_CENTER_SCHEMA,
            "version": self.version,
            "channel": self._settings()["channel"],
            "current": {
                "version": str(info.get("version") or self.version),
                "channel": str(info.get("channel") or "Stable"),
                "stability": str(info.get("stability") or "Stable"),
                "publisher": str(info.get("publisher") or PUBLISHER_NAME),
                **self._manifest_summary(),
            },
            "policy": {
                "local_first": True,
                "automatic_download": False,
                "silent_apply": False,
                "candidate_execution": False,
                "trusted_package_required_for_staging": True,
                "rollback_metadata": True,
            },
            "inspection": self._last_inspection,
            "staged": {
                "present": bool(staged_path),
                "path": str(staged_path) if staged_path else "",
                "name": staged_path.name if staged_path else "",
                "size": _human_bytes(staged_path.stat().st_size) if staged_path and staged_path.is_file() else "",
            },
            "history": self._history(),
            "last_export": "",
        }

    def state(self) -> dict[str, Any]:
        self._state = {**self._build_state(), "inspection": self._last_inspection, "last_export": self._state.get("last_export", "") if hasattr(self, "_state") else ""}
        return json.loads(json.dumps(self._state))

    def set_channel(self, channel: str) -> dict[str, Any]:
        channel = str(channel or "").strip().lower()
        if channel not in _ALLOWED_CHANNELS:
            raise ValueError("Update channel must be Stable or Preview.")
        self._write_json(self.settings_file, {"channel": channel, "automatic_download": False, "silent_apply": False})
        self._state = self._build_state()
        return self.state()

    def inspect(self, source: str, expected_sha256: str = "") -> dict[str, Any]:
        source_path = Path(os.path.expandvars(os.path.expanduser(str(source or "").strip()))).resolve()
        inspection: dict[str, Any] = {
            "ok": False,
            "source": str(source_path),
            "name": source_path.name,
            "kind": "folder" if source_path.is_dir() else "package",
            "package_sha256": "",
            "package_size": "",
            "expected_sha256": str(expected_sha256 or "").strip().lower(),
            "checksum_match": None,
            "trust": {},
            "relation": "UNKNOWN",
            "recommendation": "BLOCKED",
            "detail": "",
            "inspected_at": _now_iso(),
        }
        if not source_path.exists():
            inspection["detail"] = "Selected update source does not exist."
            self._last_inspection = inspection
            return self.state()

        if source_path.is_file():
            inspection["package_size"] = _human_bytes(source_path.stat().st_size)
            inspection["package_sha256"] = _sha256_file(source_path)
            expected = inspection["expected_sha256"]
            inspection["checksum_match"] = (inspection["package_sha256"] == expected) if expected else None
            if expected and inspection["checksum_match"] is False:
                inspection["detail"] = "Package SHA-256 does not match the expected checksum."
                self._last_inspection = inspection
                return self.state()

        temp_dir: tempfile.TemporaryDirectory[str] | None = None
        try:
            release_root = source_path
            if source_path.is_file():
                temp_dir = tempfile.TemporaryDirectory(prefix="bms-update-inspect-")
                ok, error, extracted_root = _extract_package(source_path, Path(temp_dir.name))
                if not ok or extracted_root is None:
                    inspection["detail"] = error
                    self._last_inspection = inspection
                    return self.state()
                release_root = extracted_root

            trust = verify_release_folder(release_root)
            inspection["trust"] = trust
            relation_value = compare_versions(str(trust.get("version") or ""), self.version)
            inspection["relation"] = "NEWER" if relation_value > 0 else "SAME" if relation_value == 0 else "OLDER"
            preferred = self._settings()["channel"]
            candidate_channel = str(trust.get("channel") or "stable").strip().lower()
            channel_ok = preferred == "preview" or candidate_channel == "stable"
            inspection["channel_compatible"] = channel_ok
            inspection["ok"] = bool(trust.get("trusted"))
            if not trust.get("trusted"):
                inspection["recommendation"] = "BLOCKED"
                inspection["detail"] = "; ".join(trust.get("errors") or ["Candidate release is not trusted."])
            elif not channel_ok:
                inspection["recommendation"] = "CHANNEL BLOCKED"
                inspection["detail"] = f"Candidate channel '{candidate_channel or 'unknown'}' is outside the preferred Stable channel."
            elif relation_value > 0:
                inspection["recommendation"] = "UPDATE READY"
                inspection["detail"] = "Newer trusted release verified. It can be staged locally for a deliberate offline apply step."
            elif relation_value == 0:
                inspection["recommendation"] = "REINSTALL / VERIFY"
                inspection["detail"] = "Trusted package matches the currently installed version."
            else:
                inspection["recommendation"] = "ROLLBACK CANDIDATE"
                inspection["detail"] = "Trusted older release verified. It can be staged as an explicit rollback candidate."
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

        self._last_inspection = inspection
        return self.state()

    def stage_last_inspection(self) -> dict[str, Any]:
        inspection = dict(self._last_inspection or {})
        trust = dict(inspection.get("trust") or {})
        if not inspection.get("ok") or not trust.get("trusted"):
            raise ValueError("Only a successfully inspected TRUSTED release can be staged.")
        if not inspection.get("channel_compatible", True):
            raise ValueError("Candidate does not match the selected update channel policy.")
        source = Path(str(inspection.get("source") or ""))
        if not source.exists():
            raise FileNotFoundError("The inspected update source is no longer available.")

        self.staging_dir.mkdir(parents=True, exist_ok=True)
        safe_version = re.sub(r"[^0-9A-Za-z._-]+", "-", str(trust.get("version") or "unknown"))
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        if source.is_file():
            target = self.staging_dir / f"BMS-v{safe_version}-{stamp}{source.suffix.lower()}"
            shutil.copy2(source, target)
            staged_sha = _sha256_file(target)
            if inspection.get("package_sha256") and staged_sha != inspection.get("package_sha256"):
                target.unlink(missing_ok=True)
                raise IOError("Staged package checksum changed during copy.")
        else:
            target = self.staging_dir / f"BMS-v{safe_version}-{stamp}"
            shutil.copytree(source, target, ignore=_stage_copy_ignore)
            staged_sha = ""

        rollback = {
            "schema": 1,
            "created_at": _now_iso(),
            "from_version": self.version,
            "to_version": str(trust.get("version") or ""),
            "relationship": str(inspection.get("relation") or ""),
            "staged_path": str(target),
            "staged_sha256": staged_sha,
            "current_release": self._manifest_summary(),
            "apply_policy": "offline-explicit-only",
            "note": "Bitcoin Miner Studio does not replace the running application automatically. Close the app and use the complete trusted release for any update or rollback.",
        }
        self._write_json(self.rollback_file, rollback)
        history = self._history()
        history.insert(0, {
            "action": "staged",
            "at": _now_iso(),
            "version": str(trust.get("version") or ""),
            "relation": str(inspection.get("relation") or ""),
            "name": target.name,
            "sha256": staged_sha,
        })
        self._write_json(self.history_file, history[:25])
        self._state = self._build_state()
        return {"ok": True, "state": self.state(), "path": str(target), "rollback_plan": str(self.rollback_file)}

    def clear_staged(self) -> dict[str, Any]:
        if self.staging_dir.exists():
            for child in self.staging_dir.iterdir():
                if child.is_dir():
                    _remove_tree(child)
                else:
                    child.unlink(missing_ok=True)
        if self.rollback_file.exists():
            self.rollback_file.unlink(missing_ok=True)
        history = self._history()
        history.insert(0, {"action": "staging-cleared", "at": _now_iso(), "version": self.version})
        self._write_json(self.history_file, history[:25])
        self._state = self._build_state()
        return {"ok": True, "state": self.state()}

    def export_release_descriptor(self, security_state: dict[str, Any] | None = None) -> dict[str, Any]:
        info = self._release_info()
        manifest = dict(self._load_json(self.root / "purple_dragon_manifest.json", {}) or {})
        files = dict(manifest.get("files") or {})
        descriptor = {
            "schema": RELEASE_DESCRIPTOR_SCHEMA,
            "product": PRODUCT_NAME,
            "version": self.version,
            "channel": str(info.get("channel") or "Stable"),
            "publisher": PUBLISHER_NAME,
            "created_at": _now_iso(),
            "build_id": str(manifest.get("build_id") or ""),
            "provenance_tag": str(manifest.get("provenance_tag") or ""),
            "release_seal": str(manifest.get("release_seal") or ""),
            "publisher_key_id": str(manifest.get("publisher_key_id") or ""),
            "protected_files": len(files),
            "protected_files_digest": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "security": {
                "trust_level": str((security_state or {}).get("trust_level") or "UNKNOWN"),
                "signature_valid": bool((security_state or {}).get("signature_valid")),
                "critical_controls": "ENABLED" if (security_state or {}).get("critical_actions_allowed") else "LOCKED",
            },
            "update_policy": {
                "automatic_download": False,
                "silent_apply": False,
                "offline_explicit_apply": True,
            },
            "notes": str(info.get("notes") or ""),
        }
        self.export_dir.mkdir(parents=True, exist_ok=True)
        path = self.export_dir / f"BitcoinMinerStudio-v{self.version}-release-descriptor.json"
        self._write_json(path, descriptor)
        self._state["last_export"] = str(path)
        return {"ok": True, "path": str(path), "descriptor": descriptor}

    def report(self) -> str:
        state = self.state()
        current = state.get("current") or {}
        inspection = state.get("inspection") or {}
        trust = inspection.get("trust") or {}
        lines = [
            "BITCOIN MINER STUDIO — UPDATE & RELEASE CENTER",
            "",
            f"Current version: {current.get('version', self.version)}",
            f"Channel: {state.get('channel', 'stable').upper()}",
            f"Build ID: {current.get('build_id', '')}",
            f"Protected files: {current.get('protected_files', 0)}",
            "Automatic download: OFF",
            "Silent apply: OFF",
            "",
            "LAST PACKAGE INSPECTION",
            f"Source: {inspection.get('name') or 'None'}",
            f"Candidate version: {trust.get('version') or '—'}",
            f"Publisher signature: {'VALID' if trust.get('signature_valid') else '—'}",
            f"Protected files: {trust.get('files_verified', 0)} / {trust.get('files_total', 0)}",
            f"Relationship: {inspection.get('relation') or '—'}",
            f"Recommendation: {inspection.get('recommendation') or '—'}",
            f"Detail: {inspection.get('detail') or '—'}",
            "",
            "Policy: candidate packages are inspected and staged only. Bitcoin Miner Studio never silently replaces its running application.",
        ]
        return "\n".join(lines)
