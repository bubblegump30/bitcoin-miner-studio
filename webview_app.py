import json
import os
import subprocess
import sys
import threading
import traceback
import time
import webbrowser
from pathlib import Path

from config import CONFIG_FILE, load_config, save_config
from app_runtime import RuntimeContext
from app_events import LocalEventBus
from service_registry import ServiceRegistry
from workspace_manager import WorkspaceManager
from api_contract import API_SCHEMA as BRIDGE_API_SCHEMA, EXPOSED_API_METHODS, contract_snapshot
from connections import test_stratum
from pool_powertools import PoolDiagnosticsController, normalize_endpoints, pool_health_score, diagnostic_report
from pool_profiles import PoolProfileStore, normalize_failover_policy, policy_for, policy_options, profile_to_pool_config
from analytics_monitor import AnalyticsStore
from release_candidate import ReleaseCandidateManager, RELEASE_CHANNEL
from diagnostics_center import DiagnosticsSupportCenter
from update_release_center import UpdateReleaseCenter
from ui_theme import normalize_ui_theme, ui_theme_options
from branding import DEFAULT_COINBASE_TAG, PAYPAL_SUPPORT_LABEL, PAYPAL_SUPPORT_URL, PUBLISHER_NAME
from mining_assistant import build_mining_assistant_snapshot, normalize_goal
from profitability_center import block_subsidy_for_height, default_profitability_inputs, profitability_snapshot
from hardware_compatibility import compatibility_snapshot, sanitized_report
from windows_tray import WindowsTrayManager, build_tray_status, normalize_tray_settings
from bitcoin_core import (
    BitcoinCoreRPCError,
    disconnected_snapshot,
    fetch_core_snapshot,
    get_best_block_hash,
    snapshot_report,
    submit_block,
    validate_block_proposal,
)
from block_template import fetch_block_template, template_for_ui, template_report, unavailable_template
from coinbase_builder import (CoinbaseError, build_coinbase_transaction, coinbase_report, decode_payout_address, unavailable_coinbase)
from core_setup import (
    auto_config_values,
    detect_bitcoin_core,
    detection_report,
    recommended_config_snippet,
    resolve_rpc_credentials,
    validate_core_executable,
    launch_bitcoin_core,
    core_data_dir_guard,
)
from credentials import POOL_TARGET, RPC_TARGET, backend_name, delete_secret, pool_profile_target, read_secret, write_secret
from miner_engine import BenchmarkEngine
from benchmark_lab import BenchmarkLabController
from mining_academy import MiningAcademy
from solo_miner import SoloMiningEngine, hash_header, prepare_solo_work, search_nonce_batch, solo_mining_report
from block_submission import (
    archive_candidate,
    assemble_candidate_block,
    assembly_for_ui,
    assembly_report,
    unavailable_submission_state,
)
from purple_dragon_security import checking_state, verify_integrity, provenance_report, security_policy
from regtest_lab import RegtestLab, RegtestLabController, default_lab_dir
from asic_solo_bridge import (
    AsicSoloBridge,
    DEFAULT_SHARE_DIFFICULTY as ASIC_SOLO_DEFAULT_DIFFICULTY,
    detect_private_lan_ip,
    validate_bridge_bind_ip,
)
from stratum_miner import StratumMiner
from local_test_pool import LocalStratumTestPool
from fleet_monitor import FleetMonitor
from asic_manager import (
    default_private_cidr,
    discover_devices,
    ensure_private_host,
    query_device,
    classify_probe,
    is_confirmed_asic,
    restart_miner,
    switch_pool,
    assign_pool,
)

APP_NAME = "Bitcoin Miner Studio"
PAYPAL_DONATION_URL = PAYPAL_SUPPORT_URL
VERSION = "2.0.1"



APP_ICON_RELATIVE = Path("assets") / "BitcoinMinerStudio.ico"


def _set_windows_native_icon(window_title: str, icon_path: Path, timeout: float = 8.0) -> bool:
    """Apply the official ICO to the native pywebview window."""
    if sys.platform != "win32" or not Path(icon_path).is_file():
        return False

    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False

    user32 = ctypes.windll.user32
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010
    WM_SETICON = 0x0080
    ICON_SMALL = 0
    ICON_BIG = 1

    try:
        user32.LoadImageW.restype = wintypes.HANDLE
        big_icon = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        small_icon = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if not big_icon and not small_icon:
            return False
    except Exception:
        return False

    current_pid = os.getpid()
    deadline = time.monotonic() + max(0.5, float(timeout))
    found = {"hwnd": None}
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def enum_callback(hwnd, _lparam):
        try:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) != current_pid:
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if title == window_title or title.startswith(APP_NAME):
                found["hwnd"] = hwnd
                return False
        except Exception:
            return True
        return True

    while time.monotonic() < deadline:
        try:
            found["hwnd"] = None
            callback = WNDENUMPROC(enum_callback)
            user32.EnumWindows(callback, 0)
            hwnd = found["hwnd"]
            if hwnd:
                if big_icon:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big_icon)
                if small_icon:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small_icon)
                return True
        except Exception:
            pass
        time.sleep(0.10)

    return False


def _schedule_windows_native_icon(window_title: str, icon_path: Path) -> None:
    if sys.platform != "win32":
        return
    threading.Thread(
        target=_set_windows_native_icon,
        args=(window_title, icon_path),
        name="BitcoinMinerStudioIcon",
        daemon=True,
    ).start()


def format_hashrate(value):
    value = float(value or 0)
    units = [(1e18, "EH/s"), (1e15, "PH/s"), (1e12, "TH/s"), (1e9, "GH/s"), (1e6, "MH/s"), (1e3, "kH/s")]
    for scale, unit in units:
        if abs(value) >= scale:
            return f"{value/scale:.2f} {unit}"
    return f"{value:.0f} H/s" if value >= 10 else f"{value:.2f} H/s"


def format_uptime(seconds):
    seconds = max(0, int(float(seconds or 0)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_difficulty(value):
    value = float(value or 0)
    if value >= 1_000_000_000:
        return f"{value/1_000_000_000:.2f} G"
    if value >= 1_000_000:
        return f"{value/1_000_000:.2f} M"
    if value >= 1_000:
        return f"{value/1_000:.2f} K"
    if 0 < value < 0.001:
        return f"{value:.3g}"
    return f"{value:.2f}" if value else "—"


def format_eta(seconds):
    seconds = float(seconds or 0)
    if seconds <= 0:
        return "—"
    if seconds < 60:
        return "<1 min" if seconds < 1 else f"{seconds:.0f} sec"
    if seconds < 3600:
        return f"{seconds/60:.1f} min"
    if seconds < 86400:
        return f"{seconds/3600:.1f} hr"
    return f"{seconds/86400:.1f} d"


POOL_RESTORE_KEYS = (
    "pool_url",
    "pool_backup_urls",
    "pool_worker",
    "pool_failover_enabled",
    "pool_failover_policy",
    "pool_primary_recovery_seconds",
    "active_pool_profile_id",
    "pool_job_timeout_seconds",
    "suggest_difficulty_enabled",
    "suggest_difficulty",
    "mining_processes",
)


def recover_ephemeral_local_pool_config(cfg):
    """Restore persistent pool config after a Local Test Pool session/restart.

    v0.7.0/v0.7.0.1 could persist a dynamically allocated 127.0.0.1 port.
    Those ports are invalid after the process exits. v0.7.0.2 marks future
    local sessions explicitly and also migrates the legacy local.worker1 form.
    """
    cfg = dict(cfg or {})
    marker = bool(cfg.get("pool_url_ephemeral_local_test"))
    restore = dict(cfg.get("pool_restore_after_local_test") or {})
    url = str(cfg.get("pool_url") or "")
    worker = str(cfg.get("pool_worker") or "")
    legacy_stale = (
        not marker
        and worker == "local.worker1"
        and (
            url.startswith("stratum+tcp://127.0.0.1:")
            or url.startswith("stratum+tcp://localhost:")
        )
    )

    if not marker and not legacy_stale:
        return cfg, False, ""

    if restore:
        for key in POOL_RESTORE_KEYS:
            if key in restore:
                cfg[key] = restore[key]
    else:
        # Legacy v0.7.0/v0.7.0.1 builds did not preserve the previous pool.
        # Remove only the known app-generated localhost endpoint instead of
        # continuing to test a dead ephemeral port.
        cfg["pool_url"] = ""
        cfg["pool_backup_urls"] = []
        if worker == "local.worker1":
            cfg["pool_worker"] = ""

    cfg["pool_url_ephemeral_local_test"] = False
    cfg["pool_restore_after_local_test"] = {}
    reason = (
        "Restored pool configuration after an interrupted Local Test Pool session."
        if marker
        else "Removed stale Local Test Pool endpoint saved by an older build."
    )
    return cfg, True, reason


class WebBackend:
    def __init__(self):
        self.window = None
        self.tray_manager = None
        self.runtime = RuntimeContext.create(
            root=Path(__file__).resolve().parent,
            version=VERSION,
            product=APP_NAME,
            publisher=PUBLISHER_NAME,
            channel=RELEASE_CHANNEL,
        )
        self.events = LocalEventBus(max_events=300)
        self.services = ServiceRegistry()
        self.workspace = WorkspaceManager(self.runtime.paths.app_data / "workspace-v2.json")
        loaded_cfg = load_config()
        self.cfg, pool_cfg_recovered, pool_cfg_recovery_reason = recover_ephemeral_local_pool_config(loaded_cfg)
        if pool_cfg_recovered:
            try:
                save_config(self.cfg)
            except Exception:
                pass
        self.lock = threading.RLock()
        self.logs = []
        if pool_cfg_recovered:
            self._log(pool_cfg_recovery_reason)
        self.security_state = checking_state()
        self.benchmark = BenchmarkEngine()
        self.benchmark_lab = BenchmarkLabController(
            self.benchmark,
            self.runtime.paths.app_data / "benchmark-history.json",
            log_callback=self._log,
        )
        self.mining_academy = MiningAcademy(
            self.runtime.paths.app_data / "academy_progress.json"
        )
        self.miner = StratumMiner(event_callback=self._miner_event)
        self.pool_diagnostics = PoolDiagnosticsController(
            event_callback=self._pool_powertools_event
        )
        self.pool_profiles = PoolProfileStore(
            self.runtime.paths.app_data / "pool_profiles.json"
        )
        self.session_profile_passwords = {}
        self.local_pool = LocalStratumTestPool(
            difficulty=float(self.cfg.get("local_test_difficulty", 0.000001)),
            event_callback=self._local_pool_event,
        )
        self.session_pool_password = ""
        self.session_rpc_password = ""
        try:
            self.session_pool_password = read_secret(POOL_TARGET) or ""
        except Exception:
            pass
        try:
            self.session_rpc_password = read_secret(RPC_TARGET) or ""
        except Exception:
            pass

        self.asic_devices = {}
        history_path = self.runtime.paths.app_data / "fleet_history.json"
        self.fleet_monitor = FleetMonitor(max_samples=180, storage_path=history_path)
        analytics_path = self.runtime.paths.app_data / "analytics.sqlite3"
        self.analytics = AnalyticsStore(
            analytics_path,
            sample_seconds=int(self.cfg.get("analytics_sample_seconds", 10)),
            retention_days=int(self.cfg.get("analytics_retention_days", 30)),
            event_callback=self._analytics_event,
        )
        self.release_candidate = ReleaseCandidateManager(
            self.runtime.paths.root,
            VERSION,
            self.cfg,
            config_path=CONFIG_FILE,
        )
        self.diagnostics_center = DiagnosticsSupportCenter(
            self.runtime.paths.root,
            VERSION,
            app_data_dir=self.runtime.paths.app_data,
        )
        self.update_release_center = UpdateReleaseCenter(
            self.runtime.paths.root,
            VERSION,
            app_data_dir=self.runtime.paths.app_data,
        )
        self.asic_aliases = dict(self.cfg.get("asic_aliases", {}) or {})
        self.asic_groups = dict(self.cfg.get("asic_groups", {}) or {})
        self.asic_notes = dict(self.cfg.get("asic_notes", {}) or {})
        self.asic_known_devices = set(self.cfg.get("asic_known_devices", []) or [])
        self.asic_manual_devices = set(self.cfg.get("asic_manual_devices", []) or [])

        # Keep WebView creation responsive. Windows Core discovery may invoke
        # CIM/PowerShell and filesystem probes, so never do it synchronously
        # while the backend object is being constructed.
        configured_data_dir = str(self.cfg.get("core_data_dir", "") or "")
        self.core_setup_state = {
            "detected": False,
            "installation_found": bool(self.cfg.get("core_executable")),
            "process_running": False,
            "rpc_listening": False,
            "network": self.cfg.get("core_network", "main"),
            "rpc_url": self.cfg.get("rpc_url", "http://127.0.0.1:8332"),
            "data_dir": configured_data_dir,
            "data_dir_exists": bool(configured_data_dir and Path(configured_data_dir).exists()),
            "cookie_exists": False,
            "executable": self.cfg.get("core_executable", ""),
            "scanning": True,
            "remediation": ["Background Bitcoin Core detection is starting."],
        }

        self.core_state = disconnected_snapshot()
        self._core_state_signature = None
        self._core_monitor_stop = threading.Event()
        self._core_monitor_thread = None

        self.template_state = unavailable_template()
        self._template_state_signature = None
        self.coinbase_state = unavailable_coinbase()
        self.solo_miner = SoloMiningEngine(event_callback=self._solo_event)
        self._solo_template_failure_count = 0

        self.asic_solo_bridge = AsicSoloBridge(event_callback=self._asic_solo_event)
        self._asic_solo_template_failure_count = 0

        self.block_submission_state = unavailable_submission_state()
        self._assembled_candidate = None
        self._preserved_candidate_bundle = None
        self._preserved_candidate_source = ""
        self._submission_job_lock = threading.Lock()

        self.regtest_lab = RegtestLab(
            configured_executable=self.cfg.get("core_executable", ""),
            data_dir=default_lab_dir(),
            rpc_port=int(self.cfg.get("regtest_lab_rpc_port", 19443)),
            p2p_port=int(self.cfg.get("regtest_lab_p2p_port", 19444)),
            event_callback=self._regtest_event,
        )
        self.regtest_controller = RegtestLabController(
            self.regtest_lab,
            event_callback=self._regtest_event,
        )

        self._template_monitor_stop = threading.Event()
        self._template_monitor_thread = None
        self._background_services_started = False
        self._background_services_lock = threading.Lock()

        self._register_architecture_services()
        self.services.mark("backend", "idle", "Backend constructed; waiting for WebView bridge.")
        # Keep the js_api object constructor extremely cheap. All filesystem
        # discovery, RPC probes, integrity verification, Regtest reconnect work,
        # and fleet reloads start only after pywebview has exposed the API.
        self._log(f"{APP_NAME} v{VERSION} backend object created.")

    def _register_architecture_services(self):
        """Register long-lived v2 subsystems in one local lifecycle/health map."""
        definitions = (
            ("backend", "Application Backend", "runtime", True),
            ("workspace", "Workspace State", "runtime", False),
            ("security", "Purple Dragon Security", "security", True),
            ("core-monitor", "Bitcoin Core Monitor", "monitoring", False),
            ("template-monitor", "Block Template Monitor", "monitoring", False),
            ("analytics", "Analytics Recorder", "monitoring", False),
            ("miner", "Stratum Mining Engine", "mining", True),
            ("benchmark", "Benchmark Engine", "mining", False),
            ("pool-diagnostics", "Pool Diagnostics", "network", False),
            ("local-test-pool", "Local Test Pool", "network", False),
            ("academy", "Mining Academy", "learning", False),
            ("diagnostics", "Diagnostics & Support Center", "support", False),
            ("update-center", "Update & Release Center", "release", True),
            ("asic-fleet", "ASIC Fleet Services", "hardware", False),
            ("regtest", "Regtest Lab", "development", False),
            ("tray", "Windows Tray", "runtime", False),
        )
        for service_id, label, category, critical in definitions:
            self.services.register(
                service_id,
                label=label,
                category=category,
                critical=critical,
                state="idle",
            )

    def _sync_service_states(self):
        """Reflect live subsystem state into the v2 service registry."""
        try:
            self.services.mark(
                "miner",
                "running" if self.miner.running else "idle",
                "Stratum mining session active." if self.miner.running else "Mining engine ready.",
            )
            self.services.mark(
                "benchmark",
                "running" if self.benchmark.running else "idle",
                "Benchmark active." if self.benchmark.running else "Benchmark engine ready.",
            )
            self.services.mark(
                "local-test-pool",
                "running" if self.local_pool.running else "idle",
                "Local test pool active." if self.local_pool.running else "Local test pool stopped.",
            )
            self.services.mark(
                "asic-fleet",
                "running" if self.asic_devices else "idle",
                f"{len(self.asic_devices)} ASIC device(s) in current fleet state.",
            )
            analytics_status = self.analytics.status()
            self.services.mark(
                "analytics",
                "running" if analytics_status.get("running") else "idle",
                "Local analytics recorder active." if analytics_status.get("running") else "Analytics recorder idle.",
            )
            security = dict(self.security_state or {})
            if security.get("checked"):
                self.services.mark(
                    "security",
                    "running" if security.get("verified") else "error",
                    "Purple Dragon build trusted." if security.get("verified") else "Purple Dragon trust locked.",
                    error="" if security.get("verified") else str(security.get("error") or "Integrity verification failed."),
                )
            self.services.mark("academy", "idle", "Mining Academy local learning service ready.")
            self.services.mark("diagnostics", "idle", "Diagnostics & Support Center ready.")
            self.services.mark("update-center", "idle", "Update & Release Center ready.")
        except Exception as exc:
            try:
                self.events.publish("runtime", "service-sync", str(exc), level="warning")
            except Exception:
                pass

    def get_architecture_state(self):
        """Return credential-free v2 runtime/service/workspace observability."""
        self._sync_service_states()
        return {
            "ok": True,
            "runtime": self.runtime.public_snapshot(),
            "services": self.services.snapshot(),
            "events": self.events.snapshot(),
            "workspace": self.workspace.snapshot(),
        }

    def record_workspace_view(self, view):
        try:
            state = self.workspace.record_view(view)
            self.services.mark("workspace", "running", f"Active workspace: {state.get('last_view', 'dashboard')}")
            self.events.publish("workspace", "view", f"Opened {state.get('last_view', 'dashboard')} workspace.")
            return {"ok": True, "workspace": state}
        except Exception as exc:
            self.services.mark("workspace", "degraded", "Workspace state could not be saved.", error=str(exc))
            return {"ok": False, "error": str(exc)}

    def set_workspace_preferences(self, sidebar_compact=None, pinned_views=None):
        try:
            state = self.workspace.set_preferences(
                sidebar_compact=sidebar_compact,
                pinned_views=pinned_views,
            )
            self.events.publish("workspace", "preferences", "Workspace preferences updated.")
            return {"ok": True, "workspace": state, "result": "Workspace preferences saved."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def record_workspace_command(self, command_id):
        try:
            state = self.workspace.record_command(command_id)
            return {"ok": True, "workspace": state}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def start_background_services(self):
        """Start nonessential background services only after the WebView bridge is live."""
        with self._background_services_lock:
            if self._background_services_started:
                return {"ok": True, "started": False, "result": "Background services already started."}
            self._background_services_started = True

            self._core_monitor_thread = threading.Thread(
                target=self._core_monitor_loop,
                name="CoreHealthMonitor",
                daemon=True,
            )
            self._template_monitor_thread = threading.Thread(
                target=self._template_monitor_loop,
                name="TemplateMonitor",
                daemon=True,
            )
            self._core_monitor_thread.start()
            self._template_monitor_thread.start()
            self.services.mark("core-monitor", "running", "Background Core health monitor active.")
            self.services.mark("template-monitor", "running", "Background block-template monitor active.")
            self.services.mark("backend", "running", "WebView bridge ready; background services active.")
            self.services.mark("workspace", "running", f"Workspace state loaded: {self.workspace.snapshot().get('last_view', 'dashboard')}.")
            if bool(self.cfg.get("analytics_enabled", True)):
                self.analytics.start(self._analytics_snapshot)
                self.services.mark("analytics", "running", "Local analytics recorder active.")
            else:
                self.services.mark("analytics", "idle", "Local analytics recorder disabled by configuration.")
            self.services.mark("security", "starting", "Purple Dragon integrity verification queued.")

            threading.Thread(
                target=self._security_integrity_check,
                name="BuildIntegrityCheck",
                daemon=True,
            ).start()
            if bool(self.cfg.get("rc_preflight_on_start", True)):
                threading.Thread(
                    target=self._release_preflight_check,
                    name="ReleaseCandidatePreflight",
                    daemon=True,
                ).start()
            threading.Thread(
                target=self._initial_core_setup_detect,
                name="CoreSetupDetect",
                daemon=True,
            ).start()

            # Only probe a prior Regtest Lab when a cookie actually exists.
            # A fresh install has nothing to reconnect to.
            if self.regtest_lab.cookie_path.exists():
                threading.Thread(
                    target=self.regtest_lab.probe_existing,
                    name="RegtestLabProbe",
                    daemon=True,
                ).start()

            if self.asic_known_devices:
                threading.Thread(
                    target=self._load_known_devices,
                    name="KnownAsicReload",
                    daemon=True,
                ).start()

        self._log(f"{APP_NAME} v{VERSION} holographic UI initialized.")
        self._log("Background services started after WebView API bridge readiness.")
        self._log("UI based on the supplied PowerTools Purple Holographic package.")
        return {"ok": True, "started": True, "result": "Background services started."}

    def _release_preflight_check(self):
        """Run RC readiness only after Purple Dragon has had time to verify."""
        try:
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                with self.lock:
                    checked = bool((self.security_state or {}).get("checked"))
                if checked:
                    break
                time.sleep(0.1)
            preflight_cfg = self._normalize_rc_preflight_config()
            state = self.release_candidate.run_preflight(
                preflight_cfg,
                security_state=self.security_state,
                analytics_status=self.analytics.status(),
            )
            self._log(
                f"Stable readiness check: {state.get('readiness')} · "
                f"{state.get('score')}/100."
            )
        except Exception as exc:
            self._log(f"Stable readiness background check failed: {exc}")

    def _security_integrity_check(self):
        try:
            state = dict(verify_integrity())
        except Exception as exc:
            state = checking_state()
            state.update({
                "checked": True,
                "verified": False,
                "critical_actions_allowed": False,
                "signature_valid": False,
                "status": "locked",
                "trust_level": "LOCKED",
                "error": str(exc),
            })

        with self.lock:
            self.security_state = state

        if state.get("verified"):
            self.services.mark("security", "running", "Publisher signature and protected files verified.")
            self._log(
                f"Purple Dragon Security VERIFIED — {state.get('verified_file_count', 0)}/"
                f"{state.get('protected_file_count', 0)} protected files trusted."
            )
        else:
            detail = state.get("error") or "protected files changed"
            self.services.mark("security", "error", "Build trust verification failed.", error=detail)
            self._log(f"PURPLE DRAGON SECURITY LOCK: {detail}")
        return state

    def _require_trusted_build(self, action):
        with self.lock:
            state = dict(self.security_state or {})
        if not state.get("checked"):
            return False, (
                f"Purple Dragon Security is still verifying this build. "
                f"Wait for verification before {action}."
            )
        if not state.get("critical_actions_allowed"):
            reason = state.get("error") or "build integrity is not trusted"
            return False, (
                f"Purple Dragon Security blocked {action}: {reason} "
                "Open Purple Dragon Security Center for details."
            )
        return True, ""

    def get_security_state(self):
        """Return Purple Dragon state without constructing the full dashboard snapshot."""
        with self.lock:
            return {"ok": True, "security": dict(self.security_state or {})}

    def verify_security_now(self):
        try:
            state = self._security_integrity_check()
            return {
                "ok": bool(state.get("verified")),
                "security": state,
                "report": provenance_report(),
                "error": "" if state.get("verified") else state.get("error", "Integrity verification failed."),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_security_policy(self):
        return {"ok": True, "policy": security_policy()}

    def _initial_core_setup_detect(self):
        """Best-effort initial discovery that never blocks the UI startup path."""
        try:
            state = dict(detect_bitcoin_core(self.cfg))
            state["scanning"] = False
        except Exception as exc:
            state = {
                "detected": False,
                "installation_found": bool(self.cfg.get("core_executable")),
                "process_running": False,
                "rpc_listening": False,
                "network": self.cfg.get("core_network", "main"),
                "rpc_url": self.cfg.get("rpc_url", "http://127.0.0.1:8332"),
                "data_dir": self.cfg.get("core_data_dir", ""),
                "data_dir_exists": False,
                "cookie_exists": False,
                "executable": self.cfg.get("core_executable", ""),
                "scanning": False,
                "error": str(exc),
                "remediation": [f"Background detection failed: {exc}"],
            }
            self._log(f"Background Bitcoin Core detection failed: {exc}")
        with self.lock:
            self.core_setup_state = state

    def _log(self, message):
        stamp = time.strftime("%H:%M:%S")
        message = str(message)
        with self.lock:
            self.logs.append({"time": stamp, "message": message})
            self.logs = self.logs[-250:]
        try:
            self.events.publish("activity", "log", message)
        except Exception:
            pass

    def clear_logs(self):
        """Clear the current in-app activity history and leave one confirmation entry."""
        stamp = time.strftime("%H:%M:%S")
        with self.lock:
            self.logs.clear()
            self.logs.append({"time": stamp, "message": "Activity log cleared."})
            logs = list(self.logs)
        return {
            "ok": True,
            "logs": logs,
            "result": "Activity log cleared.",
        }

    def _miner_event(self, kind, payload):
        if kind == "log":
            self._log(payload)
        elif kind == "share":
            result = payload.get("result", "share") if isinstance(payload, dict) else str(payload)
            self._log(f"Share: {result}")
        elif kind == "status":
            self._log(f"Miner status: {payload}")

    def _pool_powertools_event(self, kind, payload):
        if kind == "log":
            self._log(f"Pool PowerTools: {payload}")

    def _analytics_event(self, kind, payload):
        if kind == "log":
            self._log(f"Monitoring: {payload}")

    def _local_pool_event(self, kind, payload):
        if kind == "log":
            self._log(payload)
        elif kind == "share":
            self._log(f"Local test share: {payload}")

    def _regtest_event(self, message):
        self._log(f"Regtest Lab: {message}")

    def _asic_solo_event(self, kind, payload):
        if kind == "log":
            self._log(f"ASIC Solo: {payload}")
        elif kind == "share":
            data = dict(payload or {})
            self._log(
                f"ASIC Solo share: {data.get('worker') or data.get('ip') or 'worker'} "
                f"difficulty {float(data.get('difficulty') or 0):.6g}"
                + (" — NETWORK TARGET" if data.get("network_valid") else "")
            )
        elif kind == "candidate":
            data = dict(payload or {})
            bundle = data.pop("bundle", None)
            self._log(
                f"ASIC SOLO CANDIDATE: height {int(data.get('height') or 0):,}, "
                f"worker {data.get('worker') or data.get('ip')}, hash {data.get('hash')}."
            )
            if bundle:
                threading.Thread(
                    target=self._preserve_external_candidate,
                    args=(bundle, f"ASIC Solo Bridge · {data.get('worker') or data.get('ip') or 'worker'}"),
                    name="AsicCandidatePreserver",
                    daemon=True,
                ).start()

    def _solo_event(self, kind, payload):
        if kind == "started":
            self._log(f"Solo Mining Engine started on height {int((payload or {}).get('height') or 0):,}.")
        elif kind in ("work_switch", "work_switched"):
            self._log(f"Solo Mining Engine switched to new work at height {int((payload or {}).get('height') or 0):,}.")
        elif kind == "candidate":
            self._log(f"SOLO CANDIDATE: height {int((payload or {}).get('height') or 0):,}, hash {(payload or {}).get('hash')}, nonce {int((payload or {}).get('nonce') or 0):,}.")
            threading.Thread(
                target=self._preserve_solo_candidate,
                name="CandidatePreserver",
                daemon=True,
            ).start()
        elif kind == "error":
            self._log(f"Solo Mining Engine error: {payload}")
        elif kind == "stopped":
            self._log(f"Solo Mining Engine stopped: {(payload or {}).get('reason', 'stopped')}")

    def _preserve_external_candidate(self, bundle, source):
        try:
            if not bundle:
                raise RuntimeError("Target-valid candidate bundle is unavailable.")

            candidate_prev = str((bundle.get("work") or {}).get("previousblockhash") or "").lower()
            with self.lock:
                current_prev = str(self.template_state.get("previousblockhash") or "").lower()
            if current_prev and candidate_prev and current_prev != candidate_prev:
                raise RuntimeError(
                    "Candidate became stale before preservation because Bitcoin Core moved to a newer chain tip."
                )

            assembly = assemble_candidate_block(bundle, require_target=True)
            assembly["candidate_source"] = str(source)
            state = assembly_for_ui(
                assembly,
                status="Candidate Ready",
                detail=(
                    f"Target-valid candidate from {source} assembled and preserved. "
                    "Validate it with Bitcoin Core before submission."
                ),
                candidate_available=True,
            )
            state["candidate_source"] = str(source)

            if bool(self.cfg.get("candidate_auto_archive", True)):
                archive_dir = Path.home() / ".bitcoin-miner-studio" / "candidates"
                json_path, block_path = archive_candidate(assembly, archive_dir)
                state["archive_json"] = json_path
                state["archive_block"] = block_path
                self._log(f"Target-valid candidate archived: {json_path}")

            with self.lock:
                self._preserved_candidate_bundle = bundle
                self._preserved_candidate_source = str(source)
                self._assembled_candidate = assembly
                self.block_submission_state = state
        except Exception as exc:
            state = unavailable_submission_state(str(exc))
            state["status"] = "Assembly Error"
            state["error"] = str(exc)
            with self.lock:
                self._assembled_candidate = None
                self.block_submission_state = state
            self._log(f"Candidate preservation failed: {exc}")

    def _preserve_solo_candidate(self):
        bundle = self.solo_miner.candidate_bundle()
        if bundle:
            self._preserve_external_candidate(bundle, "CPU Solo Mining Engine")

    def _core_signature(self, state):
        if state.get("connected"):
            return ("online", state.get("status"), state.get("chain"))
        return ("offline", state.get("error_kind"), state.get("error"))

    def _set_core_state(self, state, log_transition=True):
        signature = self._core_signature(state)
        with self.lock:
            self.core_state = dict(state)
        if log_transition and signature != self._core_state_signature:
            if state.get("connected"):
                self._log(
                    f"Bitcoin Core: {state.get('status')} on {state.get('chain')} — "
                    f"height {state.get('blocks', 0):,}, {state.get('connections', 0)} peer(s)."
                )
            else:
                self._log(
                    f"Bitcoin Core RPC {state.get('error_kind', 'error')}: {state.get('error', 'unavailable')}"
                )
        self._core_state_signature = signature

    def _core_credentials(self):
        return resolve_rpc_credentials(self.cfg, self.session_rpc_password)

    def _refresh_core_snapshot(self, *, log_transition=True, timeout=6.0, preserve_transient=False):
        try:
            username, password = self._core_credentials()
            state = fetch_core_snapshot(
                self.cfg.get("rpc_url", ""),
                username,
                password,
                timeout=timeout,
            )
        except BitcoinCoreRPCError as exc:
            state = None
            if preserve_transient and getattr(exc, "kind", "") == "timeout":
                with self.lock:
                    previous = dict(self.core_state or {})
                if previous.get("connected"):
                    previous["transient_error"] = True
                    previous["transient_error_kind"] = "timeout"
                    previous["transient_error_message"] = str(exc)
                    previous["transient_error_at"] = time.time()
                    state = previous
            if state is None:
                state = disconnected_snapshot(exc)
        except Exception as exc:
            state = disconnected_snapshot(exc)
        self._set_core_state(state, log_transition=log_transition)
        return state

    def _core_monitor_loop(self):
        # Small startup delay lets the WebView initialize before the first health check.
        self._core_monitor_stop.wait(1.5)
        while not self._core_monitor_stop.is_set():
            if bool(self.cfg.get("core_auto_refresh", True)):
                self._refresh_core_snapshot(log_transition=True, timeout=4.0, preserve_transient=True)
            try:
                interval = int(self.cfg.get("core_refresh_seconds", 10))
            except (TypeError, ValueError):
                interval = 10
            if bool(self.cfg.get("performance_plus_enabled", False)):
                # Core health data is informational; template freshness remains
                # independently monitored below. Reduce background RPC pressure.
                interval = max(interval, 20)
            self._core_monitor_stop.wait(max(5, min(300, interval)))

    def _template_signature(self, state):
        if state.get("available"):
            return (
                "ready",
                state.get("height"),
                state.get("previousblockhash"),
                state.get("transactions"),
            )
        return ("unavailable", state.get("error_kind"), state.get("error"))

    def _set_template_state(self, state, log_transition=True):
        signature = self._template_signature(state)
        with self.lock:
            self.template_state = dict(state)
        if log_transition and signature != self._template_state_signature:
            if state.get("available"):
                self._log(
                    f"Block template: height {state.get('height', 0):,}, "
                    f"{state.get('transactions', 0):,} transaction(s), "
                    f"coinbase {state.get('coinbase_value_btc', 0):.8f} BTC."
                )
            else:
                self._log(
                    f"getblocktemplate {state.get('error_kind', 'error')}: "
                    f"{state.get('error', 'unavailable')}"
                )
        self._template_state_signature = signature

        if state.get("available") and not state.get("transient_error"):
            self._solo_template_failure_count = 0
            self._asic_solo_template_failure_count = 0

            if (
                getattr(self, "solo_miner", None) is not None
                and self.solo_miner.running
                and bool(self.cfg.get("solo_auto_new_template", True))
            ):
                if self.solo_miner.update_template(state):
                    self._log(
                        f"Solo Mining: fresh chain-tip work queued for height {int(state.get('height') or 0):,}."
                    )

            if getattr(self, "asic_solo_bridge", None) is not None and self.asic_solo_bridge.running:
                try:
                    self.asic_solo_bridge.update_template(state)
                except Exception as exc:
                    self._log(f"ASIC Solo Bridge work update failed: {exc}")
        else:
            if (
                getattr(self, "solo_miner", None) is not None
                and self.solo_miner.running
                and bool(self.cfg.get("solo_auto_new_template", True))
            ):
                self._solo_template_failure_count += 1
                if self._solo_template_failure_count >= 3:
                    reason = (
                        "Solo mining stopped after 3 consecutive getblocktemplate failures "
                        "to prevent prolonged stale work."
                    )
                    self.solo_miner.stop(reason)
                    self._log(reason)
                    self._solo_template_failure_count = 0

            if getattr(self, "asic_solo_bridge", None) is not None and self.asic_solo_bridge.running:
                self._asic_solo_template_failure_count += 1
                if self._asic_solo_template_failure_count >= 3:
                    reason = (
                        "ASIC Solo Bridge stopped after 3 consecutive getblocktemplate failures "
                        "to prevent ASICs from hashing prolonged stale work."
                    )
                    self.asic_solo_bridge.stop(reason)
                    self._log(reason)
                    self._asic_solo_template_failure_count = 0

    def _refresh_block_template(self, *, log_transition=True, timeout=6.0, preserve_transient=False):
        try:
            username, password = self._core_credentials()
            state = fetch_block_template(
                self.cfg.get("rpc_url", ""),
                username,
                password,
                timeout=timeout,
            )
        except BitcoinCoreRPCError as exc:
            state = None
            if preserve_transient and getattr(exc, "kind", "") == "timeout":
                with self.lock:
                    previous = dict(self.template_state or {})
                if previous.get("available"):
                    previous["transient_error"] = True
                    previous["transient_error_kind"] = "timeout"
                    previous["transient_error_message"] = str(exc)
                    previous["transient_error_at"] = time.time()
                    state = previous
            if state is None:
                state = unavailable_template(exc)
        except Exception as exc:
            state = unavailable_template(exc)
        self._set_template_state(state, log_transition=log_transition)

        # Coinbase previews are intentionally NOT rebuilt here. The template
        # monitor runs in the background and a saved payout address would make
        # every automatic getblocktemplate refresh also perform coinbase work
        # and mutate UI-facing state. Keep the preview explicitly user-driven.
        with self.lock:
            if self.coinbase_state.get("available"):
                previous_height = int(self.coinbase_state.get("height") or 0)
                new_height = int(state.get("height") or 0) if state.get("available") else 0
                if new_height and new_height != previous_height:
                    self.coinbase_state = unavailable_coinbase(
                        f"A newer block template is ready at height {new_height:,}. "
                        "Click Build Coinbase Preview to rebuild it."
                    )
        return state

    def _coinbase_payload_values(self, payload=None):
        payload = payload or {}
        address = str(payload.get("coinbase_payout_address", self.cfg.get("coinbase_payout_address", "")) or "").strip()
        tag = str(payload.get("coinbase_tag", self.cfg.get("coinbase_tag", DEFAULT_COINBASE_TAG)) or "").strip()
        try:
            extranonce_size = int(payload.get("coinbase_extranonce_size", self.cfg.get("coinbase_extranonce_size", 8)))
        except (TypeError, ValueError):
            extranonce_size = 8
        return address, tag, max(4, min(32, extranonce_size))

    def _save_coinbase(self, payload):
        address, tag, extranonce_size = self._coinbase_payload_values(payload)
        self.cfg["coinbase_payout_address"] = address
        self.cfg["coinbase_tag"] = tag
        self.cfg["coinbase_extranonce_size"] = extranonce_size
        save_config(self.cfg)
        return address, tag, extranonce_size

    def _refresh_coinbase_preview(self, template_state=None):
        template_state = template_state or self.template_state
        address, tag, extranonce_size = self._coinbase_payload_values()
        if not address:
            state = unavailable_coinbase("Enter a payout address to prepare the live coinbase preview.")
        elif not template_state.get("available"):
            state = unavailable_coinbase("A ready block template is required before building the coinbase preview.")
        else:
            try:
                state = build_coinbase_transaction(
                    template_state,
                    address,
                    network=self.cfg.get("core_network", "main"),
                    tag=tag,
                    extranonce_size=extranonce_size,
                )
            except Exception as exc:
                state = unavailable_coinbase(str(exc))
        with self.lock:
            self.coinbase_state = dict(state)
        return state

    def _template_monitor_loop(self):
        self._template_monitor_stop.wait(2.0)
        while not self._template_monitor_stop.is_set():
            if bool(self.cfg.get("template_auto_refresh", True)):
                self._refresh_block_template(log_transition=True, timeout=5.0, preserve_transient=True)
            try:
                interval = int(self.cfg.get("template_refresh_seconds", 15))
            except (TypeError, ValueError):
                interval = 15
            if bool(self.cfg.get("performance_plus_enabled", False)):
                # Do not trade mining correctness for UI performance. Keep new
                # block detection reasonably fresh even while other polling is reduced.
                interval = min(interval, 15)
            self._template_monitor_stop.wait(max(5, min(300, interval)))

    def _password(self, payload, key, stored):
        value = str((payload or {}).get(key, "") or "")
        return value if value else stored

    def _configured_pool_endpoints(self):
        try:
            return normalize_endpoints(
                self.cfg.get("pool_url", ""),
                self.cfg.get("pool_backup_urls", []),
            )
        except Exception:
            return []

    def _invalidate_pool_diagnostics_if_changed(self, previous_endpoints):
        current = self._configured_pool_endpoints()
        if list(previous_endpoints or []) != list(current or []):
            try:
                self.pool_diagnostics.invalidate(
                    "Pool endpoint configuration changed. Previous diagnostic results were discarded; run Test All Endpoints again."
                )
            except Exception:
                pass

    def _pool_config_for_ui(self):
        return {
            "pool_url": self.cfg.get("pool_url", ""),
            "pool_backup_urls": list(self.cfg.get("pool_backup_urls", []) or []),
            "pool_worker": self.cfg.get("pool_worker", ""),
            "pool_failover_enabled": bool(self.cfg.get("pool_failover_enabled", True)),
            "pool_failover_policy": normalize_failover_policy(self.cfg.get("pool_failover_policy", "balanced")),
            "pool_primary_recovery_seconds": int(self.cfg.get("pool_primary_recovery_seconds", 300)),
            "active_pool_profile_id": str(self.cfg.get("active_pool_profile_id", "") or ""),
            "pool_job_timeout_seconds": int(self.cfg.get("pool_job_timeout_seconds", 120)),
            "suggest_difficulty_enabled": bool(self.cfg.get("suggest_difficulty_enabled", False)),
            "suggest_difficulty": float(self.cfg.get("suggest_difficulty", 1.0)),
            "mining_processes": int(self.cfg.get("mining_processes", 2)),
        }

    def _normalize_local_test_pool_payload(self, payload):
        """Prevent a blank/stale WebView form from overriding an active local pool.

        The built-in Local Test Pool owns its endpoint and local test worker.
        When the local server is active, those values are authoritative.
        """
        payload = dict(payload or {})
        if not self.local_pool.running:
            return payload

        endpoint = str(self.local_pool.endpoint or "").strip()
        requested = str(payload.get("pool_url") or "").strip()
        if requested and requested != endpoint:
            return payload

        payload["pool_url"] = endpoint
        payload["pool_backup_urls"] = []
        payload["pool_worker"] = "local.worker1"
        payload["pool_password"] = "x"
        payload["pool_failover_enabled"] = False
        payload["pool_failover_policy"] = "manual"
        payload["pool_primary_recovery_seconds"] = 0
        payload["suggest_difficulty_enabled"] = False
        payload["suggest_difficulty"] = float(
            getattr(self.local_pool, "difficulty", 0.000001) or 0.000001
        )
        return payload

    def _save_pool(self, payload):
        previous_endpoints = self._configured_pool_endpoints()
        payload = self._normalize_local_test_pool_payload(payload)
        self.cfg["pool_url"] = str(payload.get("pool_url", self.cfg.get("pool_url", ""))).strip()

        backups = payload.get("pool_backup_urls", self.cfg.get("pool_backup_urls", []))
        if isinstance(backups, str):
            backups = [line.strip() for line in backups.replace(",", "\n").splitlines() if line.strip()]
        endpoints = normalize_endpoints(self.cfg["pool_url"], backups or [])
        if not endpoints:
            raise ValueError("At least one valid Stratum endpoint is required.")
        self.cfg["pool_url"] = endpoints[0]
        self.cfg["pool_backup_urls"] = endpoints[1:]
        policy = normalize_failover_policy(
            payload.get("pool_failover_policy", self.cfg.get("pool_failover_policy", "balanced"))
        )
        if not bool(payload.get("pool_failover_enabled", self.cfg.get("pool_failover_enabled", True))):
            policy = "manual"
        policy_cfg = policy_for(policy)
        self.cfg["pool_failover_policy"] = policy
        self.cfg["pool_failover_enabled"] = bool(policy_cfg["failover_enabled"])
        try:
            recovery_seconds = int(
                payload.get(
                    "pool_primary_recovery_seconds",
                    self.cfg.get("pool_primary_recovery_seconds", policy_cfg["primary_recovery_seconds"]),
                )
            )
        except (TypeError, ValueError):
            recovery_seconds = int(policy_cfg["primary_recovery_seconds"])
        self.cfg["pool_primary_recovery_seconds"] = max(0, min(86400, recovery_seconds))
        try:
            job_timeout = int(
                payload.get("pool_job_timeout_seconds", self.cfg.get("pool_job_timeout_seconds", 120))
            )
        except (TypeError, ValueError):
            job_timeout = 120
        self.cfg["pool_job_timeout_seconds"] = max(20, min(1800, job_timeout))

        self.cfg["pool_worker"] = str(payload.get("pool_worker", self.cfg.get("pool_worker", ""))).strip()
        self.cfg["mining_processes"] = max(1, min(64, int(payload.get("mining_processes", self.cfg.get("mining_processes", 2)))))
        self.cfg["suggest_difficulty_enabled"] = bool(payload.get("suggest_difficulty_enabled", self.cfg.get("suggest_difficulty_enabled", False)))
        self.cfg["suggest_difficulty"] = float(payload.get("suggest_difficulty", self.cfg.get("suggest_difficulty", 1.0)))
        password = str(payload.get("pool_password", "") or "")
        if password:
            self.session_pool_password = password
            try:
                write_secret(POOL_TARGET, self.cfg["pool_worker"], password)
            except Exception as exc:
                self._log(f"Credential save warning: {exc}")
        save_config(self.cfg)
        self._invalidate_pool_diagnostics_if_changed(previous_endpoints)

    def _save_core(self, payload):
        payload = payload or {}
        self.cfg["rpc_url"] = str(payload.get("rpc_url", self.cfg.get("rpc_url", ""))).strip()
        self.cfg["rpc_user"] = str(payload.get("rpc_user", self.cfg.get("rpc_user", ""))).strip()
        auth_mode = str(payload.get("core_auth_mode", self.cfg.get("core_auth_mode", "password")) or "password").strip().lower()
        self.cfg["core_auth_mode"] = auth_mode if auth_mode in ("password", "cookie") else "password"
        self.cfg["core_data_dir"] = str(payload.get("core_data_dir", self.cfg.get("core_data_dir", "")) or "").strip()
        self.cfg["core_executable"] = str(payload.get("core_executable", self.cfg.get("core_executable", "")) or "").strip()
        self.cfg["core_cookie_path"] = str(payload.get("core_cookie_path", self.cfg.get("core_cookie_path", "")) or "").strip()
        network = str(payload.get("core_network", self.cfg.get("core_network", "main")) or "main").strip().lower()
        self.cfg["core_network"] = network if network in ("main", "testnet", "testnet4", "signet", "regtest") else "main"
        self.cfg["core_auto_refresh"] = bool(payload.get("core_auto_refresh", self.cfg.get("core_auto_refresh", True)))
        try:
            refresh_seconds = int(payload.get("core_refresh_seconds", self.cfg.get("core_refresh_seconds", 10)))
        except (TypeError, ValueError):
            refresh_seconds = 10
        self.cfg["core_refresh_seconds"] = max(5, min(300, refresh_seconds))
        self.cfg["template_auto_refresh"] = bool(payload.get("template_auto_refresh", self.cfg.get("template_auto_refresh", True)))
        try:
            template_refresh_seconds = int(payload.get("template_refresh_seconds", self.cfg.get("template_refresh_seconds", 15)))
        except (TypeError, ValueError):
            template_refresh_seconds = 15
        self.cfg["template_refresh_seconds"] = max(5, min(300, template_refresh_seconds))
        password = str(payload.get("rpc_password", "") or "")
        if password and self.cfg.get("core_auth_mode") == "password":
            self.session_rpc_password = password
            try:
                write_secret(RPC_TARGET, self.cfg["rpc_user"], password)
            except Exception as exc:
                self._log(f"Credential save warning: {exc}")
        save_config(self.cfg)

    def _profile_password(self, profile_id):
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            return ""
        if profile_id in self.session_profile_passwords:
            return self.session_profile_passwords[profile_id]
        try:
            value = read_secret(pool_profile_target(profile_id)) or ""
        except Exception:
            value = ""
        if value:
            self.session_profile_passwords[profile_id] = value
        return value

    def _pool_profiles_state(self):
        active_id = str(self.cfg.get("active_pool_profile_id", "") or "")
        rows = []
        for profile in self.pool_profiles.list():
            row = dict(profile)
            row["active"] = bool(profile.get("id") == active_id)
            row["credential_stored"] = bool(self._profile_password(profile.get("id")))
            rows.append(row)
        active = next((dict(x) for x in rows if x.get("active")), None)
        stats = self.miner.stats()
        return {
            "schema": 1,
            "profiles": rows,
            "profile_count": len(rows),
            "active_profile_id": active_id,
            "active_profile": active,
            "policies": policy_options(),
            "runtime": {
                "running": bool(stats.get("running")),
                "active_endpoint": stats.get("active_endpoint", ""),
                "failover_policy": stats.get("failover_policy", normalize_failover_policy(self.cfg.get("pool_failover_policy"))),
                "failover_count": int(stats.get("failover_count") or 0),
                "last_failover_reason": stats.get("last_failover_reason", ""),
                "primary_recovery_attempts": int(stats.get("primary_recovery_attempts") or 0),
                "active_endpoint_uptime_seconds": float(stats.get("active_endpoint_uptime_seconds") or 0),
            },
            "credential_backend": backend_name(),
            "passwords_in_profile_file": False,
        }

    def _apply_profile(self, profile):
        previous_endpoints = self._configured_pool_endpoints()
        config = profile_to_pool_config(profile)
        for key, value in config.items():
            self.cfg[key] = value
        self.cfg["active_pool_profile_id"] = str(profile.get("id") or "")
        self.cfg["profitability_pool_fee_percent"] = float(profile.get("pool_fee_percent") or 0)
        save_config(self.cfg)
        self._invalidate_pool_diagnostics_if_changed(previous_endpoints)
        password = self._profile_password(profile.get("id"))
        if password:
            self.session_pool_password = password
            try:
                write_secret(POOL_TARGET, self.cfg.get("pool_worker", ""), password)
            except Exception as exc:
                self._log(f"Profile credential activation warning: {exc}")
        return config, password

    def _attach_tray_manager(self, manager):
        self.tray_manager = manager
        return True

    def _tray_status_snapshot(self):
        snapshot = self._analytics_snapshot()
        with self.lock:
            security = dict(self.security_state or {})
        snapshot.update({
            "security_checked": bool(security.get("checked")),
            "security_verified": bool(security.get("verified")),
        })
        return snapshot

    def _tray_runtime_state(self):
        if self.tray_manager is not None:
            return self.tray_manager.state()
        settings = normalize_tray_settings(self.cfg)
        return {
            "schema": 1,
            "supported": sys.platform == "win32",
            "platform": sys.platform,
            "running": False,
            "hidden": False,
            "exit_requested": False,
            "error": "Tray manager has not started yet." if sys.platform == "win32" else "Windows tray is available only on Windows.",
            "settings": settings,
            "status": build_tray_status(self._tray_status_snapshot()),
            "last_notification": "",
            "last_notification_at": 0.0,
        }

    def get_tray_state(self):
        return {"ok": True, "tray": self._tray_runtime_state()}

    def save_tray_settings(self, payload=None):
        try:
            settings = normalize_tray_settings({**self.cfg, **dict(payload or {})})
            self.cfg.update(settings)
            save_config(self.cfg)
            if self.tray_manager is not None:
                state = self.tray_manager.update_settings(settings)
            else:
                state = self._tray_runtime_state()
            self._log(
                "Tray settings saved — "
                f"enabled={settings['tray_enabled']}, minimize={settings['tray_minimize_to_tray']}, "
                f"close={settings['tray_close_to_tray']}, notifications={settings['tray_notifications_enabled']}."
            )
            return {"ok": True, "tray": state, "result": "Windows tray settings saved."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def hide_to_tray(self):
        if self.tray_manager is None:
            return {"ok": False, "error": "Windows tray manager is not initialized."}
        if not self.tray_manager.hide_window():
            return {"ok": False, "error": self.tray_manager.error or "Tray is disabled or unavailable."}
        return {"ok": True, "tray": self.tray_manager.state(), "result": "Bitcoin Miner Studio is running in the Windows tray."}

    def show_from_tray(self):
        if self.tray_manager is None:
            return {"ok": False, "error": "Windows tray manager is not initialized."}
        if not self.tray_manager.show_window():
            return {"ok": False, "error": self.tray_manager.error or "Could not show the application window."}
        return {"ok": True, "tray": self.tray_manager.state(), "result": "Bitcoin Miner Studio window restored."}

    def test_tray_notification(self):
        if self.tray_manager is None:
            return {"ok": False, "error": "Windows tray manager is not initialized."}
        if not self.tray_manager.test_notification():
            return {"ok": False, "error": self.tray_manager.error or "Tray notifications are disabled or unavailable."}
        return {"ok": True, "tray": self.tray_manager.state(), "result": "Windows tray test notification sent."}

    def get_bootstrap(self):
        with self.lock:
            return {
                "app_name": APP_NAME,
                "version": VERSION,
                "publisher": PUBLISHER_NAME,
                "created_by": f"Created by {PUBLISHER_NAME}",
                "credential_backend": backend_name(),
                "runtime": self.runtime.public_snapshot(),
                "architecture": self.services.snapshot(),
                "workspace": self.workspace.snapshot(),
                "api_contract": {
                    "schema": BRIDGE_API_SCHEMA,
                    "exposed_count": len(EXPOSED_API_METHODS),
                },
                "config": {
                    "pool_url": self.cfg.get("pool_url", ""),
                    "pool_backup_urls": list(self.cfg.get("pool_backup_urls", []) or []),
                    "pool_failover_enabled": bool(self.cfg.get("pool_failover_enabled", True)),
                    "pool_failover_policy": normalize_failover_policy(self.cfg.get("pool_failover_policy", "balanced")),
                    "pool_primary_recovery_seconds": int(self.cfg.get("pool_primary_recovery_seconds", 300)),
                    "active_pool_profile_id": str(self.cfg.get("active_pool_profile_id", "") or ""),
                    "pool_job_timeout_seconds": int(self.cfg.get("pool_job_timeout_seconds", 120)),
                    "pool_worker": self.cfg.get("pool_worker", ""),
                    "mining_processes": int(self.cfg.get("mining_processes", 2)),
                    "benchmark_processes": int(self.cfg.get("benchmark_processes", 2)),
                    "benchmark_duration_seconds": int(self.cfg.get("benchmark_duration_seconds", 30)),
                    "benchmark_scaling_seconds": int(self.cfg.get("benchmark_scaling_seconds", 8)),
                    "suggest_difficulty_enabled": bool(self.cfg.get("suggest_difficulty_enabled", False)),
                    "suggest_difficulty": float(self.cfg.get("suggest_difficulty", 1.0)),
                    "rpc_url": self.cfg.get("rpc_url", ""),
                    "rpc_user": self.cfg.get("rpc_user", ""),
                    "core_auth_mode": self.cfg.get("core_auth_mode", "password"),
                    "core_data_dir": self.cfg.get("core_data_dir", ""),
                    "core_executable": self.cfg.get("core_executable", ""),
                    "core_cookie_path": self.cfg.get("core_cookie_path", ""),
                    "core_network": self.cfg.get("core_network", "main"),
                    "core_auto_refresh": bool(self.cfg.get("core_auto_refresh", True)),
                    "core_refresh_seconds": int(self.cfg.get("core_refresh_seconds", 10)),
                    "template_auto_refresh": bool(self.cfg.get("template_auto_refresh", True)),
                    "template_refresh_seconds": int(self.cfg.get("template_refresh_seconds", 15)),
                    "coinbase_payout_address": self.cfg.get("coinbase_payout_address", ""),
                    "coinbase_tag": self.cfg.get("coinbase_tag", DEFAULT_COINBASE_TAG),
                    "coinbase_extranonce_size": int(self.cfg.get("coinbase_extranonce_size", 8)),
                    "solo_batch_size": int(self.cfg.get("solo_batch_size", 20000)),
                    "solo_extranonce_roll_hashes": int(self.cfg.get("solo_extranonce_roll_hashes", 2000000)),
                    "solo_auto_new_template": bool(self.cfg.get("solo_auto_new_template", True)),
                    "block_submit_require_proposal": bool(self.cfg.get("block_submit_require_proposal", True)),
                    "candidate_auto_archive": bool(self.cfg.get("candidate_auto_archive", True)),
                    "performance_plus_enabled": bool(self.cfg.get("performance_plus_enabled", False)),
                    "ui_theme": normalize_ui_theme(self.cfg.get("ui_theme")),
                    "ui_theme_options": ui_theme_options(),
                    "mining_assistant_goal": normalize_goal(self.cfg.get("mining_assistant_goal")),
                    "mining_assistant_intro_seen": bool(self.cfg.get("mining_assistant_intro_seen", False)),
                    "mining_assistant_completed": bool(self.cfg.get("mining_assistant_completed", False)),
                    "profitability_electricity_per_kwh": float(self.cfg.get("profitability_electricity_per_kwh", 0.15)),
                    "profitability_pool_fee_percent": float(self.cfg.get("profitability_pool_fee_percent", 1.0)),
                    "profitability_btc_price": float(self.cfg.get("profitability_btc_price", 0.0)),
                    "analytics_enabled": bool(self.cfg.get("analytics_enabled", True)),
                    "analytics_sample_seconds": int(self.cfg.get("analytics_sample_seconds", 10)),
                    "analytics_retention_days": int(self.cfg.get("analytics_retention_days", 30)),
                    "tray_enabled": bool(self.cfg.get("tray_enabled", True)),
                    "tray_minimize_to_tray": bool(self.cfg.get("tray_minimize_to_tray", True)),
                    "tray_close_to_tray": bool(self.cfg.get("tray_close_to_tray", False)),
                    "tray_notifications_enabled": bool(self.cfg.get("tray_notifications_enabled", True)),
                    "tray_poll_seconds": int(self.cfg.get("tray_poll_seconds", 10)),
                    "release_channel": self.cfg.get("release_channel", RELEASE_CHANNEL),
                    "rc_preflight_on_start": bool(self.cfg.get("rc_preflight_on_start", True)),
                    "regtest_lab_rpc_port": int(self.cfg.get("regtest_lab_rpc_port", 19443)),
                    "regtest_lab_data_dir": str(default_lab_dir()),
                    "asic_subnet": self.cfg.get("asic_subnet") or default_private_cidr(),
                    "asic_solo_bind_ip": self.cfg.get("asic_solo_bind_ip") or detect_private_lan_ip(),
                    "asic_solo_port": int(self.cfg.get("asic_solo_port", 3333)),
                    "asic_solo_share_difficulty": float(self.cfg.get("asic_solo_share_difficulty", ASIC_SOLO_DEFAULT_DIFFICULTY)),
                    "pool_password_stored": bool(self.session_pool_password),
                    "rpc_password_stored": bool(self.session_rpc_password),
                },
            }

    def _analytics_snapshot(self):
        """Collect one credential-free monitoring snapshot from in-memory state."""
        stats = self.miner.stats()
        solo = self.solo_miner.stats()
        with self.lock:
            core = dict(self.core_state or {})
            devices = [dict(device) for device in self.asic_devices.values()]

        temps = []
        health = []
        total_asic_hashrate = 0.0
        online = 0
        for device in devices:
            status = str(device.get("status") or "")
            if status in ("Online", "Web UI only"):
                online += 1
            total_asic_hashrate += float(device.get("hashrate_hs") or 0)
            temp = device.get("temperature_c")
            if temp is not None:
                try:
                    temps.append(float(temp))
                except Exception:
                    pass
            try:
                health.append(float(self.fleet_monitor.health_score(device)))
            except Exception:
                pass

        decided = int(stats.get("accepted") or 0) + int(stats.get("rejected") or 0) + int(stats.get("stale") or 0)
        acceptance = float(stats.get("acceptance_rate") or 0) if decided else 0.0
        pool_health = pool_health_score(stats) if stats.get("session_started") else 100
        return {
            "ts": time.time(),
            "pool_running": bool(stats.get("running")),
            "pool_hashrate": float(stats.get("current_hashrate") or 0),
            "pool_avg_hashrate": float(stats.get("average_hashrate") or 0),
            "pool_acceptance": acceptance,
            "pool_accepted": int(stats.get("accepted") or 0),
            "pool_rejected": int(stats.get("rejected") or 0),
            "pool_stale": int(stats.get("stale") or 0),
            "pool_share_p95_ms": float(stats.get("share_response_p95_ms") or 0),
            "pool_health": float(pool_health),
            "pool_job_age": float(stats.get("job_age_seconds") or 0),
            "pool_failovers": int(stats.get("failover_count") or 0),
            "pool_reconnects": int(stats.get("reconnect_count") or 0),
            "solo_running": bool(solo.get("running")),
            "solo_hashrate": float(solo.get("hashrate") or 0),
            "solo_avg_hashrate": float(solo.get("average_hashrate") or 0),
            "solo_peak_hashrate": float(solo.get("peak_hashrate") or 0),
            "solo_best_difficulty": float(solo.get("best_difficulty") or 0),
            "solo_target_ratio": float(solo.get("target_ratio") or 0),
            "solo_stale_batches": int(solo.get("stale_batches_discarded") or 0),
            "core_connected": bool(core.get("connected")),
            "core_rpc_latency_ms": float(core.get("latency_ms") or 0),
            "core_peers": int(core.get("connections") or 0),
            "core_sync_percent": float(core.get("sync_percent") or 0),
            "core_height": int(core.get("blocks") or 0),
            "asic_total": len(devices),
            "asic_online": online,
            "asic_hashrate": total_asic_hashrate,
            "asic_avg_temp": (sum(temps) / len(temps)) if temps else 0.0,
            "asic_max_temp": max(temps) if temps else 0.0,
            "asic_avg_health": (sum(health) / len(health)) if health else 0.0,
        }

    def _normalize_rc_preflight_config(self):
        """Return configuration suitable for RC scoring.

        The built-in Local Test Pool uses an ephemeral marker by design.

        * If the Local Test Pool is actively running, keep the live app
          configuration untouched but suppress the expected ephemeral marker
          in the copy used by Stable release validation.
        * If no Local Test Pool is running, clear stale ephemeral metadata from
          the real configuration and persist that cleanup.

        This function never starts/stops a pool and never changes a live pool
        endpoint.
        """
        try:
            local_running = bool(self.local_pool.running)
        except Exception:
            local_running = False

        preflight_cfg = dict(self.cfg)

        if local_running:
            preflight_cfg["pool_url_ephemeral_local_test"] = False
            preflight_cfg["pool_restore_after_local_test"] = {}
            return preflight_cfg

        changed = False
        if bool(self.cfg.get("pool_url_ephemeral_local_test")):
            self.cfg["pool_url_ephemeral_local_test"] = False
            changed = True

        if self.cfg.get("pool_restore_after_local_test"):
            self.cfg["pool_restore_after_local_test"] = {}
            changed = True

        if changed:
            try:
                save_config(self.cfg)
                self._log("Stable preflight normalized stale Local Test Pool session metadata.")
            except Exception as exc:
                self._log(f"Stable preflight could not persist Local Test Pool metadata cleanup: {exc}")

        return dict(self.cfg)

    # v1.8.0 — Diagnostics & Support Center
    def _diagnostics_snapshot(self):
        """Build a read-only operational snapshot without exposing stored secrets."""
        try:
            miner_stats = dict(self.miner.stats() or {})
        except Exception:
            miner_stats = {}
        miner_stats["running"] = bool(getattr(self.miner, "running", False))

        try:
            pool_state = dict(self.pool_diagnostics.state() or {})
        except Exception:
            pool_state = {}

        try:
            asic_solo = dict(self.asic_solo_bridge.stats() or {})
        except Exception:
            asic_solo = {}

        asics = []
        for ip, device in sorted(self.asic_devices.items()):
            row = dict(device or {})
            row.setdefault("ip", ip)
            try:
                row["health"] = self.fleet_monitor.health_score(device)
            except Exception:
                pass
            asics.append(row)

        try:
            analytics = dict(self.analytics.status() or {})
        except Exception:
            analytics = {}
        analytics.setdefault("enabled", bool(self.cfg.get("analytics_enabled", True)))

        try:
            release_state = dict(self.release_candidate.state() or {})
        except Exception:
            release_state = {}

        return {
            "cfg": dict(self.cfg),
            "security": dict(self.security_state),
            "core": dict(self.core_state),
            "core_setup": dict(self.core_setup_state),
            "miner": miner_stats,
            "pool_diagnostics": pool_state,
            "asic_devices": asics,
            "asic_solo": asic_solo,
            "analytics": analytics,
            "release": release_state,
            "architecture": self.services.snapshot(),
            "workspace": self.workspace.snapshot(),
            "logs": list(self.logs),
            "release_report": self.release_candidate.report(),
            "pool_diagnostic_report": diagnostic_report(pool_state),
        }

    def get_diagnostics_state(self):
        try:
            return {"ok": True, "diagnostics": self.diagnostics_center.state()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_diagnostics(self, mode="quick"):
        try:
            state = self.diagnostics_center.run(self._diagnostics_snapshot(), mode)
            self._log(
                f"Diagnostics {state.get('mode', 'quick')}: {state.get('health')} — "
                f"{state.get('score')}/100, {state.get('warnings')} warning(s), "
                f"{state.get('failures')} failure(s)."
            )
            return {
                "ok": not bool(state.get("failures")),
                "diagnostics": state,
                "report": self.diagnostics_center.report(),
                "error": "" if not state.get("failures") else "Diagnostics found one or more failures.",
            }
        except Exception as exc:
            self._log(f"Diagnostics failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def get_diagnostics_report(self):
        try:
            return {
                "ok": True,
                "diagnostics": self.diagnostics_center.state(),
                "report": self.diagnostics_center.report(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def create_diagnostics_support_bundle(self, payload=None):
        try:
            payload = dict(payload or {})
            result = self.diagnostics_center.create_support_bundle(
                self._diagnostics_snapshot(),
                include_activity_log=bool(payload.get("include_activity_log", True)),
                include_settings=bool(payload.get("include_settings", True)),
            )
            self._log(f"Diagnostics support bundle created locally: {result.get('path_display')}")
            return result
        except Exception as exc:
            self._log(f"Diagnostics support bundle failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def open_diagnostics_support_folder(self):
        try:
            path = self.diagnostics_center.support_dir
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return {"ok": True, "result": "Opened local Diagnostics support folder."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # v2.0.1 — Update & Release Center retained inside Architecture/UX milestone
    def get_update_release_state(self):
        try:
            return {"ok": True, "update_release": self.update_release_center.state()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_update_channel(self, channel="stable"):
        try:
            state = self.update_release_center.set_channel(channel)
            self._log(f"Update channel preference set to {state.get('channel', 'stable').upper()}.")
            return {"ok": True, "update_release": state}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def choose_update_package(self):
        try:
            if self.window is None:
                return {"ok": False, "error": "The native file picker is not available yet."}
            import webview
            selected = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "Bitcoin Miner Studio release packages (*.7z;*.zip)",
                    "7-Zip archives (*.7z)",
                    "ZIP archives (*.zip)",
                    "All files (*.*)",
                ),
            )
            if not selected:
                return {"ok": False, "error": "No update package selected."}
            return {"ok": True, "path": str(selected[0])}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def choose_update_folder(self):
        try:
            if self.window is None:
                return {"ok": False, "error": "The native folder picker is not available yet."}
            import webview
            selected = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            if not selected:
                return {"ok": False, "error": "No release folder selected."}
            return {"ok": True, "path": str(selected[0])}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def inspect_update_package(self, payload=None):
        try:
            payload = dict(payload or {})
            source = str(payload.get("path") or payload.get("source") or "").strip()
            expected = str(payload.get("sha256") or payload.get("expected_sha256") or "").strip()
            state = self.update_release_center.inspect(source, expected)
            inspection = state.get("inspection") or {}
            trust = inspection.get("trust") or {}
            self._log(
                f"Update package inspection: {inspection.get('recommendation', 'BLOCKED')} · "
                f"candidate {trust.get('version') or 'unknown'} · "
                f"trusted={'yes' if trust.get('trusted') else 'no'}."
            )
            return {
                "ok": bool(inspection.get("ok")),
                "update_release": state,
                "report": self.update_release_center.report(),
                "error": "" if inspection.get("ok") else str(inspection.get("detail") or "Update inspection failed."),
            }
        except Exception as exc:
            self._log(f"Update package inspection failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def stage_update_package(self):
        try:
            result = self.update_release_center.stage_last_inspection()
            self._log(f"Trusted update staged locally: {result.get('path')}")
            return result
        except Exception as exc:
            self._log(f"Update staging failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def clear_staged_update(self):
        try:
            result = self.update_release_center.clear_staged()
            self._log("Local update staging area cleared by explicit user action.")
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def export_release_descriptor(self):
        try:
            result = self.update_release_center.export_release_descriptor(self.security_state)
            self._log(f"Release descriptor exported locally: {result.get('path')}")
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_update_release_report(self):
        try:
            return {
                "ok": True,
                "update_release": self.update_release_center.state(),
                "report": self.update_release_center.report(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_update_staging_folder(self):
        try:
            path = self.update_release_center.update_dir
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return {"ok": True, "result": "Opened local Update & Release Center folder."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_release_candidate_state(self):
        try:
            return {"ok": True, "release_candidate": self.release_candidate.state()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_release_preflight(self):
        try:
            preflight_cfg = self._normalize_rc_preflight_config()
            state = self.release_candidate.run_preflight(
                preflight_cfg,
                security_state=self.security_state,
                analytics_status=self.analytics.status(),
            )
            self._log(
                f"Stable release preflight: {state.get('readiness')} — "
                f"{state.get('score')}/100, {state.get('blockers')} blocker(s), "
                f"{state.get('warnings')} warning(s)."
            )
            return {
                "ok": not bool(state.get("blockers")),
                "release_candidate": state,
                "report": self.release_candidate.report(),
                "error": "" if not state.get("blockers") else "Stable release preflight has blocking failures.",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_release_candidate_report(self):
        try:
            return {
                "ok": True,
                "release_candidate": self.release_candidate.state(),
                "report": self.release_candidate.report(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def create_release_support_bundle(self):
        try:
            result = self.release_candidate.create_support_bundle(
                self.cfg,
                logs=list(self.logs),
                security_state=self.security_state,
                analytics_status=self.analytics.status(),
                pool_diagnostic_report=diagnostic_report(self.pool_diagnostics.state()),
            )
            self._log(
                f"Stable support bundle created locally: {result.get('path_display')}"
            )
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_analytics_dashboard(self, range_seconds=3600):
        try:
            return self.analytics.dashboard(int(range_seconds))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_analytics_status(self):
        try:
            return {"ok": True, "status": self.analytics.status()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def configure_analytics(self, payload):
        try:
            payload = dict(payload or {})
            enabled = bool(payload.get("enabled", self.cfg.get("analytics_enabled", True)))
            sample_seconds = max(5, min(300, int(payload.get("sample_seconds", self.cfg.get("analytics_sample_seconds", 10)))))
            retention_days = max(1, min(365, int(payload.get("retention_days", self.cfg.get("analytics_retention_days", 30)))))
            self.cfg["analytics_enabled"] = enabled
            self.cfg["analytics_sample_seconds"] = sample_seconds
            self.cfg["analytics_retention_days"] = retention_days
            save_config(self.cfg)
            status = self.analytics.configure(sample_seconds, retention_days)
            if enabled:
                self.analytics.start(self._analytics_snapshot)
            else:
                self.analytics.stop()
                status = self.analytics.status()
            self._log(
                f"Monitoring & Analytics {'enabled' if enabled else 'disabled'} — "
                f"sample {sample_seconds}s, retention {retention_days}d."
            )
            return {"ok": True, "status": status, "enabled": enabled, "result": "Monitoring settings saved."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def clear_analytics_history(self):
        try:
            status = self.analytics.clear()
            self._log("Monitoring & Analytics history cleared.")
            return {"ok": True, "status": status, "result": "Analytics history cleared."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def export_analytics(self, range_seconds=86400, fmt="csv"):
        try:
            fmt = str(fmt or "csv").lower()
            if fmt not in ("csv", "json"):
                raise ValueError("Export format must be csv or json.")
            export_dir = Path.home() / ".bitcoin-miner-studio" / "exports"
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = export_dir / f"monitoring-{stamp}.{fmt}"
            result = self.analytics.export(path, int(range_seconds), fmt=fmt)
            self._log(f"Monitoring analytics exported: {result['path']}")
            return {"ok": True, "export": result, "result": f"Exported {result['rows']} sample(s) to {result['path']}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_state(self):
        self._sync_service_states()
        with self.lock:
            stats = self.miner.stats()
            benchmark_lab = self.benchmark_lab.snapshot()
            benchmark = dict(benchmark_lab.get("stats") or {})
            if self.benchmark.running:
                display_hashrate = benchmark.get("average_hashrate", benchmark.get("hashrate", 0))
                total_hashes = benchmark.get("total_hashes", 0)
                status = "Benchmarking"
                endpoint = "Local SHA-256d benchmark"
                workers = len(self.benchmark.processes)
            else:
                display_hashrate = stats.get("hashrate", 0)
                total_hashes = stats.get("total_hashes", 0)
                status = stats.get("status", "Idle")
                endpoint = stats.get("active_endpoint") or stats.get("endpoint") or "No pool session"
                workers = stats.get("workers", 0)

            decided = int(stats.get("accepted", 0)) + int(stats.get("rejected", 0)) + int(stats.get("stale", 0))
            acceptance = float(stats.get("acceptance_rate", 0.0)) if decided else 0.0
            health = pool_health_score(stats) if stats.get("session_started") else 100
            mode = "LOCAL TEST" if self.local_pool.running else ("REAL POOL" if self.cfg.get("pool_url") and "example.com" not in self.cfg.get("pool_url", "") else "READY")

            diagnostics_state = self.pool_diagnostics.state()
            configured_endpoints = self._configured_pool_endpoints()
            tested_endpoints = list(diagnostics_state.get("endpoints") or [])
            if (
                tested_endpoints
                and tested_endpoints != configured_endpoints
                and not diagnostics_state.get("running")
            ):
                diagnostics_state = self.pool_diagnostics.invalidate(
                    "Pool endpoint configuration changed. Previous diagnostic results were discarded; run Test All Endpoints again."
                )

            asic_solo = self.asic_solo_bridge.stats()
            solo_endpoint = str(asic_solo.get("endpoint") or "").rstrip("/").lower()
            active_worker_ips = {
                str(w.get("ip") or "")
                for w in asic_solo.get("workers", [])
                if w.get("active")
            }

            asics = []
            for ip, d in sorted(self.asic_devices.items()):
                x = dict(d)
                x["alias"] = self.asic_aliases.get(ip, "")
                x["group"] = self.asic_groups.get(ip, "")
                x["note"] = self.asic_notes.get(ip, "")
                x["availability"] = self.fleet_monitor.availability_percent(ip)
                x["health"] = self.fleet_monitor.health_score(d)
                pool_url = str(d.get("pool_url") or "").rstrip("/").lower()
                x["solo_assigned"] = bool(solo_endpoint and pool_url == solo_endpoint)
                x["solo_connected"] = ip in active_worker_ips
                asics.append(x)

            performance_plus = bool(self.cfg.get("performance_plus_enabled", False))
            log_limit = 12 if performance_plus else 30
            share_limit = 10 if performance_plus else 30

            return {
                "mode": mode,
                "status": status,
                "endpoint": endpoint,
                "hashrate": float(display_hashrate or 0),
                "hashrate_text": format_hashrate(display_hashrate),
                "avg_hashrate": float(stats.get("average_hashrate", 0) or 0),
                "avg_hashrate_text": format_hashrate(stats.get("average_hashrate", 0)),
                "peak_hashrate": float(stats.get("peak_hashrate", 0) or 0),
                "peak_hashrate_text": format_hashrate(stats.get("peak_hashrate", 0)),
                "accepted": int(stats.get("accepted", 0)),
                "rejected": int(stats.get("rejected", 0)),
                "stale": int(stats.get("stale", 0)),
                "submitted": int(stats.get("submitted", 0)),
                "acceptance": acceptance,
                "acceptance_text": f"{acceptance:.1f}%" if decided else "—",
                "difficulty": float(stats.get("difficulty", 0) or 0),
                "difficulty_text": format_difficulty(stats.get("difficulty", 0)),
                "expected_share_text": format_eta(stats.get("expected_share_seconds", 0)),
                "total_hashes": int(total_hashes or 0),
                "uptime": float(stats.get("uptime", 0) or 0),
                "uptime_text": format_uptime(stats.get("uptime", 0)),
                "latency_text": f"{float(stats.get('connect_latency_ms', 0) or 0):.1f} ms" if float(stats.get("connect_latency_ms", 0) or 0) > 0 else "—",
                "job": stats.get("job_id") or "—",
                "workers": int(workers or 0),
                "miner_running": bool(self.miner.running),
                "benchmark_running": bool(self.benchmark.running),
                "benchmark_lab": benchmark_lab,
                "local_pool_running": bool(self.local_pool.running),
                "local_pool_endpoint": self.local_pool.endpoint if self.local_pool.running else "",
                "health": health,
                "recent_shares": list(stats.get("recent_shares", []))[:share_limit],
                "pool_profiles": self._pool_profiles_state(),
                "pool_powertools": {
                    "session": {
                        "active_endpoint": stats.get("active_endpoint") or "",
                        "active_endpoint_index": int(stats.get("active_endpoint_index") or 0),
                        "endpoint_count": int(stats.get("endpoint_count") or 0),
                        "endpoints": list(stats.get("endpoints") or []),
                        "failover_enabled": bool(stats.get("failover_enabled")),
                        "failover_count": int(stats.get("failover_count") or 0),
                        "reconnect_count": int(stats.get("reconnect_count") or 0),
                        "connection_attempts": int(stats.get("connection_attempts") or 0),
                        "disconnects": int(stats.get("disconnects") or 0),
                        "last_disconnect_reason": stats.get("last_disconnect_reason") or "",
                        "job_timeout_seconds": int(stats.get("job_timeout_seconds") or self.cfg.get("pool_job_timeout_seconds", 120)),
                        "failover_policy": str(stats.get("failover_policy") or self.cfg.get("pool_failover_policy", "balanced")),
                        "failure_threshold": int(stats.get("failure_threshold") or 1),
                        "primary_recovery_seconds": int(stats.get("primary_recovery_seconds") or self.cfg.get("pool_primary_recovery_seconds", 300)),
                        "primary_recovery_attempts": int(stats.get("primary_recovery_attempts") or 0),
                        "last_failover_reason": str(stats.get("last_failover_reason") or ""),
                        "active_endpoint_uptime_seconds": float(stats.get("active_endpoint_uptime_seconds") or 0),
                        "job_age_seconds": float(stats.get("job_age_seconds") or 0),
                        "job_count": int(stats.get("job_count") or 0),
                        "clean_job_count": int(stats.get("clean_job_count") or 0),
                        "job_update_count": int(stats.get("job_update_count") or 0),
                        "difficulty_changes": int(stats.get("difficulty_changes") or 0),
                        "difficulty_history": list(stats.get("difficulty_history") or [])[:20],
                        "protocol_events": list(stats.get("protocol_events") or [])[:30],
                        "share_response_avg_ms": float(stats.get("share_response_avg_ms") or 0),
                        "share_response_p95_ms": float(stats.get("share_response_p95_ms") or 0),
                        "best_share_difficulty": float(stats.get("best_share_difficulty") or 0),
                        "duplicate_prevented": int(stats.get("duplicate_prevented") or 0),
                        "extranonce1": stats.get("extranonce1") or "",
                        "extranonce2_size": int(stats.get("extranonce2_size") or 0),
                        "connected": bool(stats.get("connected")),
                        "authorized": bool(stats.get("authorized")),
                        "health": health,
                    },
                    "diagnostics": diagnostics_state,
                },
                "logs": list(self.logs[-log_limit:]),
                "asic_devices": asics,
                "asic_solo_bridge": asic_solo,
                "bitcoin_core": dict(self.core_state),
                "core_setup": dict(self.core_setup_state),
                "block_template": template_for_ui(
                    self.template_state,
                    self.cfg.get("template_refresh_seconds", 15),
                ),
                "coinbase": dict(self.coinbase_state),
                "solo_mining": self.solo_miner.stats(),
                "block_submission": dict(self.block_submission_state),
                "system": {"cpu_cores": os.cpu_count() or 1, "known_asics": len(self.asic_known_devices)},
                "security": dict(self.security_state),
                "regtest_lab": self.regtest_controller.state(),
                "analytics": self.analytics.status(),
                "release_candidate": self.release_candidate.state(),
                "diagnostics_center": self.diagnostics_center.state(),
                "update_release_center": self.update_release_center.state(),
                "mining_assistant": self._mining_assistant_snapshot(),
                "hardware_compatibility": self._hardware_compatibility_snapshot(),
                "tray": self._tray_runtime_state(),
                "architecture": self.services.snapshot(),
                "workspace": self.workspace.snapshot(),
                "performance_plus": {
                    "enabled": performance_plus,
                    "ui_refresh_ms": 3000 if performance_plus else 1500,
                    "core_poll_floor_seconds": 20 if performance_plus else 5,
                    "visual_effects": "reduced" if performance_plus else "full",
                },
            }

    def set_performance_plus(self, enabled=False):
        try:
            enabled = bool(enabled)
            self.cfg["performance_plus_enabled"] = enabled
            save_config(self.cfg)
            self._log(
                "Performance+ enabled — reduced UI/GPU overhead and noncritical polling."
                if enabled
                else "Performance+ disabled — restored full visual effects and standard polling."
            )
            return {
                "ok": True,
                "enabled": enabled,
                "result": (
                    "Performance+ ENABLED\n\n"
                    "• Reduced holographic GPU effects\n"
                    "• UI state refresh: 3 seconds\n"
                    "• Charts redraw less often\n"
                    "• Logs/ASIC DOM updates are de-duplicated\n"
                    "• Bitcoin Core health polling floor: 20 seconds\n"
                    "• Block-template freshness remains mining-safe\n"
                    "• Solo-mining hash batch floor: 50,000\n"
                    "• Hidden/minimized window polling is heavily throttled"
                    if enabled
                    else
                    "Performance+ DISABLED\n\n"
                    "Full holographic effects and normal UI polling are restored."
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_ui_theme(self, theme="purple"):
        try:
            normalized = normalize_ui_theme(theme)
            self.cfg["ui_theme"] = normalized
            save_config(self.cfg)
            label = next(
                (item["name"] for item in ui_theme_options() if item["id"] == normalized),
                normalized.title(),
            )
            self._log(f"UI theme changed to {label}.")
            return {
                "ok": True,
                "theme": normalized,
                "name": label,
                "options": ui_theme_options(),
                "result": f"Theme changed to {label}.",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


    def _mining_assistant_snapshot(self, goal=None):
        with self.lock:
            cfg = dict(self.cfg)
            core_setup = dict(self.core_setup_state or {})
            core_state = dict(self.core_state or {})
            devices = [dict(d) for d in self.asic_devices.values()]
            security = dict(self.security_state or {})
            regtest = dict(self.regtest_controller.state() or {})
        try:
            benchmark = dict(self.benchmark.stats() or {})
        except Exception:
            benchmark = {}
        try:
            analytics = dict(self.analytics.status() or {})
        except Exception:
            analytics = {}
        return build_mining_assistant_snapshot(
            cfg,
            core_setup=core_setup,
            core_state=core_state,
            asic_devices=devices,
            security_state=security,
            regtest_state=regtest,
            benchmark_state=benchmark,
            analytics_status=analytics,
            goal=goal,
        )

    def get_mining_assistant_state(self, goal=None):
        try:
            return {
                "ok": True,
                "assistant": self._mining_assistant_snapshot(goal),
                "preferences": {
                    "goal": normalize_goal(self.cfg.get("mining_assistant_goal")),
                    "intro_seen": bool(self.cfg.get("mining_assistant_intro_seen", False)),
                    "completed": bool(self.cfg.get("mining_assistant_completed", False)),
                },
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_mining_assistant_check(self, goal=None):
        """Refresh advisory readiness without starting/scanning/changing anything."""
        try:
            normalized = normalize_goal(goal or self.cfg.get("mining_assistant_goal"))
            self.cfg["mining_assistant_goal"] = normalized
            save_config(self.cfg)
            state = self._mining_assistant_snapshot(normalized)
            self._log(
                f"Mining Assistant guided check completed — {state.get('overall')} "
                f"({state.get('score')}/100), goal: {state.get('goal_name')}."
            )
            return {
                "ok": True,
                "assistant": state,
                "result": f"Mining Assistant check complete: {state.get('overall')} · {state.get('score')}/100",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_mining_assistant_preferences(self, goal=None, intro_seen=None, completed=None):
        try:
            if goal is not None:
                self.cfg["mining_assistant_goal"] = normalize_goal(goal)
            if intro_seen is not None:
                self.cfg["mining_assistant_intro_seen"] = bool(intro_seen)
            if completed is not None:
                self.cfg["mining_assistant_completed"] = bool(completed)
            save_config(self.cfg)
            return {
                "ok": True,
                "goal": normalize_goal(self.cfg.get("mining_assistant_goal")),
                "intro_seen": bool(self.cfg.get("mining_assistant_intro_seen", False)),
                "completed": bool(self.cfg.get("mining_assistant_completed", False)),
                "result": "Mining Assistant preferences saved.",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_profitability_state(self):
        try:
            with self.lock:
                cfg = dict(self.cfg)
                core_state = dict(self.core_state or {})
            defaults = default_profitability_inputs(cfg, core_state)
            return {
                "ok": True,
                "defaults": defaults,
                "core": {
                    "connected": bool(core_state.get("connected")),
                    "chain": core_state.get("chain"),
                    "blocks": core_state.get("blocks") or core_state.get("height"),
                    "difficulty": core_state.get("difficulty"),
                    "status": core_state.get("status"),
                },
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def calculate_profitability(
        self,
        hashrate_hs=0,
        power_watts=0,
        electricity_per_kwh=0.15,
        pool_fee_percent=1.0,
        btc_price=0,
        difficulty=0,
        block_subsidy_btc=3.125,
        avg_fees_btc_per_block=0,
    ):
        try:
            result = profitability_snapshot(
                hashrate_hs=float(hashrate_hs or 0),
                power_watts=float(power_watts or 0),
                electricity_per_kwh=float(electricity_per_kwh or 0),
                pool_fee_percent=float(pool_fee_percent or 0),
                btc_price=float(btc_price or 0),
                difficulty=float(difficulty or 0),
                block_subsidy_btc=float(block_subsidy_btc or 0),
                avg_fees_btc_per_block=float(avg_fees_btc_per_block or 0),
            )
            return {"ok": True, "calculation": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_profitability_preferences(
        self,
        hashrate_hs=0,
        power_watts=0,
        electricity_per_kwh=0.15,
        pool_fee_percent=1.0,
        btc_price=0,
        difficulty=0,
        height=0,
        block_subsidy_btc=3.125,
        avg_fees_btc_per_block=0,
    ):
        try:
            values = {
                "profitability_hashrate_hs": max(0.0, float(hashrate_hs or 0)),
                "profitability_power_watts": max(0.0, float(power_watts or 0)),
                "profitability_electricity_per_kwh": max(0.0, float(electricity_per_kwh or 0)),
                "profitability_pool_fee_percent": max(0.0, min(100.0, float(pool_fee_percent or 0))),
                "profitability_btc_price": max(0.0, float(btc_price or 0)),
                "profitability_difficulty": max(0.0, float(difficulty or 0)),
                "profitability_height": max(0, int(height or 0)),
                "profitability_block_subsidy_btc": max(0.0, float(block_subsidy_btc or 0)),
                "profitability_avg_fees_btc_per_block": max(0.0, float(avg_fees_btc_per_block or 0)),
            }
            self.cfg.update(values)
            save_config(self.cfg)
            return {"ok": True, "result": "Profitability & Power preferences saved.", "values": values}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def use_core_profitability_data(self):
        """Return local-node height/difficulty/subsidy; never fetch market prices."""
        try:
            with self.lock:
                core_state = dict(self.core_state or {})
            if not core_state.get("connected"):
                return {"ok": False, "error": "Bitcoin Core is not currently connected."}
            difficulty = float(core_state.get("difficulty") or 0)
            height = int(core_state.get("blocks") or core_state.get("height") or 0)
            if difficulty <= 0 or height <= 0:
                return {"ok": False, "error": "Bitcoin Core has not reported usable height/difficulty yet."}
            subsidy = block_subsidy_for_height(height)
            return {
                "ok": True,
                "difficulty": difficulty,
                "height": height,
                "block_subsidy_btc": subsidy,
                "chain": core_state.get("chain"),
                "result": f"Loaded height {height:,} and network difficulty from local Bitcoin Core.",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _hardware_compatibility_snapshot(self):
        with self.lock:
            devices = []
            for ip, device in sorted(self.asic_devices.items()):
                row = dict(device)
                row["alias"] = self.asic_aliases.get(ip, "")
                row["group"] = self.asic_groups.get(ip, "")
                row["health"] = self.fleet_monitor.health_score(device)
                row["availability"] = self.fleet_monitor.availability_percent(ip)
                devices.append(row)
            known = list(self.asic_known_devices)
        return compatibility_snapshot(devices, known_devices=known)

    def get_hardware_compatibility_state(self):
        try:
            return {"ok": True, "compatibility": self._hardware_compatibility_snapshot()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def create_hardware_compatibility_report(self):
        """Create a local privacy-sanitized JSON compatibility report."""
        try:
            payload = sanitized_report(self._hardware_compatibility_snapshot())
            export_dir = Path.home() / ".bitcoin-miner-studio" / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = export_dir / f"hardware-compatibility-{stamp}.json"
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._log(f"Sanitized hardware compatibility report created: {path}")
            return {
                "ok": True,
                "path": str(path),
                "report": payload,
                "result": f"Sanitized compatibility report created locally: {path}",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_provenance(self):
        """Public verification/provenance report. No private signing material is stored in the app."""
        try:
            state = dict(verify_integrity())
            with self.lock:
                self.security_state = state
            return {
                "ok": bool(state.get("verified")),
                "security": state,
                "report": provenance_report(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_pool_profiles_state(self):
        try:
            return {"ok": True, "pool_profiles": self._pool_profiles_state()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_pool_profile(self, payload):
        try:
            payload = dict(payload or {})
            if self.local_pool.running:
                return {"ok": False, "error": "Stop the Local Test Pool before saving a real pool profile."}
            profile = self.pool_profiles.upsert(payload)
            password = str(payload.get("pool_password") or "")
            if password:
                self.session_profile_passwords[profile["id"]] = password
                try:
                    write_secret(pool_profile_target(profile["id"]), profile.get("pool_worker", ""), password)
                except Exception as exc:
                    self._log(f"Pool profile credential save warning: {exc}")
            self._log(f"Pool profile saved: {profile['name']}")
            return {
                "ok": True,
                "profile": profile,
                "pool_profiles": self._pool_profiles_state(),
                "result": f"Pool profile saved: {profile['name']}",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delete_pool_profile(self, profile_id):
        try:
            profile_id = str(profile_id or "").strip()
            if not profile_id:
                raise ValueError("Pool profile ID is required.")
            if self.miner.running and profile_id == str(self.cfg.get("active_pool_profile_id") or ""):
                return {"ok": False, "error": "Stop pool mining before deleting the active profile."}
            existing = self.pool_profiles.get(profile_id)
            if not existing:
                return {"ok": False, "error": "Pool profile not found."}
            deleted = self.pool_profiles.delete(profile_id)
            if not deleted:
                return {"ok": False, "error": "Pool profile not found."}
            self.session_profile_passwords.pop(profile_id, None)
            try:
                delete_secret(pool_profile_target(profile_id))
            except Exception as exc:
                self._log(f"Pool profile credential delete warning: {exc}")
            if str(self.cfg.get("active_pool_profile_id") or "") == profile_id:
                self.cfg["active_pool_profile_id"] = ""
                save_config(self.cfg)
            self._log(f"Pool profile deleted: {existing.get('name', profile_id)}")
            return {
                "ok": True,
                "pool_profiles": self._pool_profiles_state(),
                "result": f"Pool profile deleted: {existing.get('name', profile_id)}",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def activate_pool_profile(self, profile_id):
        try:
            if self.local_pool.running:
                return {"ok": False, "error": "Stop the Local Test Pool before activating a real pool profile."}
            if self.miner.running:
                return {"ok": False, "error": "Stop pool mining before switching the active profile."}
            profile = self.pool_profiles.get(profile_id)
            if not profile:
                return {"ok": False, "error": "Pool profile not found."}
            if not profile.get("enabled", True):
                return {"ok": False, "error": "This pool profile is disabled."}
            config, password = self._apply_profile(profile)
            self._log(f"Activated pool profile: {profile['name']}")
            return {
                "ok": True,
                "profile": profile,
                "pool_config": self._pool_config_for_ui(),
                "credential_stored": bool(password),
                "pool_profiles": self._pool_profiles_state(),
                "result": (
                    f"Activated pool profile: {profile['name']}"
                    + ("" if password else " · enter its password before mining if the pool requires one")
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def test_pool_profile(self, profile_id):
        try:
            profile = self.pool_profiles.get(profile_id)
            if not profile:
                return {"ok": False, "error": "Pool profile not found."}
            endpoints = normalize_endpoints(profile.get("pool_url", ""), profile.get("pool_backup_urls", []))
            password = self._profile_password(profile_id) or "x"
            state = self.pool_diagnostics.start(
                endpoints,
                worker=profile.get("pool_worker", ""),
                password=password,
                timeout=5.0,
            )
            return {
                "ok": True,
                "diagnostics": state,
                "result": f"Testing {len(endpoints)} endpoint(s) for profile: {profile['name']}",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def export_pool_profiles(self):
        try:
            payload = self.pool_profiles.sanitized_export(self.cfg.get("active_pool_profile_id", ""))
            export_dir = Path.home() / ".bitcoin-miner-studio" / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = export_dir / f"pool-profiles-sanitized-{stamp}.json"
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            report = json.dumps(payload, indent=2)
            self._log(f"Sanitized pool profile export created: {path}")
            return {
                "ok": True,
                "path": str(path),
                "report": report,
                "result": f"Sanitized pool profile export created locally: {path}",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_pool_config(self, payload):
        try:
            self._save_pool(payload)
            self._log("Pool configuration saved.")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def start_mining(self, payload):
        trusted, security_error = self._require_trusted_build("starting pool mining")
        if not trusted:
            return {"ok": False, "error": security_error}
        try:
            self._save_pool(payload)
            if self.benchmark.running:
                self.benchmark.stop()
            if self.miner.running:
                return {"ok": True, "message": "Mining is already running."}
            password = self._password(payload, "pool_password", self.session_pool_password) or "x"
            suggested = self.cfg.get("suggest_difficulty") if self.cfg.get("suggest_difficulty_enabled") else None
            self.miner.start(
                self.cfg.get("pool_url", ""),
                self.cfg.get("pool_worker", ""),
                password,
                int(self.cfg.get("mining_processes", 2)),
                suggest_difficulty=suggested,
                backup_urls=list(self.cfg.get("pool_backup_urls", []) or []),
                failover_enabled=bool(self.cfg.get("pool_failover_enabled", True)),
                job_timeout_seconds=int(self.cfg.get("pool_job_timeout_seconds", 120)),
                failover_policy=normalize_failover_policy(self.cfg.get("pool_failover_policy", "balanced")),
                primary_recovery_seconds=int(self.cfg.get("pool_primary_recovery_seconds", 300)),
            )
            self._log("Pool mining started from holographic UI.")
            return {"ok": True}
        except Exception as exc:
            self._log(f"Mining error: {exc}")
            return {"ok": False, "error": str(exc)}

    def stop_mining(self):
        try:
            self.miner.stop()
            self._log("Pool mining stopped; session statistics retained.")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def reset_session(self):
        try:
            self.miner.reset_stats()
            self._log("Mining session statistics reset.")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def start_benchmark(self, workers=2, duration_seconds=0, label="Quick Benchmark"):
        """Backward-compatible Dashboard benchmark entrypoint backed by Benchmark Lab 2.0."""
        try:
            if self.miner.running:
                self.miner.stop()
            workers = max(1, min(64, int(workers)))
            duration_seconds = max(0, min(3600, int(duration_seconds or 0)))
            self.cfg["benchmark_processes"] = workers
            if duration_seconds:
                self.cfg["benchmark_duration_seconds"] = duration_seconds
            save_config(self.cfg)
            lab = self.benchmark_lab.start(workers, duration_seconds, label, source="dashboard")
            return {"ok": True, "benchmark_lab": lab}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def start_benchmark_lab(self, workers=2, duration_seconds=30, label="Standard"):
        try:
            if self.miner.running:
                self.miner.stop()
            workers = max(1, min(64, int(workers)))
            duration_seconds = max(3, min(3600, int(duration_seconds or 30)))
            self.cfg["benchmark_processes"] = workers
            self.cfg["benchmark_duration_seconds"] = duration_seconds
            save_config(self.cfg)
            lab = self.benchmark_lab.start(workers, duration_seconds, label, source="benchmark-lab")
            return {"ok": True, "benchmark_lab": lab, "result": f"{label} benchmark started."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def stop_benchmark(self):
        try:
            lab = self.benchmark_lab.stop("manual")
            return {"ok": True, "benchmark_lab": lab}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_benchmark_lab(self):
        try:
            return {"ok": True, "benchmark_lab": self.benchmark_lab.snapshot()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def start_benchmark_scaling_test(self, seconds_per_step=8):
        try:
            if self.miner.running:
                self.miner.stop()
            seconds_per_step = max(3, min(120, int(seconds_per_step or 8)))
            self.cfg["benchmark_scaling_seconds"] = seconds_per_step
            save_config(self.cfg)
            lab = self.benchmark_lab.start_suite(seconds_per_step=seconds_per_step)
            return {"ok": True, "benchmark_lab": lab, "result": "Worker Scaling Test started."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def clear_benchmark_history(self):
        try:
            lab = self.benchmark_lab.clear_history()
            self._log("Benchmark Lab history cleared.")
            return {"ok": True, "benchmark_lab": lab, "result": "Benchmark history cleared."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def export_benchmark_history(self, fmt="json"):
        try:
            fmt = str(fmt or "json").strip().lower()
            export_dir = Path.home() / ".bitcoin-miner-studio" / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = export_dir / f"benchmark-lab-{stamp}.{fmt}"
            result = self.benchmark_lab.export(path, fmt=fmt)
            self._log(f"Benchmark Lab history exported: {result['path']}")
            return {"ok": True, "export": result, "result": f"Exported {result['rows']} benchmark result(s) to {result['path']}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # v1.7.0 — Mining Academy
    # Local educational state only. These endpoints deliberately have no
    # access to wallet, pool, ASIC, RPC or block-submission controls.
    # ------------------------------------------------------------------
    def get_mining_academy_state(self):
        try:
            return {"ok": True, "academy": self.mining_academy.state()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_academy_lesson_status(self, lesson_id, status):
        try:
            state = self.mining_academy.set_lesson_status(lesson_id, status)
            return {"ok": True, "academy": state, "result": "Mining Academy progress saved locally."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def submit_academy_quiz(self, lesson_id, answer_index):
        try:
            result = self.mining_academy.submit_quiz(lesson_id, answer_index)
            return {"ok": True, "quiz": {k: v for k, v in result.items() if k != "state"}, "academy": result["state"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def reset_academy_progress(self):
        try:
            state = self.mining_academy.reset_progress()
            self._log("Mining Academy local progress reset.")
            return {"ok": True, "academy": state, "result": "Mining Academy progress reset."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_academy_hash_lab(self, text=""):
        try:
            result = self.mining_academy.hash_lab(text)
            return {"ok": True, "lab": {k: v for k, v in result.items() if k != "state"}, "academy": result["state"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_academy_difficulty_lab(self, payload=None):
        try:
            payload = dict(payload or {})
            result = self.mining_academy.difficulty_lab(payload.get("difficulty", 1.0), payload.get("bits"))
            return {"ok": True, "lab": {k: v for k, v in result.items() if k != "state"}, "academy": result["state"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_academy_header_lab(self, payload=None):
        try:
            result = self.mining_academy.block_header_lab(payload)
            return {"ok": True, "lab": {k: v for k, v in result.items() if k != "state"}, "academy": result["state"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_academy_merkle_lab(self, txids=None):
        try:
            result = self.mining_academy.merkle_lab(txids or [])
            return {"ok": True, "lab": {k: v for k, v in result.items() if k != "state"}, "academy": result["state"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_academy_nonce_lab(self, payload=None):
        try:
            result = self.mining_academy.nonce_lab(payload)
            return {"ok": True, "lab": {k: v for k, v in result.items() if k != "state"}, "academy": result["state"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _local_test_restore_snapshot(self):
        return {
            key: (
                list(self.cfg.get(key) or [])
                if key == "pool_backup_urls"
                else self.cfg.get(key)
            )
            for key in POOL_RESTORE_KEYS
        }

    def _restore_pool_after_local_test(self):
        previous_endpoints = self._configured_pool_endpoints()
        restore = dict(self.cfg.get("pool_restore_after_local_test") or {})
        if restore:
            for key in POOL_RESTORE_KEYS:
                if key in restore:
                    self.cfg[key] = restore[key]
        else:
            self.cfg["pool_url"] = ""
            self.cfg["pool_backup_urls"] = []
            if self.cfg.get("pool_worker") == "local.worker1":
                self.cfg["pool_worker"] = ""
        self.cfg["pool_url_ephemeral_local_test"] = False
        self.cfg["pool_restore_after_local_test"] = {}
        save_config(self.cfg)
        self._invalidate_pool_diagnostics_if_changed(previous_endpoints)

    def toggle_local_pool(self):
        try:
            if self.local_pool.running:
                if self.miner.running and self.cfg.get("pool_url", "") == self.local_pool.endpoint:
                    self.miner.stop()
                old_endpoint = self.local_pool.endpoint
                self.local_pool.stop()
                self._restore_pool_after_local_test()
                self._log(
                    f"Local test pool stopped; ephemeral endpoint {old_endpoint} was discarded "
                    "and the previous pool configuration was restored."
                )
                return {
                    "ok": True,
                    "running": False,
                    "restored_pool_url": self.cfg.get("pool_url", ""),
                    "pool_config": self._pool_config_for_ui(),
                    "local_password": "",
                    "result": (
                        "Local Test Pool stopped. Its temporary localhost port was discarded "
                        "and the previous pool configuration was restored."
                    ),
                }

            # Preserve the user's non-local pool configuration before replacing
            # it with an ephemeral localhost endpoint.
            if not self.cfg.get("pool_url_ephemeral_local_test"):
                self.cfg["pool_restore_after_local_test"] = self._local_test_restore_snapshot()

            previous_endpoints = self._configured_pool_endpoints()
            endpoint = self.local_pool.start()
            self.cfg["pool_url"] = endpoint
            self.cfg["pool_backup_urls"] = []
            self.cfg["pool_worker"] = "local.worker1"
            self.cfg["pool_failover_enabled"] = False
            self.cfg["pool_failover_policy"] = "manual"
            self.cfg["pool_primary_recovery_seconds"] = 0
            self.cfg["suggest_difficulty_enabled"] = False
            self.cfg["suggest_difficulty"] = float(
                getattr(self.local_pool, "difficulty", 0.000001) or 0.000001
            )
            self.cfg["pool_url_ephemeral_local_test"] = True
            self.session_pool_password = "x"
            save_config(self.cfg)
            self._invalidate_pool_diagnostics_if_changed(previous_endpoints)
            self._log(f"Local test pool running at {endpoint}.")
            return {
                "ok": True,
                "running": True,
                "endpoint": endpoint,
                "pool_config": self._pool_config_for_ui(),
                "local_password": "x",
                "result": (
                    f"Local Test Pool started at {endpoint}. "
                    "Worker local.worker1 and password x were selected automatically. "
                    "Suggested difficulty is disabled so the Local Test Pool can use its fast validation difficulty. "
                    "This port is temporary and will never be reused after the pool/app stops."
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def start_pool_diagnostics(self, payload):
        try:
            self._save_pool(payload)
            password = self._password(
                payload, "pool_password", self.session_pool_password
            ) or "x"
            endpoints = normalize_endpoints(
                self.cfg.get("pool_url", ""),
                self.cfg.get("pool_backup_urls", []),
            )

            primary = endpoints[0] if endpoints else ""
            looks_like_app_local = (
                self.cfg.get("pool_worker") == "local.worker1"
                and (
                    primary.startswith("stratum+tcp://127.0.0.1:")
                    or primary.startswith("stratum+tcp://localhost:")
                )
            )
            if looks_like_app_local and not self.local_pool.running:
                return {
                    "ok": False,
                    "error": (
                        "The configured Local Test Pool endpoint is no longer running. "
                        "Local Test Pool ports are temporary. Click Start Local Test Pool "
                        "to allocate a fresh endpoint, then run Test All Endpoints again."
                    ),
                }

            state = self.pool_diagnostics.start(
                endpoints,
                worker=self.cfg.get("pool_worker", ""),
                password=password,
                timeout=5.0,
            )
            self._log(
                f"Pool PowerTools diagnostics started for {len(endpoints)} endpoint(s)."
            )
            return {
                "ok": True,
                "diagnostics": state,
                "result": (
                    f"Background diagnostics started for {len(endpoints)} endpoint(s). "
                    "The app will remain responsive."
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def clear_pool_diagnostics(self):
        try:
            state = self.pool_diagnostics.clear()
            return {"ok": True, "diagnostics": state, "result": "Pool diagnostics cleared."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_pool_diagnostic_report(self):
        try:
            state = self.pool_diagnostics.state()
            return {"ok": True, "diagnostics": state, "report": diagnostic_report(state)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def test_pool(self, payload):
        try:
            self._save_pool(payload)
            password = self._password(payload, "pool_password", self.session_pool_password) or "x"
            result = test_stratum(self.cfg.get("pool_url", ""), self.cfg.get("pool_worker", ""), password)
            self._log("Pool connectivity test completed.")
            return {"ok": True, "result": result}
        except Exception as exc:
            self._log(f"Pool test failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def detect_core_setup(self):
        try:
            state = detect_bitcoin_core(self.cfg)
            with self.lock:
                self.core_setup_state = dict(state)
            self._log(
                f"Bitcoin Core detection: network={state.get('network')}, "
                f"RPC {'listening' if state.get('rpc_listening') else 'not listening'}, "
                f"cookie {'available' if state.get('cookie_exists') else 'unavailable'}."
            )
            return {"ok": True, "setup": state, "result": detection_report(state)}
        except Exception as exc:
            self._log(f"Bitcoin Core detection failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def auto_configure_core(self):
        try:
            state = detect_bitcoin_core(self.cfg)
            if not state.get("detected") and not state.get("installation_found"):
                with self.lock:
                    self.core_setup_state = dict(state)
                return {
                    "ok": False,
                    "error": (
                        "Bitcoin Core is not installed or could not be located. "
                        "Use Locate Core EXE for a custom installation, or Download Bitcoin Core first."
                    ),
                    "setup": state,
                }
            values = auto_config_values(state, self.cfg)
            self.cfg.update(values)
            save_config(self.cfg)
            with self.lock:
                self.core_setup_state = dict(state)
            self._log(
                f"Bitcoin Core Auto Configure applied: {self.cfg.get('core_network')} · "
                f"{self.cfg.get('rpc_url')} · {self.cfg.get('core_auth_mode')} auth."
            )
            # Refresh immediately using the selected auth method.
            core = self._refresh_core_snapshot(log_transition=True, timeout=5.0)
            threading.Thread(
                target=lambda: self._refresh_block_template(log_transition=True, timeout=5.0),
                daemon=True,
            ).start()
            return {
                "ok": True,
                "setup": state,
                "config": {
                    "rpc_url": self.cfg.get("rpc_url", ""),
                    "rpc_user": self.cfg.get("rpc_user", ""),
                    "core_auth_mode": self.cfg.get("core_auth_mode", "password"),
                    "core_data_dir": self.cfg.get("core_data_dir", ""),
                    "core_executable": self.cfg.get("core_executable", ""),
                    "core_cookie_path": self.cfg.get("core_cookie_path", ""),
                    "core_network": self.cfg.get("core_network", "main"),
                },
                "core": core,
                "result": detection_report(state),
            }
        except Exception as exc:
            self._log(f"Bitcoin Core Auto Configure failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def locate_core_executable(self):
        try:
            if self.window is None:
                return {"ok": False, "error": "The native file picker is not available yet."}
            import webview
            selected = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "Bitcoin Core node (bitcoin-qt.exe;bitcoind.exe)",
                    "Executable files (*.exe)",
                    "All files (*.*)",
                ),
            )
            if not selected:
                return {"ok": False, "error": "No executable selected."}

            exe = validate_core_executable(selected[0])
            self.cfg["core_executable"] = str(exe)
            save_config(self.cfg)
            state = detect_bitcoin_core(self.cfg)
            with self.lock:
                self.core_setup_state = dict(state)
            self._log(f"Bitcoin Core executable selected: {exe}")
            return {
                "ok": True,
                "setup": state,
                "config": {"core_executable": str(exe)},
                "result": f"Bitcoin Core executable selected:\n{exe}",
            }
        except Exception as exc:
            self._log(f"Locate Bitcoin Core executable failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def locate_core_data_dir(self):
        try:
            if self.window is None:
                return {"ok": False, "error": "The native folder picker is not available yet."}
            import webview
            selected = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            if not selected:
                return {"ok": False, "error": "No data directory selected."}

            path = Path(selected[0]).resolve()
            if not path.exists() or not path.is_dir():
                return {"ok": False, "error": f"Selected folder does not exist: {path}"}

            self.cfg["core_data_dir"] = str(path)
            save_config(self.cfg)
            state = detect_bitcoin_core(self.cfg)
            with self.lock:
                self.core_setup_state = dict(state)
            self._log(f"Bitcoin Core data directory selected: {path}")
            return {
                "ok": True,
                "setup": state,
                "config": {"core_data_dir": str(path)},
                "result": f"Bitcoin Core data directory selected:\n{path}",
            }
        except Exception as exc:
            self._log(f"Locate Bitcoin Core data directory failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def start_bitcoin_core(self):
        try:
            state = detect_bitcoin_core(self.cfg)

            # Prefer the user's pinned executable/path over whatever another
            # currently running Core instance happened to reveal.
            executable = str(self.cfg.get("core_executable", "") or "").strip() or state.get("executable", "")
            if not executable:
                return {
                    "ok": False,
                    "error": "Bitcoin Core executable is not known. Use Locate Core EXE first.",
                    "setup": state,
                }

            configured_dir = str(self.cfg.get("core_data_dir", "") or "").strip()
            launch_data_dir = configured_dir or str(state.get("data_dir", "") or "").strip()
            if not launch_data_dir:
                return {
                    "ok": False,
                    "error": (
                        "No Bitcoin data directory is pinned. Use Choose Data Folder first. "
                        "Miner Studio will not launch Bitcoin Core with an implicit/default profile directory."
                    ),
                    "setup": state,
                }

            data_path = Path(os.path.expandvars(os.path.expanduser(launch_data_dir)))
            if not data_path.exists() or not data_path.is_dir():
                return {
                    "ok": False,
                    "error": (
                        f"Configured Bitcoin data directory does not exist: {data_path}. "
                        "Miner Studio refused to fall back to the default Windows Bitcoin directory."
                    ),
                    "setup": state,
                }

            guard = core_data_dir_guard(
                launch_data_dir,
                state.get("running_processes") or [],
                state.get("registry_data_dirs") or [],
                process_running=bool(state.get("process_running")),
            )

            if state.get("process_running"):
                status = str(guard.get("status") or "")
                if not guard.get("safe"):
                    message = guard.get("message") or "The running Bitcoin Core data directory cannot be verified."
                    self._log(f"Bitcoin Core Data-Dir Guard blocked duplicate launch: {status} · {message}")
                    return {
                        "ok": False,
                        "error": (
                            f"Bitcoin Core Data-Dir Guard: {message} "
                            f"Configured directory: {launch_data_dir}. "
                            "Close the existing Bitcoin Core window, then press Start Bitcoin Core here."
                        ),
                        "setup": state,
                        "data_dir_guard": guard,
                    }

                # Never open a second Core process when the intended node is
                # already running; refresh it instead.
                self._log(
                    f"Bitcoin Core already running with Data-Dir Guard {status}: {launch_data_dir}. "
                    "Duplicate launch skipped."
                )
                return {
                    "ok": True,
                    "already_running": True,
                    "setup": state,
                    "data_dir_guard": guard,
                    "result": (
                        "Bitcoin Core is already running with the configured data directory. "
                        "Miner Studio did not launch a duplicate process."
                    ),
                }

            exe = launch_bitcoin_core(executable, launch_data_dir)

            # Pin the exact launch directory for subsequent starts. This is
            # intentionally persisted only after all validation above succeeds.
            self.cfg["core_executable"] = str(executable)
            self.cfg["core_data_dir"] = str(data_path)
            save_config(self.cfg)

            self._log(f"Started Bitcoin Core: {exe} · explicit -datadir={data_path}")

            state = detect_bitcoin_core(self.cfg)
            with self.lock:
                self.core_setup_state = dict(state)
            return {
                "ok": True,
                "setup": state,
                "launch_data_dir": str(data_path),
                "result": (
                    f"Bitcoin Core start requested with explicit data directory:\n{data_path}\n\n"
                    "Miner Studio will not fall back to the default Windows Bitcoin profile directory."
                ),
            }
        except Exception as exc:
            self._log(f"Start Bitcoin Core failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def open_core_data_dir(self):
        try:
            path = str(self.cfg.get("core_data_dir", "") or "").strip()
            if not path:
                state = detect_bitcoin_core(self.cfg)
                path = state.get("data_dir", "")
            p = Path(path) if path else None
            if not p or not p.exists() or not p.is_dir():
                return {"ok": False, "error": "No verified Bitcoin Core data directory is available."}
            if sys.platform.startswith("win"):
                os.startfile(str(p))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def download_bitcoin_core(self):
        try:
            webbrowser.open("https://bitcoincore.org/en/download/")
            self._log("Opened the official Bitcoin Core download page.")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def core_setup_recommendation(self):
        state = detect_bitcoin_core(self.cfg)
        with self.lock:
            self.core_setup_state = dict(state)
        return {
            "ok": True,
            "setup": state,
            "result": recommended_config_snippet(state.get("network", "main")),
        }

    def save_core_config(self, payload):
        try:
            self._save_core(payload)
            self.core_setup_state = detect_bitcoin_core(self.cfg)
            self._log("Bitcoin Core configuration saved.")
            threading.Thread(
                target=lambda: self._refresh_core_snapshot(log_transition=True, timeout=5.0),
                daemon=True,
            ).start()
            threading.Thread(
                target=lambda: self._refresh_block_template(log_transition=True, timeout=5.0),
                daemon=True,
            ).start()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def refresh_core(self):
        state = self._refresh_core_snapshot(log_transition=True, timeout=6.0)
        if state.get("connected"):
            return {"ok": True, "core": state, "result": snapshot_report(state)}
        return {"ok": False, "error": state.get("error", "Bitcoin Core RPC is unavailable."), "core": state}

    def test_core(self, payload):
        try:
            self._save_core(payload)
            state = self._refresh_core_snapshot(log_transition=True, timeout=6.0)
            if not state.get("connected"):
                return {"ok": False, "error": state.get("error", "Bitcoin Core RPC is unavailable."), "core": state}
            self._log("Bitcoin Core integration test completed: all v0.4.2.1 node-health RPCs succeeded.")
            return {"ok": True, "result": snapshot_report(state), "core": state}
        except Exception as exc:
            self._log(f"Bitcoin Core test failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def refresh_block_template(self):
        state = self._refresh_block_template(log_transition=True, timeout=7.0)
        state_ui = template_for_ui(state, self.cfg.get("template_refresh_seconds", 15))
        if state.get("available"):
            return {"ok": True, "template": state_ui, "result": template_report(state)}
        return {
            "ok": False,
            "error": state.get("error", "getblocktemplate is unavailable."),
            "template": state_ui,
        }

    def test_block_template(self, payload=None):
        try:
            if payload:
                self._save_core(payload)
            state = self._refresh_block_template(log_transition=True, timeout=7.0)
            state_ui = template_for_ui(state, self.cfg.get("template_refresh_seconds", 15))
            if not state.get("available"):
                return {
                    "ok": False,
                    "error": state.get("error", "getblocktemplate is unavailable."),
                    "template": state_ui,
                }
            self._log("Block Template Engine test completed: getblocktemplate parsed and validated.")
            return {"ok": True, "template": state_ui, "result": template_report(state)}
        except Exception as exc:
            self._log(f"Block template test failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def save_coinbase_config(self, payload):
        try:
            if self.solo_miner.running:
                self.solo_miner.stop("Payout configuration changed.")
            if self.asic_solo_bridge.running:
                self.asic_solo_bridge.stop("Payout configuration changed; ASIC Solo Bridge stopped.")
            self.solo_miner.clear_candidate()
            with self.lock:
                self._preserved_candidate_bundle = None
                self._preserved_candidate_source = ""
                self._assembled_candidate = None
                self.block_submission_state = unavailable_submission_state(
                    "Payout configuration changed; waiting for a new target-valid candidate."
                )
            address, tag, extranonce_size = self._coinbase_payload_values(payload or {})
            if address:
                decode_payout_address(address, self.cfg.get("core_network", "main"))
            self.cfg["coinbase_payout_address"] = address
            self.cfg["coinbase_tag"] = tag
            self.cfg["coinbase_extranonce_size"] = extranonce_size
            save_config(self.cfg)
            state = unavailable_coinbase(
                "Payout configuration saved. Click Build Coinbase Preview when you want a fresh preview."
            )
            with self.lock:
                self.coinbase_state = dict(state)
            self._log("Coinbase & payout configuration saved.")
            return {"ok": True, "coinbase": state}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def validate_payout_address(self, payload):
        try:
            address, tag, extranonce_size = self._coinbase_payload_values(payload or {})
            decoded = decode_payout_address(address, self.cfg.get("core_network", "main"))
            return {
                "ok": True,
                "address": decoded,
                "result": (
                    "PAYOUT ADDRESS VALID\n\n"
                    f"Network: {decoded.get('network')}\n"
                    f"Type: {decoded.get('type')}\n"
                    f"Address: {decoded.get('address')}\n"
                    f"scriptPubKey: {decoded.get('script_pubkey')}\n\n"
                    "Only the public payout address is used. No private key or seed phrase is needed."
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def build_coinbase_preview(self, payload):
        try:
            address, tag, extranonce_size = self._coinbase_payload_values(payload or {})
            with self.lock:
                template = dict(self.template_state)
            if not template.get("available"):
                return {
                    "ok": False,
                    "error": (
                        "No ready block template is available yet. Click Refresh Template first, "
                        "then build the coinbase preview."
                    ),
                }
            state = build_coinbase_transaction(
                template, address, network=self.cfg.get("core_network", "main"),
                tag=tag, extranonce_size=extranonce_size,
            )
            # Persist only after the address/template successfully validate.
            self.cfg["coinbase_payout_address"] = address
            self.cfg["coinbase_tag"] = tag
            self.cfg["coinbase_extranonce_size"] = extranonce_size
            save_config(self.cfg)
            with self.lock:
                self.coinbase_state = dict(state)
            self._log(
                f"Coinbase preview built for height {state.get('height', 0):,}: "
                f"{state.get('coinbase_value_btc', 0):.8f} BTC to {state.get('payout_type')}."
            )
            return {"ok": True, "coinbase": state, "result": coinbase_report(state)}
        except Exception as exc:
            state = unavailable_coinbase(str(exc))
            with self.lock:
                self.coinbase_state = state
            self._log(f"Coinbase preview failed: {exc}")
            return {"ok": False, "error": str(exc), "coinbase": state}

    def _solo_payload_values(self, payload=None):
        payload = payload or {}
        try: batch_size = int(payload.get("solo_batch_size", self.cfg.get("solo_batch_size", 20000)))
        except (TypeError, ValueError): batch_size = 20000
        try: roll_hashes = int(payload.get("solo_extranonce_roll_hashes", self.cfg.get("solo_extranonce_roll_hashes", 2000000)))
        except (TypeError, ValueError): roll_hashes = 2000000
        batch_size = max(500, min(250000, batch_size)); roll_hashes = max(batch_size, min(50000000, roll_hashes))
        auto_new = bool(payload.get("solo_auto_new_template", self.cfg.get("solo_auto_new_template", True)))
        return batch_size, roll_hashes, auto_new

    def test_solo_mining_pipeline(self, payload):
        try:
            address, tag, extranonce_size = self._coinbase_payload_values(payload or {})
            with self.lock: template = dict(self.template_state); core = dict(self.core_state)
            if not core.get("connected"): return {"ok": False, "error": "Bitcoin Core must be connected before testing solo mining."}
            if core.get("initialblockdownload"): return {"ok": False, "error": "Bitcoin Core is still in Initial Block Download. Wait for 100% sync."}
            if not template.get("available"): return {"ok": False, "error": "Refresh the Block Template Engine first."}
            if not address: return {"ok": False, "error": "Enter a public Bitcoin payout address first."}
            work = prepare_solo_work(template, address, network=self.cfg.get("core_network","main"), tag=tag, extranonce_size=extranonce_size, extranonce_value=0)
            one = search_nonce_batch(work, 0, 1); header = work["header_prefix"] + (0).to_bytes(4,"little")
            result = ("SOLO MINING PIPELINE VERIFIED\n\n" f"Height: {work.get('height',0):,}\n" f"Transactions: {work.get('transactions',0):,}\n" f"Coinbase TXID: {work.get('coinbase',{}).get('txid')}\n" f"Merkle root: {work.get('merkle_root')}\n" f"Header size: {len(header)} bytes\n" f"Nonce 0 hash: {one.get('best_hash')}\n" f"Network target: {work.get('target')}\n" f"Target met: {'Yes' if one.get('candidate') else 'No (normal on mainnet)'}\n\nHeader construction, merkle-root calculation, SHA-256d hashing, and target comparison passed.")
            return {"ok": True, "result": result}
        except Exception as exc:
            self._log(f"Solo Mining pipeline test failed: {exc}"); return {"ok": False, "error": str(exc)}

    def start_solo_mining(self, payload):
        trusted, security_error = self._require_trusted_build("starting solo mining")
        if not trusted:
            return {"ok": False, "error": security_error}
        try:
            address, tag, extranonce_size = self._coinbase_payload_values(payload or {}); batch_size, roll_hashes, auto_new = self._solo_payload_values(payload or {})
            with self.lock: template = dict(self.template_state); core = dict(self.core_state)
            if not core.get("connected"): return {"ok":False,"error":"Bitcoin Core must be connected before solo mining."}
            if core.get("initialblockdownload"): return {"ok":False,"error":"Bitcoin Core must be fully synced before solo mining."}
            if not template.get("available"): return {"ok":False,"error":"No ready block template is available. Click Refresh Template first."}
            if not address: return {"ok":False,"error":"Enter a public Bitcoin payout address first."}
            if self.benchmark.running: self.benchmark.stop()
            if self.miner.running: self.miner.stop()
            self.solo_miner.clear_candidate()
            with self.lock:
                self._preserved_candidate_bundle = None
                self._preserved_candidate_source = ""
                self._assembled_candidate = None
                self.block_submission_state = unavailable_submission_state(
                    "Solo mining started; waiting for a target-valid candidate."
                )
            self.cfg["coinbase_payout_address"]=address; self.cfg["coinbase_tag"]=tag; self.cfg["coinbase_extranonce_size"]=extranonce_size; self.cfg["solo_batch_size"]=batch_size; self.cfg["solo_extranonce_roll_hashes"]=roll_hashes; self.cfg["solo_auto_new_template"]=auto_new; save_config(self.cfg)
            effective_batch_size = (
                max(batch_size, 50000)
                if bool(self.cfg.get("performance_plus_enabled", False))
                else batch_size
            )
            self._solo_template_failure_count = 0
            state=self.solo_miner.start(template,address,network=self.cfg.get("core_network","main"),tag=tag,extranonce_size=extranonce_size,batch_size=effective_batch_size,extranonce_roll_hashes=roll_hashes,auto_new_template=auto_new)
            self._log(
                f"Solo Mining Engine started at height {int(state.get('work_height') or 0):,} "
                f"with batch {int(state.get('batch_size') or effective_batch_size):,}."
            )
            return {"ok":True,"solo":state,"result":solo_mining_report(state)}
        except Exception as exc:
            self._log(f"Solo Mining start failed: {exc}"); return {"ok":False,"error":str(exc)}

    def stop_solo_mining(self):
        try:
            state=self.solo_miner.stop()
            self._log("Solo Mining Engine stopped by user.")
            return {"ok":True,"solo":state,"result":solo_mining_report(state)}
        except Exception as exc:
            return {"ok":False,"error":str(exc)}

    def reset_solo_mining(self):
        try:
            state=self.solo_miner.reset_stats(); self._log("Solo Mining Engine statistics reset."); return {"ok":True,"solo":state,"result":solo_mining_report(state)}
        except Exception as exc: return {"ok":False,"error":str(exc)}

    def _submission_credentials(self):
        username, password = self._core_credentials()
        return self.cfg.get("rpc_url", ""), username, password

    def _submission_job_state(self, *, status, detail, operation, busy=True):
        with self.lock:
            state = dict(self.block_submission_state or unavailable_submission_state())
            state["status"] = status
            state["detail"] = detail
            state["operation"] = operation
            state["busy"] = bool(busy)
            state["error"] = ""
            self.block_submission_state = state
            return dict(state)

    def _run_submission_job(self, operation, callable_):
        try:
            result = callable_()
            with self.lock:
                current = dict(self.block_submission_state or unavailable_submission_state())

                # Preserve the rich operation-specific state returned by the
                # synchronous implementation, but do not expose raw block hex.
                returned_state = result.get("submission") or result.get("assembly")
                if isinstance(returned_state, dict):
                    current.update(returned_state)

                current["busy"] = False
                current["operation"] = ""
                current["result_text"] = str(
                    result.get("result")
                    or result.get("error")
                    or current.get("detail")
                    or f"{operation} finished."
                )
                if result.get("ok"):
                    current["error"] = ""
                else:
                    current["error"] = str(result.get("error") or "Operation failed.")
                self.block_submission_state = current

            if result.get("ok"):
                self._log(f"{operation} completed.")
            else:
                self._log(f"{operation} failed: {result.get('error', 'unknown error')}")
        except Exception as exc:
            with self.lock:
                current = dict(self.block_submission_state or unavailable_submission_state())
                current["busy"] = False
                current["operation"] = ""
                current["status"] = "Error"
                current["detail"] = str(exc)
                current["result_text"] = f"ERROR: {exc}"
                current["error"] = str(exc)
                self.block_submission_state = current
            self._log(f"{operation} background job failed: {exc}")
        finally:
            self._submission_job_lock.release()

    def _launch_submission_job(self, operation, status, detail, callable_):
        if not self._submission_job_lock.acquire(blocking=False):
            with self.lock:
                current = dict(self.block_submission_state or unavailable_submission_state())
                active = current.get("operation") or "another block operation"
            return {
                "ok": False,
                "error": f"{active} is already running. Wait for it to finish.",
                "submission": current,
            }

        state = self._submission_job_state(
            status=status,
            detail=detail,
            operation=operation,
            busy=True,
        )
        threading.Thread(
            target=self._run_submission_job,
            args=(operation, callable_),
            name="BlockSubmissionWorker",
            daemon=True,
        ).start()
        return {
            "ok": True,
            "started": True,
            "submission": state,
            "result": f"{operation} started in the background. Bitcoin Miner Studio will remain responsive.",
        }

    def test_block_assembly(self, payload):
        payload = dict(payload or {})
        return self._launch_submission_job(
            "Block assembly test",
            "Testing Assembly",
            "Building and validating a complete current-template block in the background.",
            lambda: self._test_block_assembly_sync(payload),
        )

    def assemble_solo_candidate(self):
        return self._launch_submission_job(
            "Candidate assembly",
            "Assembling Candidate",
            "Assembling the preserved target-valid candidate in the background.",
            self._assemble_solo_candidate_sync,
        )

    def validate_solo_candidate(self):
        return self._launch_submission_job(
            "Bitcoin Core proposal validation",
            "Validating Proposal",
            "Checking the chain tip and sending the complete block to Bitcoin Core proposal mode in the background.",
            self._validate_solo_candidate_sync,
        )

    def submit_solo_candidate(self, authorized=False):
        trusted, security_error = self._require_trusted_build("submitting a Bitcoin block candidate")
        if not trusted:
            return {"ok": False, "error": security_error}
        if not bool(authorized):
            return {
                "ok": False,
                "error": "Confirm the submission authorization checkbox before calling submitblock.",
            }
        return self._launch_submission_job(
            "Controlled submitblock",
            "Submitting Candidate",
            "Re-checking the chain tip and submitting the preserved target-valid candidate in the background.",
            lambda: self._submit_solo_candidate_sync(True),
        )

    def _test_block_assembly_sync(self, payload):
        """Build a complete current-template block with nonce 0 for local structure testing only."""
        try:
            address, tag, extranonce_size = self._coinbase_payload_values(payload or {})
            with self.lock:
                template = dict(self.template_state)
                core = dict(self.core_state)
            if not core.get("connected"):
                return {"ok": False, "error": "Bitcoin Core must be connected before testing block assembly."}
            if core.get("initialblockdownload"):
                return {"ok": False, "error": "Bitcoin Core must be fully synced before testing block assembly."}
            if not template.get("available"):
                return {"ok": False, "error": "Refresh the Block Template Engine first."}
            if not address:
                return {"ok": False, "error": "Enter a public Bitcoin payout address first."}

            work = prepare_solo_work(
                template,
                address,
                network=self.cfg.get("core_network", "main"),
                tag=tag,
                extranonce_size=extranonce_size,
                extranonce_value=0,
            )
            header = work["header_prefix"] + (0).to_bytes(4, "little")
            block_hash, block_hash_int = hash_header(header)
            bundle = {
                "template": template,
                "work": work,
                "candidate": {
                    "hash": block_hash,
                    "hash_int": block_hash_int,
                    "nonce": 0,
                    "header_hex": header.hex(),
                },
            }
            assembly = assemble_candidate_block(bundle, require_target=False)
            ui = assembly_for_ui(
                assembly,
                status="Assembly Test Passed",
                detail=(
                    "Full raw block serialization passed locally. "
                    "This is a structure test only and cannot unlock proposal/submission controls."
                ),
                candidate_available=False,
            )
            return {"ok": True, "assembly": ui, "result": assembly_report(assembly, target_required=False)}
        except Exception as exc:
            self._log(f"Block assembly test failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def _assemble_solo_candidate_sync(self):
        try:
            with self.lock:
                bundle = self._preserved_candidate_bundle
                source = self._preserved_candidate_source
            if not bundle:
                bundle = self.solo_miner.candidate_bundle()
                source = source or "CPU Solo Mining Engine"
            if not bundle:
                return {"ok": False, "error": "No target-valid CPU/ASIC mining candidate has been found yet."}
            assembly = assemble_candidate_block(bundle, require_target=True)
            assembly["candidate_source"] = source or "Mining Engine"
            state = assembly_for_ui(
                assembly,
                status="Candidate Ready",
                detail=f"Target-valid candidate from {source or 'mining engine'} assembled. Run Bitcoin Core proposal validation before submission.",
                candidate_available=True,
            )
            state["candidate_source"] = source or "Mining Engine"
            if bool(self.cfg.get("candidate_auto_archive", True)):
                archive_dir = Path.home() / ".bitcoin-miner-studio" / "candidates"
                json_path, block_path = archive_candidate(assembly, archive_dir)
                state["archive_json"] = json_path
                state["archive_block"] = block_path
            with self.lock:
                self._assembled_candidate = assembly
                self.block_submission_state = state
            self._log(f"Candidate block assembled at height {assembly.get('height', 0):,}.")
            return {"ok": True, "submission": state, "result": assembly_report(assembly)}
        except Exception as exc:
            self._log(f"Candidate block assembly failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def _validate_solo_candidate_sync(self):
        try:
            with self.lock:
                assembly = dict(self._assembled_candidate or {})
            if not assembly:
                result = self._assemble_solo_candidate_sync()
                if not result.get("ok"):
                    return result
                with self.lock:
                    assembly = dict(self._assembled_candidate or {})
            if not assembly.get("target_valid"):
                return {"ok": False, "error": "Submission guard blocked a candidate that does not meet the template target."}

            rpc_url, username, password = self._submission_credentials()
            best_hash, tip_latency = get_best_block_hash(rpc_url, username, password, timeout=7.0)
            previous = str(assembly.get("previousblockhash") or "").lower()
            if best_hash != previous:
                state = assembly_for_ui(
                    assembly,
                    status="Stale Candidate",
                    detail="Bitcoin Core's chain tip changed. This candidate cannot be submitted.",
                )
                state["stale"] = True
                state["proposal_result"] = f"Current tip: {best_hash}"
                state["rpc_latency_ms"] = tip_latency
                with self.lock:
                    self.block_submission_state = state
                self._log("Candidate validation stopped: previous block is no longer the current chain tip.")
                return {
                    "ok": False,
                    "error": "Candidate is stale because Bitcoin Core has a newer chain tip.",
                    "submission": state,
                }

            proposal = validate_block_proposal(
                rpc_url, username, password, assembly.get("raw_block"), timeout=20.0
            )
            state = assembly_for_ui(
                assembly,
                status="Proposal Valid" if proposal.get("valid") else "Proposal Rejected",
                detail=(
                    "Bitcoin Core proposal validation accepted the complete candidate block."
                    if proposal.get("valid")
                    else f"Bitcoin Core rejected the proposal: {proposal.get('reason') or 'unknown reason'}"
                ),
            )
            state["proposal_checked"] = True
            state["proposal_valid"] = bool(proposal.get("valid"))
            state["proposal_result"] = proposal.get("reason") or "valid"
            state["rpc_latency_ms"] = float(proposal.get("latency_ms") or 0.0) + tip_latency
            with self.lock:
                self.block_submission_state = state
            if proposal.get("valid"):
                self._log(f"Bitcoin Core proposal validation accepted candidate {assembly.get('block_hash')}.")
                return {
                    "ok": True,
                    "submission": state,
                    "result": (
                        "BITCOIN CORE PROPOSAL VALID\n\n"
                        "The complete target-valid block passed proposal validation. "
                        "It is eligible for controlled submitblock."
                    ),
                }
            self._log(f"Bitcoin Core proposal rejected candidate: {proposal.get('reason')}")
            return {
                "ok": False,
                "error": f"Bitcoin Core proposal rejected the block: {proposal.get('reason')}",
                "submission": state,
            }
        except Exception as exc:
            self._log(f"Candidate proposal validation failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def _submit_solo_candidate_sync(self, authorized=False):
        """Controlled submitblock. The UI cannot provide arbitrary raw block hex."""
        if not bool(authorized):
            return {
                "ok": False,
                "error": "Confirm the submission authorization checkbox before calling submitblock.",
            }
        try:
            with self.lock:
                assembly = dict(self._assembled_candidate or {})
                current_state = dict(self.block_submission_state)
            if not assembly:
                return {"ok": False, "error": "No assembled target-valid candidate is available."}
            if not assembly.get("target_valid"):
                return {"ok": False, "error": "Submission guard blocked a non-target-valid candidate."}

            if bool(self.cfg.get("block_submit_require_proposal", True)) and not current_state.get("proposal_valid"):
                validation = self._validate_solo_candidate_sync()
                if not validation.get("ok"):
                    return validation
                with self.lock:
                    current_state = dict(self.block_submission_state)

            rpc_url, username, password = self._submission_credentials()

            # Re-check the chain tip immediately before submitblock.
            best_hash, tip_latency = get_best_block_hash(rpc_url, username, password, timeout=7.0)
            if best_hash != str(assembly.get("previousblockhash") or "").lower():
                state = assembly_for_ui(
                    assembly,
                    status="Stale Candidate",
                    detail="Chain tip changed after validation; submitblock was not called.",
                )
                state["stale"] = True
                state["proposal_checked"] = bool(current_state.get("proposal_checked"))
                state["proposal_valid"] = bool(current_state.get("proposal_valid"))
                state["proposal_result"] = current_state.get("proposal_result", "")
                state["rpc_latency_ms"] = tip_latency
                with self.lock:
                    self.block_submission_state = state
                self._log("submitblock guard stopped a stale candidate before submission.")
                return {
                    "ok": False,
                    "error": "Candidate became stale before submission. submitblock was not called.",
                    "submission": state,
                }

            submitted = submit_block(
                rpc_url, username, password, assembly.get("raw_block"), timeout=25.0
            )
            accepted = bool(submitted.get("accepted"))
            state = assembly_for_ui(
                assembly,
                status="Submitted / Accepted" if accepted else "Submitted / Rejected",
                detail=(
                    "Bitcoin Core accepted the submitted block."
                    if accepted
                    else f"Bitcoin Core rejected submitblock: {submitted.get('reason') or 'unknown reason'}"
                ),
            )
            state["proposal_checked"] = bool(current_state.get("proposal_checked"))
            state["proposal_valid"] = bool(current_state.get("proposal_valid"))
            state["proposal_result"] = current_state.get("proposal_result", "")
            state["submitted"] = True
            state["accepted"] = accepted
            state["submit_result"] = submitted.get("reason") or "accepted"
            state["rpc_latency_ms"] = float(submitted.get("latency_ms") or 0.0) + tip_latency
            state["archive_json"] = current_state.get("archive_json", "")
            state["archive_block"] = current_state.get("archive_block", "")
            with self.lock:
                self.block_submission_state = state

            if accepted:
                self._log(f"BLOCK ACCEPTED by Bitcoin Core: {assembly.get('block_hash')}")
                threading.Thread(
                    target=lambda: self._refresh_core_snapshot(log_transition=True, timeout=6.0),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=lambda: self._refresh_block_template(log_transition=True, timeout=8.0),
                    daemon=True,
                ).start()
                return {
                    "ok": True,
                    "submission": state,
                    "result": (
                        f"BLOCK ACCEPTED\n\nHash: {assembly.get('block_hash')}\n"
                        f"Height: {assembly.get('height', 0):,}\n\n"
                        "Bitcoin Core returned null from submitblock, indicating acceptance."
                    ),
                }

            self._log(f"submitblock rejected candidate: {submitted.get('reason')}")
            return {
                "ok": False,
                "error": f"submitblock rejected the candidate: {submitted.get('reason')}",
                "submission": state,
            }
        except Exception as exc:
            self._log(f"submitblock failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def _sync_regtest_executable(self):
        self.regtest_lab.configured_executable = str(self.cfg.get("core_executable", "") or "")

    def start_regtest_lab(self):
        self._sync_regtest_executable()
        return self.regtest_controller.launch(
            "Start Regtest Lab",
            "Starting",
            "Launching an isolated local Bitcoin Core regtest node and wallet.",
            self.regtest_lab.start_node,
        )

    def refresh_regtest_lab(self):
        current = self.regtest_controller.state()
        if not current.get("ready") and not self.regtest_lab.cookie_path.exists():
            return {
                "ok": False,
                "error": "Regtest Lab is stopped. Click Start Lab first.",
                "regtest": current,
            }
        return self.regtest_controller.launch(
            "Refresh Regtest Lab",
            "Refreshing",
            "Refreshing isolated regtest chain, wallet, and balance state.",
            self.regtest_lab.refresh,
        )

    def mine_regtest_blocks(self, count=1):
        try:
            count = max(1, min(500, int(count)))
        except (TypeError, ValueError):
            count = 1
        self._sync_regtest_executable()
        return self.regtest_controller.launch(
            f"Mine {count} Regtest Block{'s' if count != 1 else ''}",
            "Mining",
            (
                f"Running getblocktemplate → SHA-256d → block assembly → proposal → "
                f"submitblock for {count:,} isolated regtest block(s)."
            ),
            lambda: self.regtest_lab.mine_blocks(count),
        )

    def stop_regtest_lab(self):
        return self.regtest_controller.launch(
            "Stop Regtest Lab",
            "Stopping",
            "Stopping only the isolated regtest Bitcoin Core instance.",
            self.regtest_lab.stop_node,
        )

    def reset_regtest_lab(self, authorized=False):
        if not bool(authorized):
            return {
                "ok": False,
                "error": (
                    "Confirm the Regtest reset checkbox first. "
                    "Reset deletes only the isolated Regtest Lab data directory."
                ),
            }
        return self.regtest_controller.launch(
            "Reset Regtest Chain",
            "Resetting",
            "Stopping the isolated lab and deleting only its dedicated regtest data directory.",
            self.regtest_lab.reset_chain,
        )

    def start_asic_solo_bridge(self, payload=None, authorized=False):
        trusted, security_error = self._require_trusted_build("starting the ASIC Solo Bridge")
        if not trusted:
            return {"ok": False, "error": security_error}
        if not bool(authorized):
            return {"ok": False, "error": "Confirm that you own or administer the ASIC devices first."}
        try:
            payload = dict(payload or {})
            with self.lock:
                core = dict(self.core_state)
                template = dict(self.template_state)

            if not core.get("connected"):
                return {"ok": False, "error": "Bitcoin Core must be connected before starting the ASIC Solo Bridge."}
            if core.get("initialblockdownload"):
                return {"ok": False, "error": "Bitcoin Core must be fully synced before ASIC solo mining."}
            if not template.get("available"):
                return {"ok": False, "error": "A ready Block Template Engine snapshot is required."}

            address = str(self.cfg.get("coinbase_payout_address") or "").strip()
            network = str(self.cfg.get("core_network") or "main")
            if not address:
                return {"ok": False, "error": "Configure and save a public Bitcoin payout address first."}
            decode_payout_address(address, network)

            bind_ip = validate_bridge_bind_ip(
                payload.get("bind_ip")
                or self.cfg.get("asic_solo_bind_ip")
                or detect_private_lan_ip()
            )
            port = int(payload.get("port") or self.cfg.get("asic_solo_port", 3333))
            difficulty = float(
                payload.get("share_difficulty")
                or self.cfg.get("asic_solo_share_difficulty", ASIC_SOLO_DEFAULT_DIFFICULTY)
            )
            tag = str(
                self.cfg.get("coinbase_tag")
                or DEFAULT_COINBASE_TAG
            )

            self.cfg["asic_solo_bind_ip"] = bind_ip
            self.cfg["asic_solo_port"] = port
            self.cfg["asic_solo_share_difficulty"] = difficulty
            save_config(self.cfg)

            with self.lock:
                self._preserved_candidate_bundle = None
                self._preserved_candidate_source = ""
                self._assembled_candidate = None
                self.block_submission_state = unavailable_submission_state(
                    "ASIC Solo Bridge started; waiting for a Bitcoin-network-target-valid ASIC candidate."
                )

            self._asic_solo_template_failure_count = 0
            state = self.asic_solo_bridge.start(
                template,
                address,
                network=network,
                tag=tag,
                bind_ip=bind_ip,
                port=port,
                share_difficulty=difficulty,
            )
            return {
                "ok": True,
                "asic_solo_bridge": state,
                "result": (
                    "ASIC SOLO BRIDGE READY\n\n"
                    f"Endpoint: {state.get('endpoint')}\n"
                    f"Network: {network}\n"
                    f"Template height: {int(state.get('template_height') or 0):,}\n"
                    f"Share difficulty: {difficulty:g}\n"
                    f"Payout address: {address}\n\n"
                    "Configure each authorized ASIC to this local Stratum endpoint. "
                    "Any Bitcoin-target-valid result is preserved for guarded proposal/submission; blocks are never auto-submitted."
                ),
            }
        except Exception as exc:
            self._log(f"ASIC Solo Bridge start failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def stop_asic_solo_bridge(self):
        try:
            state = self.asic_solo_bridge.stop("ASIC Solo Bridge stopped by user.")
            return {
                "ok": True,
                "asic_solo_bridge": state,
                "result": "ASIC Solo Bridge stopped.",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def assign_asic_to_solo(self, ip, authorized=False):
        trusted, security_error = self._require_trusted_build("changing an ASIC pool configuration")
        if not trusted:
            return {"ok": False, "error": security_error}
        if not bool(authorized):
            return {"ok": False, "error": "Confirm that you own or administer this ASIC first."}
        try:
            ip = ensure_private_host(str(ip).strip())
            bridge = self.asic_solo_bridge.stats()
            if not bridge.get("running") or not bridge.get("endpoint"):
                return {"ok": False, "error": "Start the ASIC Solo Bridge before assigning a miner."}

            d = self.asic_devices.get(ip, {})
            if not d.get("api_verified"):
                return {
                    "ok": False,
                    "error": (
                        "Automatic pool configuration requires a verified cgminer-compatible API. "
                        "Use the ASIC Web UI and enter the displayed Solo Bridge endpoint manually."
                    ),
                }

            worker = f"BMS-{ip.replace('.', '-')}"
            result = assign_pool(
                ip, bridge["endpoint"], worker, password="x"
            )
            self._log(
                f"ASIC {ip} assigned to local Solo Bridge pool index {result.get('pool_index')}."
            )

            try:
                refreshed = query_device(ip)
                with self.lock:
                    self.asic_devices[ip] = refreshed
                    self.fleet_monitor.record(refreshed)
            except Exception:
                pass

            return {
                "ok": True,
                "result": (
                    f"ASIC {ip} assigned to {bridge['endpoint']}.\n"
                    f"Worker: {worker}\n"
                    f"Pool index: {result.get('pool_index')}\n"
                    + (
                        "A new pool entry was added without deleting existing pools."
                        if result.get("added")
                        else "Existing matching pool entry was reused."
                    )
                ),
            }
        except Exception as exc:
            self._log(f"ASIC solo assignment failed for {ip}: {exc}")
            return {"ok": False, "error": str(exc)}

    def restore_asic_pool_zero(self, ip, authorized=False):
        trusted, security_error = self._require_trusted_build("changing an ASIC pool configuration")
        if not trusted:
            return {"ok": False, "error": security_error}
        if not bool(authorized):
            return {"ok": False, "error": "Confirm that you own or administer this ASIC first."}
        try:
            ip = ensure_private_host(str(ip).strip())
            switch_pool(ip, 0)
            self._log(f"ASIC {ip} switched back to pool index 0.")
            try:
                refreshed = query_device(ip)
                with self.lock:
                    self.asic_devices[ip] = refreshed
                    self.fleet_monitor.record(refreshed)
            except Exception:
                pass
            return {
                "ok": True,
                "result": f"ASIC {ip} switched to its existing pool index 0.",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def discover_asics(self, cidr, authorized=False):
        if not authorized:
            return {"ok": False, "error": "Confirm that you own or administer the devices first."}
        try:
            cidr = str(cidr or default_private_cidr()).strip()
            self.cfg["asic_subnet"] = cidr
            save_config(self.cfg)

            probes = discover_devices(cidr)
            confirmed = []
            ignored = []

            for probe in probes:
                ip = probe["ip"]
                try:
                    device = query_device(ip)
                except Exception:
                    device = classify_probe(probe)

                if is_confirmed_asic(device):
                    confirmed.append(device)
                    with self.lock:
                        self.asic_devices[ip] = device
                        self.asic_known_devices.add(ip)
                        self.fleet_monitor.record(device)
                else:
                    ignored.append(ip)
                    # v0.5.0 could auto-save generic routers/PCs as miners.
                    # Remove such false positives when a fresh discovery sees
                    # them again, unless the user explicitly added the IP.
                    if ip not in self.asic_manual_devices:
                        with self.lock:
                            self.asic_devices.pop(ip, None)
                            self.asic_known_devices.discard(ip)

            self.cfg["asic_known_devices"] = sorted(self.asic_known_devices)
            self.cfg["asic_manual_devices"] = sorted(self.asic_manual_devices)
            save_config(self.cfg)

            self._log(
                f"ASIC discovery completed: {len(confirmed)} confirmed ASIC(s); "
                f"{len(ignored)} non-ASIC/candidate host(s) ignored."
            )
            return {
                "ok": True,
                "count": len(confirmed),
                "ignored": len(ignored),
                "result": (
                    f"ASIC discovery complete.\n\n"
                    f"Confirmed ASICs: {len(confirmed)}\n"
                    f"Ignored non-ASIC/candidate hosts: {len(ignored)}\n\n"
                    "Only devices with positive cgminer or recognized ASIC Web-UI evidence "
                    "are automatically added to the miner fleet."
                ),
            }
        except Exception as exc:
            self._log(f"ASIC discovery error: {exc}")
            return {"ok": False, "error": str(exc)}

    def _load_known_devices(self):
        changed = False
        for ip in list(self.asic_known_devices):
            try:
                d = query_device(ip)
                if (
                    not is_confirmed_asic(d)
                    and d.get("web_available")
                    and ip not in self.asic_manual_devices
                ):
                    # Positive evidence that this is a reachable generic Web
                    # device, not an ASIC. Clean up v0.5.0 false positives.
                    with self.lock:
                        self.asic_devices.pop(ip, None)
                        self.asic_known_devices.discard(ip)
                    changed = True
                    self._log(f"Removed non-ASIC LAN device from miner fleet: {ip}.")
                    continue
            except Exception:
                # Preserve unreachable known entries; a real ASIC can simply be
                # powered off during application startup.
                d = {
                    "ip": ip,
                    "model": "Known device",
                    "verification": "UNVERIFIED",
                    "status": "Offline",
                    "api_verified": False,
                    "recognized_web_asic": False,
                    "hashrate_hs": 0,
                    "can_open_web": False,
                    "can_restart": False,
                    "can_switch_pool": False,
                    "pools": [],
                }
            with self.lock:
                self.asic_devices[ip] = d
                self.fleet_monitor.record(d)

        if changed:
            self.cfg["asic_known_devices"] = sorted(self.asic_known_devices)
            save_config(self.cfg)

    def refresh_asics(self):
        try:
            changed = False
            for ip in list(self.asic_devices):
                try:
                    d = query_device(ip)
                    if (
                        not is_confirmed_asic(d)
                        and d.get("web_available")
                        and ip not in self.asic_manual_devices
                    ):
                        with self.lock:
                            self.asic_devices.pop(ip, None)
                            self.asic_known_devices.discard(ip)
                        changed = True
                        self._log(f"Ignored non-ASIC LAN device during refresh: {ip}.")
                        continue
                except Exception:
                    d = dict(self.asic_devices[ip])
                    d["status"] = "Offline"
                    d["latency_ms"] = None
                with self.lock:
                    self.asic_devices[ip] = d
                    self.fleet_monitor.record(d)

            if changed:
                self.cfg["asic_known_devices"] = sorted(self.asic_known_devices)
                save_config(self.cfg)

            self._log("ASIC fleet refreshed.")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def add_asic(self, ip):
        try:
            ip = ensure_private_host(str(ip).strip())
            try:
                d = query_device(ip)
            except Exception:
                d = {"ip": ip, "model": "Known device", "verification": "UNVERIFIED", "status": "Offline", "hashrate_hs": 0, "can_open_web": False, "can_restart": False, "can_switch_pool": False, "pools": []}
            with self.lock:
                self.asic_devices[ip] = d
                self.asic_known_devices.add(ip)
                self.asic_manual_devices.add(ip)
                self.fleet_monitor.record(d)
            self.cfg["asic_known_devices"] = sorted(self.asic_known_devices)
            self.cfg["asic_manual_devices"] = sorted(self.asic_manual_devices)
            save_config(self.cfg)
            return {
                "ok": True,
                "result": (
                    f"{ip} was added manually for troubleshooting. "
                    "Manual entries may remain visible even when ASIC verification fails."
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def remove_asic(self, ip):
        ip = str(ip)
        with self.lock:
            self.asic_devices.pop(ip, None)
            self.asic_known_devices.discard(ip)
            self.asic_manual_devices.discard(ip)
            self.asic_aliases.pop(ip, None)
            self.asic_groups.pop(ip, None)
            self.asic_notes.pop(ip, None)
        self.cfg["asic_known_devices"] = sorted(self.asic_known_devices)
        self.cfg["asic_manual_devices"] = sorted(self.asic_manual_devices)
        self.cfg["asic_aliases"] = self.asic_aliases
        self.cfg["asic_groups"] = self.asic_groups
        self.cfg["asic_notes"] = self.asic_notes
        save_config(self.cfg)
        self._log(f"ASIC {ip} removed from local fleet list.")
        return {"ok": True}

    def open_paypal_donation(self):
        """Open the Purple Dragon Foundation ltd fixed PayPal.me support page externally.

        The WebView supplies no URL argument. Keeping the destination fixed in
        signed backend code prevents this bridge action from becoming an
        arbitrary external URL launcher.
        """
        try:
            opened = bool(webbrowser.open(PAYPAL_DONATION_URL, new=2))
            self._log(f"Opened {PAYPAL_SUPPORT_LABEL} PayPal support page in the default browser.")
            return {
                "ok": True,
                "opened": opened,
                "url": PAYPAL_DONATION_URL,
                "result": f"{PAYPAL_SUPPORT_LABEL} PayPal support page opened in your default browser.",
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Could not open the PayPal donation page: {exc}",
            }

    def open_asic_web(self, ip):
        d = self.asic_devices.get(str(ip), {})
        if not d.get("can_open_web"):
            return {"ok": False, "error": "No verified HTTP/HTTPS interface for this device."}
        scheme = d.get("web_scheme") or ("https" if d.get("https_available") else "http")
        webbrowser.open(f"{scheme}://{ip}/")
        return {"ok": True}

    def restart_asic(self, ip):
        trusted, security_error = self._require_trusted_build("restarting an ASIC")
        if not trusted:
            return {"ok": False, "error": security_error}
        d = self.asic_devices.get(str(ip), {})
        if not d.get("can_restart"):
            return {"ok": False, "error": "Compatible restart capability is not verified."}
        try:
            restart_miner(ip)
            self._log(f"Restart requested for ASIC {ip}.")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def switch_asic_pool(self, ip, pool_index=0):
        trusted, security_error = self._require_trusted_build("switching an ASIC pool")
        if not trusted:
            return {"ok": False, "error": security_error}
        d = self.asic_devices.get(str(ip), {})
        if not d.get("can_switch_pool"):
            return {"ok": False, "error": "Pool switching capability is not verified."}
        try:
            switch_pool(ip, int(pool_index))
            self._log(f"ASIC {ip} switched to pool index {pool_index}.")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def close(self):
        try:
            if self.tray_manager is not None:
                self.tray_manager.stop()
        except Exception:
            pass
        try:
            self._core_monitor_stop.set()
        except Exception:
            pass
        try:
            self._template_monitor_stop.set()
        except Exception:
            pass
        try:
            self.regtest_lab.stop_node(timeout=3.0)
        except Exception:
            pass
        try:
            self.asic_solo_bridge.stop("Application closing.")
        except Exception:
            pass
        try:
            self.solo_miner.stop("Application closing.")
        except Exception:
            pass
        try:
            self.miner.stop()
        except Exception:
            pass
        try:
            self.benchmark.stop()
        except Exception:
            pass
        try:
            self.analytics.stop()
        except Exception:
            pass
        try:
            if self.cfg.get("pool_url_ephemeral_local_test"):
                self._restore_pool_after_local_test()
        except Exception:
            pass
        try:
            self.local_pool.stop()
        except Exception:
            pass
        try:
            self.release_candidate.mark_clean_shutdown()
        except Exception:
            pass
        try:
            for service_id in (
                "core-monitor", "template-monitor", "analytics", "miner", "benchmark",
                "pool-diagnostics", "local-test-pool", "asic-fleet", "regtest", "tray",
            ):
                self.services.mark(service_id, "stopped", "Application shutdown.")
            self.services.mark("backend", "stopped", "Application shutdown complete.")
            self.events.publish("runtime", "shutdown", "Bitcoin Miner Studio shutdown complete.")
        except Exception:
            pass
        return True


def _bridge_method_names(backend):
    """Return the explicit v2 pywebview contract, never arbitrary public helpers."""
    return [
        name
        for name in EXPOSED_API_METHODS
        if callable(getattr(backend, name, None))
    ]


def _make_bridge_function(backend, method_name):
    """Create a flat *args wrapper so pywebview never introspects backend internals."""
    def bridge_function(*args):
        method = getattr(backend, method_name)
        return method(*args)

    bridge_function.__name__ = method_name
    bridge_function.__qualname__ = method_name
    bridge_function.__doc__ = f"Bitcoin Miner Studio WebView bridge wrapper for {method_name}."
    return bridge_function


def build_bridge_functions(backend):
    """Build flat public wrappers only after validating the explicit v2 contract."""
    contract = contract_snapshot(backend)
    if contract.get("missing"):
        missing = ", ".join(contract["missing"])
        raise RuntimeError(f"WebView API contract is incomplete: {missing}")
    return [
        _make_bridge_function(backend, name)
        for name in _bridge_method_names(backend)
    ]


def _write_bridge_diagnostic(root, text):
    try:
        (Path(root) / "startup-bridge.log").write_text(str(text), encoding="utf-8")
    except Exception:
        pass


def run():
    import webview

    root = Path(__file__).resolve().parent
    backend = WebBackend()
    ui_path = root / "ui" / "index.html"
    icon_path = root / APP_ICON_RELATIVE
    window_title = f"{APP_NAME} v{VERSION}"

    try:
        # v0.4.6.3: expose flat function wrappers instead of the entire complex
        # backend object. Nested Regtest/controller objects never enter pywebview
        # API introspection.
        window = webview.create_window(
            window_title,
            str(ui_path),
            width=1580,
            height=960,
            min_size=(1180, 760),
            background_color="#07060B",
        )
        backend.window = window
        _schedule_windows_native_icon(window_title, icon_path)

        bridge_functions = build_bridge_functions(backend)
        window.expose(*bridge_functions)

        pywebview_version = getattr(webview, "__version__", "installed")
        _write_bridge_diagnostic(
            root,
            (
                f"Bitcoin Miner Studio v{VERSION}\n"
                f"Python: {sys.executable}\n"
                f"Python version: {sys.version.replace(chr(10), ' ')}\n"
                f"pywebview: {pywebview_version}\n"
                f"UI path: {ui_path}\n"
                f"App icon: {icon_path}\n"
                f"Bridge mode: explicit v2 window.expose contract\n"
                f"Bridge API schema: {BRIDGE_API_SCHEMA}\n"
                f"Exposed functions: {len(bridge_functions)}\n"
                f"get_bootstrap exposed: {any(f.__name__ == 'get_bootstrap' for f in bridge_functions)}\n"
                f"get_state exposed: {any(f.__name__ == 'get_state' for f in bridge_functions)}\n"
                f"start_regtest_lab exposed: {any(f.__name__ == 'start_regtest_lab' for f in bridge_functions)}\n"
            ),
        )

        tray_settings = normalize_tray_settings(backend.cfg)

        def tray_show_window():
            try:
                window.show()
                try:
                    window.restore()
                except Exception:
                    pass
            except Exception:
                pass

        def tray_hide_window():
            try:
                window.hide()
            except Exception:
                pass

        tray_manager = WindowsTrayManager(
            icon_path,
            status_provider=backend._tray_status_snapshot,
            show_callback=tray_show_window,
            hide_callback=tray_hide_window,
            exit_callback=lambda: window.destroy(),
            settings=tray_settings,
        )
        backend._attach_tray_manager(tray_manager)

        def on_shown():
            if tray_manager.settings.get("tray_enabled"):
                tray_manager.start()

        def on_minimized():
            if tray_manager.should_minimize_to_tray():
                tray_manager.hide_window()

        def on_closing():
            if tray_manager.should_close_to_tray():
                tray_manager.hide_window()
                return False
            return True

        def on_closed():
            backend.close()

        window.events.shown += on_shown
        window.events.minimized += on_minimized
        window.events.closing += on_closing
        window.events.closed += on_closed
        webview.start(debug=False)
    except Exception:
        _write_bridge_diagnostic(
            root,
            "BRIDGE STARTUP FAILURE\n\n" + traceback.format_exc(),
        )
        raise
