"""Bitcoin Miner Studio v1.8.0 — Diagnostics & Support Center.

Read-only operational diagnostics and local support packaging.

Safety boundaries:
- never starts/stops mining;
- never switches pools or changes ASIC settings;
- never changes Bitcoin Core configuration or submits blocks;
- never reads credential-backend secrets;
- never uploads telemetry or support bundles;
- support artifacts are privacy-sanitized and created locally only.
"""
from __future__ import annotations

import importlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from release_candidate import redact_text, sanitize_config, validate_config

DIAGNOSTICS_SCHEMA = 3
SUPPORT_BUNDLE_SCHEMA = 2
DEFAULT_APP_DATA_DIR = Path.home() / ".bitcoin-miner-studio"

_ERROR_RE = re.compile(r"\b(error|failed|failure|exception|traceback|fatal|crash)\b", re.I)
_DIAGNOSTICS_SUMMARY_RE = re.compile(r"^Diagnostics\s+(?:quick|full):", re.I)
_ZERO_ERROR_COUNT_RE = re.compile(r"\b0\s+(?:error|failure)(?:\(s\)|s)?\b", re.I)


def _activity_error_like(message: str) -> bool:
    """Return True only for actionable error-like activity messages.

    Diagnostics emits its own score summary into the activity log. Those summaries
    can contain text such as ``0 failure(s)`` and must never recursively create an
    app.recent_errors warning. Zero-count error/failure phrases are also ignored.
    """
    text = str(message or "").strip()
    if not text or _DIAGNOSTICS_SUMMARY_RE.match(text):
        return False
    text = _ZERO_ERROR_COUNT_RE.sub("", text)
    return bool(_ERROR_RE.search(text))


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
    home = str(Path.home())
    if home and home in text:
        text = text.replace(home, "%USERPROFILE%")
    return text


def _status_rank(value: str) -> int:
    return {"info": 0, "pass": 1, "warn": 2, "fail": 3}.get(str(value or "").lower(), 0)


def _check(
    status: str,
    code: str,
    title: str,
    detail: str,
    category: str,
    remediation: str = "",
    *,
    critical: bool = False,
) -> dict[str, Any]:
    return {
        "status": str(status),
        "code": str(code),
        "title": str(title),
        "detail": str(detail),
        "category": str(category),
        "remediation": str(remediation),
        "critical": bool(critical),
    }


def _safe_bool(value: Any) -> bool:
    try:
        return bool(value)
    except Exception:
        return False


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


class DiagnosticsSupportCenter:
    """Collect read-only health evidence and build local sanitized support bundles."""

    def __init__(
        self,
        root: Path,
        version: str,
        *,
        app_data_dir: Path | None = None,
    ):
        self.root = Path(root).resolve()
        self.version = str(version)
        self.app_data_dir = Path(app_data_dir or DEFAULT_APP_DATA_DIR)
        self.support_dir = self.app_data_dir / "support" / "diagnostics"
        self._state: dict[str, Any] = {
            "schema": DIAGNOSTICS_SCHEMA,
            "version": self.version,
            "running": False,
            "checked": False,
            "mode": "quick",
            "health": "NOT CHECKED",
            "score": 0,
            "passes": 0,
            "warnings": 0,
            "failures": 0,
            "info": 0,
            "total_checks": 0,
            "checked_at": "",
            "duration_ms": 0,
            "checks": [],
            "issues": [],
            "categories": [],
            "system": self._system_snapshot(),
            "last_bundle": "",
            "last_bundle_size": "",
            "privacy": self._privacy_state(),
        }

    @staticmethod
    def _privacy_state() -> dict[str, Any]:
        return {
            "local_only": True,
            "automatic_upload": False,
            "credentials_included": False,
            "private_keys_included": False,
            "wallet_seeds_included": False,
            "analytics_database_included": False,
            "redaction_enabled": True,
        }

    def _system_snapshot(self) -> dict[str, Any]:
        return {
            "product": "Bitcoin Miner Studio",
            "version": self.version,
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "architecture": platform.architecture()[0],
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "cpu_cores": int(os.cpu_count() or 1),
            "app_root": _redact_path(str(self.root)),
            "app_data": _redact_path(str(self.app_data_dir)),
        }

    def state(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state))

    def _writable_check(self, path: Path) -> tuple[bool, str]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="bms-diag-", dir=path, delete=True) as f:
                f.write(b"ok")
                f.flush()
            return True, _redact_path(str(path))
        except Exception as exc:
            return False, redact_text(f"{path}: {exc}")

    def _runtime_checks(self, checks: list[dict[str, Any]], mode: str) -> None:
        py_ok = sys.version_info >= (3, 11)
        checks.append(_check(
            "pass" if py_ok else "fail",
            "runtime.python",
            "Python runtime",
            f"{platform.python_implementation()} {platform.python_version()} · {platform.architecture()[0]}",
            "Runtime",
            "Install/use Python 3.11 or newer for this source release." if not py_ok else "",
            critical=not py_ok,
        ))

        arch = str(platform.architecture()[0])
        checks.append(_check(
            "pass" if "64" in arch else "warn",
            "runtime.architecture",
            "64-bit runtime",
            f"Detected {arch} Python runtime.",
            "Runtime",
            "Use a 64-bit Python runtime on Windows for the supported configuration." if "64" not in arch else "",
        ))

        for module_name, title, critical in (
            ("webview", "WebView runtime", True),
            ("cryptography", "Cryptography runtime", True),
        ):
            try:
                module = importlib.import_module(module_name)
                version = getattr(module, "__version__", "available")
                checks.append(_check("pass", f"runtime.{module_name}", title, f"{module_name} {version} is importable.", "Runtime"))
            except Exception as exc:
                checks.append(_check(
                    "fail", f"runtime.{module_name}", title,
                    f"{module_name} is unavailable: {redact_text(str(exc))}", "Runtime",
                    f"Reinstall project dependencies, then rerun {title.lower()} diagnostics.", critical=critical,
                ))

        cpu_count = int(os.cpu_count() or 0)
        checks.append(_check(
            "pass" if cpu_count > 0 else "warn",
            "runtime.cpu",
            "CPU availability",
            f"{cpu_count or 'Unknown'} logical processor(s) detected.",
            "Runtime",
            "Restart the application and verify Windows can enumerate the CPU." if cpu_count <= 0 else "",
        ))

        if mode == "full":
            required = (
                "main.py", "launch.pyw", "webview_app.py", "diagnostics_center.py",
                "ui/index.html", "ui/styles.css", "ui/script.js",
                "purple_dragon_manifest.json", "release_info.json", "update_release_center.py",
                "assets/BitcoinMinerStudio.ico", "assets/PurpleDragonFoundationLogo.png",
            )
            missing = [name for name in required if not (self.root / name).is_file()]
            checks.append(_check(
                "pass" if not missing else "fail",
                "runtime.app_files",
                "Core application files",
                "Required Diagnostics/GUI/security files are present." if not missing else f"Missing: {', '.join(missing)}",
                "Runtime",
                "Restore the release from a known-good archive; do not copy individual missing protected files from another version." if missing else "",
                critical=bool(missing),
            ))

    def _storage_checks(self, checks: list[dict[str, Any]], mode: str) -> None:
        writable, detail = self._writable_check(self.app_data_dir)
        checks.append(_check(
            "pass" if writable else "fail",
            "storage.app_data",
            "Application data directory",
            f"Writable: {detail}" if writable else detail,
            "Storage",
            "Check folder permissions and available disk space for the current Windows account." if not writable else "",
            critical=not writable,
        ))

        support_ok, support_detail = self._writable_check(self.support_dir)
        checks.append(_check(
            "pass" if support_ok else "fail",
            "storage.support",
            "Local support directory",
            f"Writable: {support_detail}" if support_ok else support_detail,
            "Storage",
            "Allow Bitcoin Miner Studio to write its local support folder, then retry bundle creation." if not support_ok else "",
        ))

        try:
            usage = shutil.disk_usage(self.app_data_dir)
            free_gb = usage.free / (1024 ** 3)
            status = "pass" if free_gb >= 1.0 else ("warn" if free_gb >= 0.25 else "fail")
            checks.append(_check(
                status,
                "storage.free_space",
                "Free disk space",
                f"{free_gb:.2f} GB free on the application-data volume.",
                "Storage",
                "Free at least 1 GB on the application-data volume for logs, history and support bundles." if status != "pass" else "",
            ))
        except Exception as exc:
            checks.append(_check("warn", "storage.free_space", "Free disk space", f"Could not measure free space: {redact_text(str(exc))}", "Storage", "Check free disk space manually."))

        if mode == "full":
            startup_logs = [name for name in ("startup-error.log", "startup-bridge.log") if (self.root / name).is_file()]
            checks.append(_check(
                "info" if startup_logs else "pass",
                "storage.startup_logs",
                "Startup diagnostic logs",
                f"Available for support: {', '.join(startup_logs)}" if startup_logs else "No startup-error log is currently present.",
                "Storage",
            ))

    def _security_checks(self, checks: list[dict[str, Any]], security: dict[str, Any]) -> None:
        checked = _safe_bool(security.get("checked"))
        verified = _safe_bool(security.get("verified"))
        signature_valid = _safe_bool(security.get("signature_valid"))
        controls = _safe_bool(security.get("critical_actions_allowed"))
        protected = _safe_int(security.get("protected_file_count"))
        verified_files = _safe_int(security.get("verified_file_count"))

        if checked and verified and signature_valid and controls:
            checks.append(_check(
                "pass", "security.trust", "Purple Dragon trust",
                f"TRUSTED · publisher signature VALID · {verified_files}/{protected} protected files verified.",
                "Security",
            ))
        elif checked:
            checks.append(_check(
                "fail", "security.trust", "Purple Dragon trust",
                str(security.get("status") or "Build trust verification failed."),
                "Security",
                "Open Purple Dragon Security Center, verify the build, and restore/re-sign the exact release if protected files were intentionally changed.",
                critical=True,
            ))
        else:
            checks.append(_check(
                "warn", "security.trust", "Purple Dragon trust",
                "Security verification has not completed yet.", "Security",
                "Open Purple Dragon Security Center and run Verify Build Now.",
            ))

        private_key_files = []
        for candidate in self.root.glob("*.pem"):
            try:
                if "PRIVATE KEY" in candidate.read_text(encoding="utf-8", errors="ignore"):
                    private_key_files.append(candidate.name)
            except Exception:
                pass
        checks.append(_check(
            "pass" if not private_key_files else "fail",
            "security.private_key",
            "Publisher private-key isolation",
            "No publisher private key is embedded in the application directory." if not private_key_files else f"Private key material detected: {', '.join(private_key_files)}",
            "Security",
            "Remove publisher private keys from the application/release directory and rotate the key if it has been distributed." if private_key_files else "",
            critical=bool(private_key_files),
        ))

    def _configuration_checks(self, checks: list[dict[str, Any]], cfg: dict[str, Any]) -> None:
        issues = validate_config(dict(cfg or {}))
        if not issues:
            checks.append(_check("pass", "config.validation", "Configuration validation", "Current settings passed range, type and privacy checks.", "Configuration"))
            return
        for issue in issues:
            severity = str(issue.get("severity") or "warn").lower()
            status = "fail" if severity == "fail" else "warn"
            checks.append(_check(
                status,
                str(issue.get("code") or "config.issue"),
                str(issue.get("area") or "Configuration"),
                str(issue.get("message") or "Configuration issue detected."),
                "Configuration",
                "Open the related settings page, correct the highlighted configuration, save, then rerun diagnostics.",
            ))

    def _core_checks(self, checks: list[dict[str, Any]], core: dict[str, Any], setup: dict[str, Any]) -> None:
        connected = _safe_bool(core.get("connected"))
        process_running = _safe_bool(setup.get("process_running"))
        configured = bool(str(setup.get("data_dir") or "").strip() or str(setup.get("executable") or "").strip())
        rpc_listening = _safe_bool(setup.get("rpc_listening"))

        if connected:
            height = core.get("blocks", core.get("height", "—"))
            network = core.get("chain", setup.get("network", "unknown"))
            checks.append(_check("pass", "core.rpc", "Bitcoin Core RPC", f"Connected · network {network} · height {height}.", "Bitcoin Core"))
        elif process_running or configured:
            detail = str(core.get("error") or "Bitcoin Core is configured but RPC is not currently connected.")
            checks.append(_check(
                "warn", "core.rpc", "Bitcoin Core RPC", redact_text(detail), "Bitcoin Core",
                "Open Bitcoin Core Center, confirm the selected data directory/network and test RPC authentication/connectivity.",
            ))
        else:
            checks.append(_check(
                "info", "core.rpc", "Bitcoin Core RPC",
                "Bitcoin Core is not configured. This is valid for pool-only/benchmark/Academy use.",
                "Bitcoin Core",
            ))

        data_dir = str(setup.get("data_dir") or "").strip()
        if data_dir:
            exists = _safe_bool(setup.get("data_dir_exists")) or Path(os.path.expandvars(os.path.expanduser(data_dir))).is_dir()
            checks.append(_check(
                "pass" if exists else "warn",
                "core.data_dir", "Bitcoin Core data directory",
                "Configured data directory exists." if exists else "Configured data directory could not be found.",
                "Bitcoin Core",
                "Use Choose Data Folder in Bitcoin Core Center and pin the actual active data directory." if not exists else "",
            ))
        if process_running and not rpc_listening and not connected:
            checks.append(_check(
                "warn", "core.rpc_listener", "Bitcoin Core RPC listener",
                "Bitcoin Core appears to be running but the configured RPC listener is not reachable.",
                "Bitcoin Core",
                "Verify server=1/RPC configuration, selected network ports and local firewall rules.",
            ))

    def _pool_checks(self, checks: list[dict[str, Any]], miner: dict[str, Any], pool: dict[str, Any], cfg: dict[str, Any]) -> None:
        running = _safe_bool(miner.get("running"))
        connected = _safe_bool(miner.get("connected"))
        authorized = _safe_bool(miner.get("authorized"))
        configured_url = str(cfg.get("pool_url") or "").strip()
        placeholder = (not configured_url) or ("example.com" in configured_url.lower())

        if running:
            if connected and authorized:
                checks.append(_check("pass", "pool.session", "Pool mining session", "Miner is connected and authorized to the active pool endpoint.", "Pool"))
            else:
                checks.append(_check(
                    "fail", "pool.session", "Pool mining session",
                    "Mining is running but pool connectivity/authorization is incomplete.", "Pool",
                    "Stop the session if it is repeatedly failing, then use Pool PowerTools to test endpoints and verify worker credentials.",
                ))
        elif placeholder:
            checks.append(_check("info", "pool.session", "Pool configuration", "No production pool endpoint is configured. This is valid for solo/benchmark/Academy workflows.", "Pool"))
        else:
            checks.append(_check("pass", "pool.session", "Pool configuration", "A non-placeholder pool endpoint is configured; miner is currently idle.", "Pool"))

        diagnostics = dict(pool or {})
        if diagnostics.get("running"):
            checks.append(_check("info", "pool.diagnostics", "Pool endpoint diagnostics", "Pool endpoint diagnostics are currently running.", "Pool"))
        else:
            endpoints = list(diagnostics.get("endpoints") or [])
            if endpoints:
                failures = sum(1 for row in endpoints if not _safe_bool(row.get("ok")))
                status = "warn" if failures else "pass"
                checks.append(_check(
                    status, "pool.diagnostics", "Pool endpoint diagnostics",
                    f"{len(endpoints)-failures}/{len(endpoints)} tested endpoint(s) passed the latest diagnostic run.", "Pool",
                    "Run Test All Endpoints in Pool PowerTools and review DNS/TLS/Stratum errors." if failures else "",
                ))
            else:
                checks.append(_check("info", "pool.diagnostics", "Pool endpoint diagnostics", "No current endpoint diagnostic result is available.", "Pool"))

    def _asic_checks(self, checks: list[dict[str, Any]], devices: list[dict[str, Any]], solo: dict[str, Any]) -> None:
        devices = list(devices or [])
        if not devices:
            checks.append(_check("info", "asic.devices", "ASIC fleet", "No confirmed ASIC devices are currently loaded. This is valid for CPU/benchmark/pool-only use.", "ASIC"))
        else:
            offline = 0
            hot = 0
            for row in devices:
                status_text = str(row.get("status") or row.get("state") or "").lower()
                if any(token in status_text for token in ("offline", "error", "unreachable", "failed")):
                    offline += 1
                temp = _safe_float(row.get("temperature", row.get("temp", 0)))
                if temp >= 85:
                    hot += 1
            if offline or hot:
                checks.append(_check(
                    "warn", "asic.devices", "ASIC fleet",
                    f"{len(devices)} device(s) loaded · {offline} offline/error · {hot} at or above 85°C.", "ASIC",
                    "Open ASIC Control, refresh the fleet and inspect device power/network/cooling before changing settings.",
                ))
            else:
                checks.append(_check("pass", "asic.devices", "ASIC fleet", f"{len(devices)} loaded device(s); no obvious offline/error or ≥85°C condition in the current snapshot.", "ASIC"))

        solo_running = _safe_bool(solo.get("running"))
        if solo_running:
            clients = _safe_int(solo.get("clients", solo.get("client_count", 0)))
            checks.append(_check("pass", "asic.solo_bridge", "ASIC Solo Bridge", f"Private-LAN solo bridge is running with {clients} client(s).", "ASIC"))
        else:
            checks.append(_check("info", "asic.solo_bridge", "ASIC Solo Bridge", "Solo bridge is stopped.", "ASIC"))

    def _monitoring_checks(self, checks: list[dict[str, Any]], analytics: dict[str, Any]) -> None:
        enabled = _safe_bool(analytics.get("enabled", True))
        running = _safe_bool(analytics.get("running"))
        if enabled and running:
            checks.append(_check("pass", "monitoring.analytics", "Monitoring recorder", "Local analytics recorder is enabled and running.", "Monitoring"))
        elif enabled:
            checks.append(_check(
                "warn", "monitoring.analytics", "Monitoring recorder",
                "Local analytics is enabled but the recorder does not report running.", "Monitoring",
                "Open Monitoring, verify storage permissions and restart the recorder/application.",
            ))
        else:
            checks.append(_check("info", "monitoring.analytics", "Monitoring recorder", "Local analytics recording is disabled by configuration.", "Monitoring"))

    def _architecture_checks(self, checks: list[dict[str, Any]], architecture: dict[str, Any]) -> None:
        architecture = dict(architecture or {})
        if not architecture:
            checks.append(_check(
                "warn", "architecture.registry", "v2 service architecture",
                "The BMS-ARCH-2 service registry is not available in this diagnostics snapshot.", "Application",
                "Restart Bitcoin Miner Studio and rerun diagnostics. If this repeats, create a support bundle.",
            ))
            return
        arch_id = str(architecture.get("architecture") or "")
        services = list(architecture.get("services") or [])
        errors = _safe_int(architecture.get("errors"))
        degraded = _safe_int(architecture.get("degraded"))
        critical = _safe_int(architecture.get("critical_issues"))
        if arch_id != "BMS-ARCH-2":
            checks.append(_check(
                "fail", "architecture.version", "Application architecture",
                f"Unexpected architecture identifier: {arch_id or 'missing'}.", "Application",
                "Verify this release with Purple Dragon Security and reinstall the complete trusted v2.0.1 package if required.",
                critical=True,
            ))
        elif critical or errors:
            checks.append(_check(
                "fail", "architecture.services", "v2 service architecture",
                f"{len(services)} registered service(s) · {errors} error(s) · {degraded} degraded · {critical} critical issue(s).", "Application",
                "Review the v2 Service Architecture panel and the related subsystem diagnostics before continuing critical operations.",
            ))
        elif degraded:
            checks.append(_check(
                "warn", "architecture.services", "v2 service architecture",
                f"{len(services)} registered service(s) · {degraded} degraded service(s).", "Application",
                "Review the v2 Service Architecture panel for the degraded subsystem.",
            ))
        else:
            checks.append(_check(
                "pass", "architecture.services", "v2 service architecture",
                f"BMS-ARCH-2 active · {len(services)} registered service(s) · no registry errors.", "Application",
            ))

    def _application_checks(self, checks: list[dict[str, Any]], release: dict[str, Any], logs: list[dict[str, Any]]) -> None:
        if _safe_bool(release.get("previous_unclean_shutdown")):
            checks.append(_check(
                "warn", "app.unclean_shutdown", "Previous application shutdown",
                "The previous Bitcoin Miner Studio session did not record a clean shutdown.", "Application",
                "Review recent activity/startup logs. If this repeats, create a support bundle immediately after reproducing the issue.",
            ))
        else:
            checks.append(_check("pass", "app.unclean_shutdown", "Previous application shutdown", "No previous unclean-session marker is currently reported.", "Application"))

        recent = list(logs or [])[-100:]
        error_rows = [row for row in recent if _activity_error_like(row.get("message"))]
        if error_rows:
            checks.append(_check(
                "warn", "app.recent_errors", "Recent activity errors",
                f"{len(error_rows)} error/failure-like message(s) detected in the last {len(recent)} activity entries.", "Application",
                "Review Logs and the issue list below; create a support bundle if the same error repeats.",
            ))
        else:
            checks.append(_check("pass", "app.recent_errors", "Recent activity errors", f"No error/failure keywords detected in the last {len(recent)} activity entries.", "Application"))

        if _safe_bool(release.get("checked")):
            blockers = _safe_int(release.get("blockers"))
            warnings = _safe_int(release.get("warnings"))
            status = "fail" if blockers else ("warn" if warnings else "pass")
            checks.append(_check(
                status, "app.release_readiness", "Release readiness",
                f"{release.get('readiness') or 'Checked'} · {blockers} blocker(s) · {warnings} warning(s).", "Application",
                "Open Release Readiness and review blocking/warning gates." if blockers or warnings else "",
            ))
        else:
            checks.append(_check("info", "app.release_readiness", "Release readiness", "Stable release preflight has not been run in this session.", "Application"))

    @staticmethod
    def _category_summary(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        categories: dict[str, list[dict[str, Any]]] = {}
        for row in checks:
            categories.setdefault(str(row.get("category") or "Other"), []).append(row)
        result = []
        preferred = ["Runtime", "Security", "Storage", "Configuration", "Bitcoin Core", "Pool", "ASIC", "Monitoring", "Application"]
        order = {name: idx for idx, name in enumerate(preferred)}
        for category, rows in sorted(categories.items(), key=lambda item: order.get(item[0], 999)):
            highest = max((_status_rank(row.get("status")) for row in rows), default=0)
            state = {3: "FAIL", 2: "WARN", 1: "PASS", 0: "INFO"}.get(highest, "INFO")
            result.append({
                "category": category,
                "state": state,
                "checks": len(rows),
                "passes": sum(1 for row in rows if row.get("status") == "pass"),
                "warnings": sum(1 for row in rows if row.get("status") == "warn"),
                "failures": sum(1 for row in rows if row.get("status") == "fail"),
                "info": sum(1 for row in rows if row.get("status") == "info"),
            })
        return result

    def run(self, snapshot: dict[str, Any], mode: str = "quick") -> dict[str, Any]:
        started = time.perf_counter()
        mode = "full" if str(mode or "quick").lower() == "full" else "quick"
        self._state["running"] = True
        checks: list[dict[str, Any]] = []
        snapshot = dict(snapshot or {})
        cfg = dict(snapshot.get("cfg") or {})

        try:
            self._runtime_checks(checks, mode)
            self._storage_checks(checks, mode)
            self._security_checks(checks, dict(snapshot.get("security") or {}))
            self._configuration_checks(checks, cfg)
            self._core_checks(checks, dict(snapshot.get("core") or {}), dict(snapshot.get("core_setup") or {}))
            self._pool_checks(checks, dict(snapshot.get("miner") or {}), dict(snapshot.get("pool_diagnostics") or {}), cfg)
            self._asic_checks(checks, list(snapshot.get("asic_devices") or []), dict(snapshot.get("asic_solo") or {}))
            self._monitoring_checks(checks, dict(snapshot.get("analytics") or {}))
            self._architecture_checks(checks, dict(snapshot.get("architecture") or {}))
            self._application_checks(checks, dict(snapshot.get("release") or {}), list(snapshot.get("logs") or []))

            passes = sum(1 for row in checks if row["status"] == "pass")
            warnings = sum(1 for row in checks if row["status"] == "warn")
            failures = sum(1 for row in checks if row["status"] == "fail")
            info = sum(1 for row in checks if row["status"] == "info")
            critical_failures = sum(1 for row in checks if row["status"] == "fail" and row.get("critical"))
            scored = max(1, passes + warnings + failures)
            score = max(0, min(100, round((passes + warnings * 0.55) / scored * 100)))
            if critical_failures:
                health = "CRITICAL"
            elif failures:
                health = "DEGRADED"
            elif warnings:
                health = "ATTENTION"
            else:
                health = "HEALTHY"

            issues = [row for row in checks if row["status"] in {"warn", "fail"}]
            issues.sort(key=lambda row: (_status_rank(row["status"]), bool(row.get("critical"))), reverse=True)
            self._state.update({
                "schema": DIAGNOSTICS_SCHEMA,
                "version": self.version,
                "running": False,
                "checked": True,
                "mode": mode,
                "health": health,
                "score": score,
                "passes": passes,
                "warnings": warnings,
                "failures": failures,
                "info": info,
                "total_checks": len(checks),
                "checked_at": _now_iso(),
                "duration_ms": max(1, round((time.perf_counter() - started) * 1000)),
                "checks": checks,
                "issues": issues,
                "categories": self._category_summary(checks),
                "system": self._system_snapshot(),
                "privacy": self._privacy_state(),
            })
        except Exception as exc:
            self._state.update({
                "running": False,
                "checked": True,
                "health": "CRITICAL",
                "failures": 1,
                "checked_at": _now_iso(),
                "duration_ms": max(1, round((time.perf_counter() - started) * 1000)),
                "checks": checks + [_check("fail", "diagnostics.internal", "Diagnostics engine", redact_text(str(exc)), "Application", "Restart Bitcoin Miner Studio and rerun diagnostics.", critical=True)],
            })
            self._state["issues"] = [row for row in self._state["checks"] if row.get("status") in {"warn", "fail"}]
            self._state["categories"] = self._category_summary(self._state["checks"])
            self._state["total_checks"] = len(self._state["checks"])
        return self.state()

    def report(self) -> str:
        state = self.state()
        lines = [
            "PURPLE DRAGON DIAGNOSTICS REPORT",
            "",
            "Product: Bitcoin Miner Studio",
            f"Version: {self.version}",
            f"Diagnostics schema: {DIAGNOSTICS_SCHEMA}",
            f"Mode: {str(state.get('mode') or 'quick').upper()}",
            f"Health: {state.get('health')}",
            f"Score: {state.get('score')}/100",
            f"Checks: {state.get('total_checks')} · Pass {state.get('passes')} · Warnings {state.get('warnings')} · Failures {state.get('failures')} · Info {state.get('info')}",
            f"Checked: {state.get('checked_at') or 'Not checked'}",
            "",
        ]
        for row in state.get("checks") or []:
            lines.append(f"[{str(row.get('status') or '').upper():4}] {row.get('category')} · {row.get('title')}: {redact_text(row.get('detail', ''))}")
            if row.get("remediation") and row.get("status") in {"warn", "fail"}:
                lines.append(f"       Next step: {redact_text(row.get('remediation', ''))}")
        lines.extend([
            "",
            "Privacy: diagnostics are local-only. Support bundles are never uploaded automatically.",
            "Credentials/private keys/wallet seeds and the analytics database are excluded from support bundles.",
        ])
        return "\n".join(lines)

    def create_support_bundle(
        self,
        snapshot: dict[str, Any],
        *,
        include_activity_log: bool = True,
        include_settings: bool = True,
    ) -> dict[str, Any]:
        snapshot = dict(snapshot or {})
        if not self._state.get("checked"):
            self.run(snapshot, "quick")
        self.support_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = self.support_dir / f"BitcoinMinerStudio-v{self.version}-diagnostics-{stamp}.zip"

        security = dict(snapshot.get("security") or {})
        release = dict(snapshot.get("release") or {})
        architecture = dict(snapshot.get("architecture") or {})
        architecture_safe = {
            "architecture": architecture.get("architecture"),
            "overall": architecture.get("overall"),
            "registered": _safe_int(architecture.get("registered")),
            "running": _safe_int(architecture.get("running")),
            "degraded": _safe_int(architecture.get("degraded")),
            "errors": _safe_int(architecture.get("errors")),
            "critical_issues": _safe_int(architecture.get("critical_issues")),
            "services": [
                {
                    "id": row.get("id"),
                    "label": row.get("label"),
                    "category": row.get("category"),
                    "critical": bool(row.get("critical")),
                    "state": row.get("state"),
                }
                for row in list(architecture.get("services") or [])
                if isinstance(row, dict)
            ],
        }
        bundle_meta = {
            "schema": SUPPORT_BUNDLE_SCHEMA,
            "created_at": _now_iso(),
            "product": "Bitcoin Miner Studio",
            "version": self.version,
            "diagnostics": self.state(),
            "system": self._system_snapshot(),
            "privacy": self._privacy_state(),
            "included": {
                "activity_log": bool(include_activity_log),
                "sanitized_settings": bool(include_settings),
                "startup_logs_if_present": True,
                "security_summary": True,
                "release_readiness": True,
                "pool_diagnostics": True,
            },
        }

        security_summary = {
            "checked": _safe_bool(security.get("checked")),
            "verified": _safe_bool(security.get("verified")),
            "signature_valid": _safe_bool(security.get("signature_valid")),
            "critical_actions_allowed": _safe_bool(security.get("critical_actions_allowed")),
            "protected_file_count": _safe_int(security.get("protected_file_count")),
            "verified_file_count": _safe_int(security.get("verified_file_count")),
            "build_id": str(security.get("build_id") or ""),
            "release_seal": str(security.get("release_seal") or ""),
            "publisher_key_id": str(security.get("publisher_key_id") or ""),
        }

        activity = []
        for row in list(snapshot.get("logs") or [])[-250:]:
            activity.append(f"{row.get('time', '')}  {redact_text(row.get('message', ''))}")

        pool_report = str(snapshot.get("pool_diagnostic_report") or "")
        release_report = str(snapshot.get("release_report") or "")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.txt", (
                "Bitcoin Miner Studio Diagnostics & Support Center\n"
                f"Version {self.version}\n\n"
                "This bundle was created locally and was not uploaded automatically.\n"
                "Mining/RPC passwords, credential-backend secrets, publisher private keys, wallet seeds,\n"
                "and the analytics SQLite database are intentionally excluded.\n"
            ))
            z.writestr("diagnostics-report.txt", self.report())
            z.writestr("architecture-summary.json", json.dumps(architecture_safe, indent=2))
            z.writestr("diagnostics.json", json.dumps(bundle_meta, indent=2))
            z.writestr("system.json", json.dumps(self._system_snapshot(), indent=2))
            z.writestr("security-summary.json", json.dumps(security_summary, indent=2))
            if include_settings:
                z.writestr("settings-sanitized.json", json.dumps(sanitize_config(dict(snapshot.get("cfg") or {})), indent=2))
            if include_activity_log:
                z.writestr("activity-log-redacted.txt", "\n".join(activity) + "\n")
            if release_report:
                z.writestr("release-readiness.txt", redact_text(release_report))
            elif release:
                z.writestr("release-readiness.json", json.dumps(sanitize_config(release), indent=2))
            if pool_report:
                z.writestr("pool-diagnostics-redacted.txt", redact_text(pool_report))
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

        size = path.stat().st_size
        with zipfile.ZipFile(path, "r") as verify_zip:
            entry_count = len(verify_zip.namelist())
        self._state["last_bundle"] = _redact_path(str(path))
        self._state["last_bundle_size"] = _human_bytes(size)
        return {
            "ok": True,
            "path": str(path),
            "path_display": _redact_path(str(path)),
            "size": size,
            "size_text": _human_bytes(size),
            "entries": entry_count,
            "result": (
                "Diagnostics support bundle created locally. It was not uploaded anywhere. "
                "Credential secrets, publisher private keys, wallet seeds and the analytics database are excluded."
            ),
            "diagnostics": self.state(),
        }
