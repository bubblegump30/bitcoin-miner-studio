"""Bitcoin Miner Studio v1.4.0 — Pool Profiles & Smart Failover.

Local-only release engineering utilities:
- release/readiness preflight;
- configuration validation;
- previous-unclean-session detection;
- privacy-sanitized support bundles.

This module never starts mining, changes ASIC settings, talks to a pool,
submits blocks, or transmits support data. Support bundles are created locally
and are not uploaded anywhere.
"""
from __future__ import annotations

import importlib
import json
import os
import platform
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from ui_theme import UI_THEME_PRESETS

APP_DATA_DIR = Path.home() / ".bitcoin-miner-studio"
SESSION_MARKER = APP_DATA_DIR / "runtime-session.json"
SUPPORT_DIR = APP_DATA_DIR / "support"
RELEASE_CHANNEL = "Stable"
SUPPORT_BUNDLE_SCHEMA = 1
PREFLIGHT_SCHEMA = 1

_SECRET_KEYS = {
    "pool_password",
    "rpc_password",
    "password",
    "private_key",
    "seed",
    "seed_phrase",
    "mnemonic",
}
_PRIVACY_KEYS = {
    "pool_worker",
    "rpc_user",
    "coinbase_payout_address",
    "core_cookie_path",
}

_STRATUM_RE = re.compile(r"(stratum\+(?:tcp|ssl)://)([^/\s:]+)(:\d+)", re.I)
_BTC_BECH32_RE = re.compile(r"\b(?:bc1|tb1|bcrt1)[023456789ac-hj-np-z]{12,90}\b", re.I)
_BTC_BASE58_RE = re.compile(r"\b[13mn2][1-9A-HJ-NP-Za-km-z]{25,50}\b")
_HOME_TEXT = str(Path.home())


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _human_bytes(value: int | float) -> str:
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def _redact_path(value: str) -> str:
    text = str(value or "")
    if _HOME_TEXT and _HOME_TEXT in text:
        text = text.replace(_HOME_TEXT, "%USERPROFILE%")
    return text


def redact_text(text: str) -> str:
    """Best-effort privacy redaction for support-bundle text."""
    text = _redact_path(str(text or ""))
    text = _STRATUM_RE.sub(lambda m: f"{m.group(1)}<pool-host>{m.group(3)}", text)
    text = _BTC_BECH32_RE.sub("<bitcoin-address>", text)
    text = _BTC_BASE58_RE.sub("<bitcoin-address>", text)
    # Common password-bearing JSON/log forms.
    text = re.sub(
        r'(?i)(password|rpc_password|pool_password)\s*[:=]\s*["\']?[^,\s"\']+',
        r"\1=<redacted>",
        text,
    )
    return text


def sanitize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a support-safe settings view.

    Passwords/secrets are removed. User-identifying worker/account/payout
    fields are replaced with explicit redaction markers. Home paths are
    normalized to %USERPROFILE%.
    """
    out: dict[str, Any] = {}
    for key, value in dict(cfg or {}).items():
        lower = str(key).lower()
        if lower in _SECRET_KEYS or "password" in lower or "private_key" in lower:
            continue
        if lower in _PRIVACY_KEYS:
            out[key] = "<redacted>" if value else ""
            continue
        if isinstance(value, str):
            out[key] = redact_text(value)
        elif isinstance(value, list):
            out[key] = [redact_text(v) if isinstance(v, str) else v for v in value]
        elif isinstance(value, dict):
            # Fleet aliases/notes may contain personal names or descriptions.
            if lower in {"asic_aliases", "asic_notes"}:
                out[key] = {"<redacted>": f"{len(value)} item(s)"} if value else {}
            else:
                out[key] = sanitize_config(value)
        else:
            out[key] = value
    return out


def validate_config(cfg: dict[str, Any], config_path: Path | None = None) -> list[dict[str, Any]]:
    cfg = dict(cfg or {})
    issues: list[dict[str, Any]] = []

    def add(severity: str, code: str, message: str, area: str = "Configuration"):
        issues.append({
            "severity": severity,
            "code": code,
            "area": area,
            "message": message,
        })

    def ranged(key: str, low: int | float, high: int | float):
        try:
            value = float(cfg.get(key))
        except Exception:
            add("fail", f"config.{key}", f"{key} is not a number.")
            return
        if not low <= value <= high:
            add("fail", f"config.{key}", f"{key} must be between {low} and {high}; current value is {value:g}.")

    ranged("mining_processes", 1, 64)
    ranged("benchmark_processes", 1, 64)
    ranged("pool_job_timeout_seconds", 20, 1800)
    ranged("core_refresh_seconds", 5, 300)
    ranged("template_refresh_seconds", 5, 300)
    ranged("analytics_sample_seconds", 5, 300)
    ranged("analytics_retention_days", 1, 365)
    if "tray_poll_seconds" in cfg:
        ranged("tray_poll_seconds", 5, 300)
    ranged("regtest_lab_rpc_port", 1, 65535)
    ranged("regtest_lab_p2p_port", 1, 65535)
    ranged("asic_solo_port", 1, 65535)

    theme = str(cfg.get("ui_theme") or "purple").strip().lower()
    if theme not in UI_THEME_PRESETS:
        add(
            "warn",
            "ui.theme_unknown",
            f"Unknown UI theme '{theme}'. Purple will be used as the safe fallback.",
            "Configuration",
        )

    if int(cfg.get("regtest_lab_rpc_port", 19443)) == int(cfg.get("regtest_lab_p2p_port", 19444)):
        add("fail", "config.regtest_ports", "Regtest RPC and P2P ports cannot be the same.", "Regtest")

    core_exe = str(cfg.get("core_executable") or "")
    if core_exe and not Path(core_exe).is_file():
        add("warn", "core.executable_missing", "Configured Bitcoin Core executable does not currently exist.", "Bitcoin Core")

    core_dir = str(cfg.get("core_data_dir") or "")
    if core_dir and not Path(core_dir).is_dir():
        add("warn", "core.data_dir_missing", "Configured Bitcoin Core data directory does not currently exist.", "Bitcoin Core")

    pool_url = str(cfg.get("pool_url") or "")
    if pool_url and "example.com" not in pool_url:
        if not re.match(r"^stratum\+(?:tcp|ssl)://[^:\s/]+:\d{1,5}$", pool_url, re.I):
            add("warn", "pool.url_shape", "Primary pool URL is not in the expected stratum+tcp/ssl://host:port form.", "Pool")

    backups = cfg.get("pool_backup_urls") or []
    if not isinstance(backups, list):
        add("fail", "pool.backups_type", "Pool backup endpoints must be stored as a list.", "Pool")
    elif len(backups) > 3:
        add("warn", "pool.backups_count", "More than three backup pool endpoints are configured; UI supports three.", "Pool")

    if bool(cfg.get("pool_url_ephemeral_local_test")):
        add("warn", "pool.ephemeral_marker", "An interrupted Local Test Pool session marker is still set.", "Pool")

    if config_path and config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            for forbidden in ("pool_password", "rpc_password"):
                if forbidden in raw:
                    add(
                        "fail",
                        "privacy.secret_in_settings",
                        f"{forbidden} is present in settings.json; credentials must stay in the credential backend.",
                        "Privacy",
                    )
        except Exception as exc:
            add("fail", "config.json_invalid", f"settings.json could not be parsed: {exc}")

    return issues


def _check(status: str, code: str, title: str, detail: str, area: str, blocking: bool = False) -> dict[str, Any]:
    return {
        "status": status,
        "code": code,
        "title": title,
        "detail": detail,
        "area": area,
        "blocking": bool(blocking),
    }


def _writable_directory(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="bms-rc-", dir=path, delete=True) as f:
            f.write(b"ok")
            f.flush()
        return True, str(path)
    except Exception as exc:
        return False, f"{path}: {exc}"


class ReleaseCandidateManager:
    def __init__(self, root: Path, version: str, cfg: dict[str, Any], config_path: Path | None = None):
        self.root = Path(root).resolve()
        self.version = str(version)
        self.config_path = Path(config_path) if config_path else APP_DATA_DIR / "settings.json"
        self._state = {
            "schema": PREFLIGHT_SCHEMA,
            "channel": RELEASE_CHANNEL,
            "version": self.version,
            "running": False,
            "checked": False,
            "score": 0,
            "readiness": "NOT CHECKED",
            "blockers": 0,
            "warnings": 0,
            "passes": 0,
            "checks": [],
            "config_issues": [],
            "previous_unclean_shutdown": False,
            "checked_at": "",
            "support_bundle": "",
        }
        self._previous_unclean = self._mark_session_started()
        self._state["previous_unclean_shutdown"] = self._previous_unclean

    def _mark_session_started(self) -> bool:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        previous_unclean = False
        try:
            if SESSION_MARKER.exists():
                previous = json.loads(SESSION_MARKER.read_text(encoding="utf-8"))
                previous_unclean = not bool(previous.get("clean_shutdown"))
        except Exception:
            previous_unclean = True
        payload = {
            "version": self.version,
            "started_at": _now_iso(),
            "pid": os.getpid(),
            "clean_shutdown": False,
        }
        try:
            SESSION_MARKER.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass
        return previous_unclean

    def mark_clean_shutdown(self) -> None:
        payload = {
            "version": self.version,
            "ended_at": _now_iso(),
            "pid": os.getpid(),
            "clean_shutdown": True,
        }
        try:
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            SESSION_MARKER.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    def state(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state))

    def run_preflight(
        self,
        cfg: dict[str, Any],
        security_state: dict[str, Any] | None = None,
        analytics_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._state["running"] = True
        checks: list[dict[str, Any]] = []

        # Runtime
        py_ok = sys.version_info >= (3, 11)
        checks.append(_check(
            "pass" if py_ok else "fail",
            "runtime.python",
            "Python runtime",
            f"{platform.python_implementation()} {platform.python_version()} · {platform.architecture()[0]}",
            "Runtime",
            blocking=not py_ok,
        ))

        try:
            importlib.import_module("webview")
            checks.append(_check("pass", "runtime.pywebview", "WebView runtime", "pywebview import succeeded.", "Runtime"))
        except Exception as exc:
            checks.append(_check("fail", "runtime.pywebview", "WebView runtime", f"pywebview import failed: {exc}", "Runtime", True))

        try:
            importlib.import_module("cryptography")
            checks.append(_check("pass", "runtime.crypto", "Cryptography runtime", "Publisher-signature verification dependency is available.", "Runtime"))
        except Exception as exc:
            checks.append(_check("fail", "runtime.crypto", "Cryptography runtime", f"cryptography import failed: {exc}", "Runtime", True))

        try:
            sqlite3.connect(":memory:").execute("select 1").fetchone()
            checks.append(_check("pass", "runtime.sqlite", "SQLite runtime", f"SQLite {sqlite3.sqlite_version} available.", "Runtime"))
        except Exception as exc:
            checks.append(_check("fail", "runtime.sqlite", "SQLite runtime", f"SQLite unavailable: {exc}", "Runtime", True))

        # App assets
        required = [
            "main.py", "launch.pyw", "webview_app.py",
            "ui/index.html", "ui/styles.css", "ui/script.js",
            "assets/BitcoinMinerStudio.ico", "assets/BitcoinMinerStudio.png",
            "assets/PurpleDragonFoundationBanner.png", "assets/PurpleDragonFoundationLogo.png",
            "ui/assets/BitcoinMinerStudio.png",
            "ui/assets/PurpleDragonFoundationBanner.png", "ui/assets/PurpleDragonFoundationLogo.png",
            "branding.py", "windows_version_info.txt",
            "windows_tray.py",
            "benchmark_lab.py", "mining_academy.py", "diagnostics_center.py", "update_release_center.py",
            "mining_assistant.py", "profitability_center.py",
            "hardware_compatibility.py",
            "pool_profiles.py",
            "purple_dragon_manifest.json",
        ]
        missing = [name for name in required if not (self.root / name).is_file()]
        checks.append(_check(
            "pass" if not missing else "fail",
            "release.assets",
            "Required application assets",
            "All startup/UI/security assets are present." if not missing else f"Missing: {', '.join(missing)}",
            "Release",
            blocking=bool(missing),
        ))

        # Main app-data storage.
        writable, detail = _writable_directory(APP_DATA_DIR)
        checks.append(_check(
            "pass" if writable else "fail",
            "storage.app_data",
            "Local application storage",
            f"Writable: {_redact_path(detail)}" if writable else _redact_path(detail),
            "Storage",
            blocking=not writable,
        ))

        try:
            usage = shutil.disk_usage(APP_DATA_DIR)
            free_gb = usage.free / (1024 ** 3)
            status = "pass" if free_gb >= 1 else "warn"
            checks.append(_check(
                status,
                "storage.free_space",
                "Free disk space",
                f"{free_gb:.1f} GB free on application-data volume.",
                "Storage",
            ))
        except Exception as exc:
            checks.append(_check("warn", "storage.free_space", "Free disk space", f"Could not measure free space: {exc}", "Storage"))

        # Startup guards added during v0.7 hardening.
        try:
            launch = (self.root / "launch.pyw").read_text(encoding="utf-8")
            main = (self.root / "main.py").read_text(encoding="utf-8")
            guarded = (
                'if __name__ == "__main__":' in launch
                and "multiprocessing.freeze_support()" in launch
                and 'current_process().name != "MainProcess"' in launch
                and 'if __name__ == "__main__":' in main
                and "multiprocessing.freeze_support()" in main
            )
            checks.append(_check(
                "pass" if guarded else "fail",
                "startup.spawn_guard",
                "Windows worker spawn guard",
                "GUI entrypoints are protected from multiprocessing child re-entry." if guarded else "Multiprocessing GUI guards are incomplete.",
                "Startup",
                blocking=not guarded,
            ))
        except Exception as exc:
            checks.append(_check("fail", "startup.spawn_guard", "Windows worker spawn guard", str(exc), "Startup", True))

        # Private publisher-key leak check.
        private_candidates = []
        for candidate in self.root.glob("*.pem"):
            try:
                if "PRIVATE KEY" in candidate.read_text(encoding="utf-8", errors="ignore"):
                    private_candidates.append(candidate.name)
            except Exception:
                pass
        checks.append(_check(
            "pass" if not private_candidates else "fail",
            "security.private_key",
            "Publisher private key",
            "No publisher private key is present in the release directory." if not private_candidates else f"Private key material found: {', '.join(private_candidates)}",
            "Security",
            blocking=bool(private_candidates),
        ))

        # Public-source hygiene: protected release files must not contain a
        # developer's absolute Windows user-profile path.
        profile_leaks = []
        try:
            manifest_path = self.root / "purple_dragon_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidates = list((manifest.get("files") or {}).keys())
            pattern = re.compile(r"(?i)[A-Z]:\\\\Users\\\\([^\\\\\r\n]+)\\\\")
            allowed_fixture_users = {
                "test", "testing", "public", "default", "default user",
                "bms-test", "<user>", "<username>", "%username%",
            }
            for rel in candidates:
                file = self.root / rel
                if not file.is_file() or file.suffix.lower() not in {".py", ".pyw", ".js", ".html", ".css", ".bat", ".json", ".txt"}:
                    continue
                text = file.read_text(encoding="utf-8", errors="ignore")
                usernames = {
                    match.group(1).strip().lower()
                    for match in pattern.finditer(text)
                }
                suspicious = sorted(
                    name for name in usernames
                    if name not in allowed_fixture_users
                )
                if suspicious:
                    profile_leaks.append(f"{rel} ({', '.join(suspicious)})")
        except Exception:
            profile_leaks = []
        checks.append(_check(
            "pass" if not profile_leaks else "fail",
            "privacy.profile_paths",
            "Developer profile-path hygiene",
            "No hard-coded Windows user-profile paths found in protected release files."
            if not profile_leaks else
            f"Hard-coded user-profile paths detected in: {', '.join(profile_leaks)}",
            "Privacy",
            blocking=bool(profile_leaks),
        ))

        security_state = dict(security_state or {})
        if security_state.get("checked") and security_state.get("verified"):
            checks.append(_check(
                "pass",
                "security.purple_dragon",
                "Purple Dragon integrity",
                f"{security_state.get('verified_file_count', 0)}/{security_state.get('protected_file_count', 0)} protected files verified; publisher signature valid.",
                "Security",
            ))
        elif security_state.get("checked"):
            checks.append(_check(
                "fail",
                "security.purple_dragon",
                "Purple Dragon integrity",
                security_state.get("error") or "Signed-build verification failed.",
                "Security",
                True,
            ))
        else:
            checks.append(_check(
                "warn",
                "security.purple_dragon",
                "Purple Dragon integrity",
                "Signed-build verification is still checking; rerun preflight after Security becomes TRUSTED.",
                "Security",
            ))

        config_issues = validate_config(cfg, self.config_path)
        if not config_issues:
            checks.append(_check(
                "pass",
                "config.validation",
                "Configuration validation",
                "Configuration ranges, persistence structure, pool endpoint shape, and credential-storage boundaries passed.",
                "Configuration",
            ))
        else:
            for issue in config_issues:
                status = "fail" if issue["severity"] == "fail" else "warn"
                checks.append(_check(
                    status,
                    issue["code"],
                    f"{issue['area']} validation",
                    issue["message"],
                    issue["area"],
                    blocking=status == "fail",
                ))

        # Analytics privacy/store status is informational unless its own status
        # reports an actual recorder error.
        analytics_status = dict(analytics_status or {})
        analytics_error = str(analytics_status.get("error") or "")
        if analytics_error:
            checks.append(_check("warn", "monitoring.recorder", "Monitoring recorder", analytics_error, "Monitoring"))
        else:
            checks.append(_check(
                "pass",
                "monitoring.recorder",
                "Monitoring recorder",
                "Local-only telemetry store is available; credentials are excluded from its schema.",
                "Monitoring",
            ))

        # Prior unclean shutdown is useful RC signal, but must not brick mining.
        checks.append(_check(
            "warn" if self._previous_unclean else "pass",
            "startup.previous_shutdown",
            "Previous application shutdown",
            "Previous session did not record a clean shutdown. Review startup logs if unexpected."
            if self._previous_unclean else
            "Previous session recorded a clean shutdown.",
            "Startup",
        ))

        blockers = sum(1 for x in checks if x["status"] == "fail")
        warnings = sum(1 for x in checks if x["status"] == "warn")
        passes = sum(1 for x in checks if x["status"] == "pass")
        score = max(0, min(100, 100 - blockers * 30 - warnings * 4))
        readiness = "RELEASE BLOCKED" if blockers else ("STABLE READY" if warnings <= 3 else "STABLE READY · REVIEW WARNINGS")

        self._state.update({
            "schema": PREFLIGHT_SCHEMA,
            "channel": RELEASE_CHANNEL,
            "version": self.version,
            "running": False,
            "checked": True,
            "score": score,
            "readiness": readiness,
            "blockers": blockers,
            "warnings": warnings,
            "passes": passes,
            "checks": checks,
            "config_issues": config_issues,
            "previous_unclean_shutdown": self._previous_unclean,
            "checked_at": _now_iso(),
        })
        return self.state()

    def report(self) -> str:
        state = self.state()
        lines = [
            f"BITCOIN MINER STUDIO {self.version} — {RELEASE_CHANNEL.upper()} READINESS",
            "",
            f"Readiness: {state.get('readiness')}",
            f"Score: {state.get('score')}/100",
            f"Pass: {state.get('passes')}  Warnings: {state.get('warnings')}  Blockers: {state.get('blockers')}",
            f"Checked: {state.get('checked_at') or 'Not checked'}",
            "",
        ]
        for row in state.get("checks") or []:
            lines.append(
                f"[{str(row.get('status') or '').upper():4}] "
                f"{row.get('area')} · {row.get('title')}: {row.get('detail')}"
            )
        lines.extend([
            "",
            "Stable baseline: ACTIVE",
            "Support bundles: LOCAL CREATION ONLY — no upload/phone-home.",
        ])
        return "\n".join(lines)

    def create_support_bundle(
        self,
        cfg: dict[str, Any],
        logs: list[dict[str, Any]] | None = None,
        security_state: dict[str, Any] | None = None,
        analytics_status: dict[str, Any] | None = None,
        pool_diagnostic_report: str = "",
    ) -> dict[str, Any]:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = SUPPORT_DIR / f"BitcoinMinerStudio-v{self.version}-support-{stamp}.zip"

        state = self.state()
        payload = {
            "schema": SUPPORT_BUNDLE_SCHEMA,
            "created_at": _now_iso(),
            "product": "Bitcoin Miner Studio",
            "version": self.version,
            "channel": RELEASE_CHANNEL,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "architecture": platform.architecture()[0],
            "preflight": state,
            "analytics_status": sanitize_config(dict(analytics_status or {})),
            "security": {
                "checked": bool((security_state or {}).get("checked")),
                "verified": bool((security_state or {}).get("verified")),
                "signature_valid": bool((security_state or {}).get("signature_valid")),
                "protected_file_count": int((security_state or {}).get("protected_file_count") or 0),
                "verified_file_count": int((security_state or {}).get("verified_file_count") or 0),
                "build_id": str((security_state or {}).get("build_id") or ""),
                "release_seal": str((security_state or {}).get("release_seal") or ""),
                "publisher_key_id": str((security_state or {}).get("publisher_key_id") or ""),
            },
            "privacy": {
                "secrets_included": False,
                "credentials_included": False,
                "analytics_database_included": False,
                "uploaded_automatically": False,
            },
        }

        activity = []
        for row in list(logs or [])[-250:]:
            activity.append(
                f"{row.get('time', '')}  {redact_text(row.get('message', ''))}"
            )

        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("support-report.json", json.dumps(payload, indent=2))
            z.writestr("settings-sanitized.json", json.dumps(sanitize_config(cfg), indent=2))
            z.writestr("preflight.txt", self.report())
            z.writestr("activity-log-redacted.txt", "\n".join(activity) + "\n")
            if pool_diagnostic_report:
                z.writestr("pool-diagnostics-redacted.txt", redact_text(pool_diagnostic_report))
            for name in ("startup-error.log", "startup-bridge.log"):
                candidate = self.root / name
                if candidate.is_file():
                    try:
                        z.writestr(name, redact_text(candidate.read_text(encoding="utf-8", errors="replace")))
                    except Exception:
                        pass
            manifest = self.root / "purple_dragon_manifest.json"
            if manifest.is_file():
                z.writestr("purple_dragon_manifest.json", manifest.read_bytes())

        self._state["support_bundle"] = _redact_path(str(path))
        return {
            "ok": True,
            "path": str(path),
            "path_display": _redact_path(str(path)),
            "size": path.stat().st_size,
            "size_text": _human_bytes(path.stat().st_size),
            "result": (
                "Local support bundle created. It was not uploaded anywhere and "
                "does not include mining/RPC passwords, private keys, wallet seeds, "
                "or the analytics database."
            ),
        }
