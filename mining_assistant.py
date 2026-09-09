"""Bitcoin Miner Studio v1.1.0.1 — Mining Assistant polish hotfix.

Advisory only: this module never starts mining, changes pools, scans the LAN,
controls ASICs, changes Bitcoin Core, or submits blocks.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from coinbase_builder import decode_payout_address


ASSISTANT_GOALS = {
    "learn": {
        "name": "Learn & Test",
        "description": "Learn the workflow safely with a CPU benchmark, Local Test Pool and Regtest.",
    },
    "cpu": {
        "name": "Test This PC",
        "description": "Benchmark this computer's local SHA-256d CPU performance.",
    },
    "pool": {
        "name": "Pool Mining",
        "description": "Configure a real Stratum pool, test it, then start an authorized session.",
    },
    "asic": {
        "name": "Connect an ASIC",
        "description": "Discover and monitor a Bitcoin ASIC you own or administer on your private LAN.",
    },
    "core": {
        "name": "Bitcoin Core",
        "description": "Detect Bitcoin Core, verify RPC access and check synchronization.",
    },
    "solo": {
        "name": "Solo Mining",
        "description": "Prepare Bitcoin Core, payout configuration and guarded solo-mining tools.",
    },
}


def normalize_goal(value) -> str:
    key = str(value or "").strip().lower()
    return key if key in ASSISTANT_GOALS else "learn"


def _status(key, label, detail, route, action, *, ready=False, optional=False):
    return {
        "status": key,
        "label": label,
        "detail": detail,
        "route": route,
        "action": action,
        "ready": bool(ready),
        "optional": bool(optional),
    }


def _payout_valid(cfg) -> bool:
    address = str(cfg.get("coinbase_payout_address") or "").strip()
    if not address:
        return False
    try:
        decode_payout_address(address, str(cfg.get("core_network") or "main"))
        return True
    except Exception:
        return False


def _pool_is_real(cfg) -> bool:
    url = str(cfg.get("pool_url") or "").strip()
    worker = str(cfg.get("pool_worker") or "").strip()
    lower_url = url.lower()
    if not url or "example.com" in lower_url:
        return False
    if lower_url.startswith("stratum+tcp://127.0.0.1:") or lower_url.startswith("stratum+tcp://localhost:"):
        return False
    if not worker or worker in ("wallet.worker1", "local.worker1"):
        return False
    return True


def _windows_cpu_name() -> str:
    """Read Windows' human-friendly processor model without spawning a shell."""
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            value, _kind = winreg.QueryValueEx(key, "ProcessorNameString")
        return " ".join(str(value or "").split())
    except Exception:
        return ""


def _cpu_name() -> str:
    for value in (
        _windows_cpu_name(),
        platform.processor(),
        os.environ.get("PROCESSOR_IDENTIFIER", ""),
        platform.machine(),
    ):
        value = " ".join(str(value or "").split())
        if value:
            return value
    return "CPU"


def _disk_free_gb() -> float:
    try:
        return shutil.disk_usage(Path.home()).free / (1024 ** 3)
    except Exception:
        return 0.0


def _steps_for_goal(goal, readiness):
    core_ready = readiness["core"]["ready"]
    pool_ready = readiness["pool"]["ready"]
    asic_ready = readiness["asic"]["ready"]
    payout_ready = readiness["solo"]["meta"]["payout_valid"]

    paths = {
        "learn": [
            ("Run a CPU benchmark", "Measure local SHA-256d performance without connecting to a real pool.", "benchmark", "Open Benchmark Lab"),
            ("Try the Local Test Pool", "Practice Stratum locally before entering real pool credentials.", "pool", "Open Pool PowerTools"),
            ("Explore Bitcoin Core + Regtest", "Learn block templates and mining flow on an isolated local chain.", "core", "Open Bitcoin Core"),
        ],
        "cpu": [
            ("Benchmark this PC", "Use Benchmark Lab 2.0 to establish average, peak and stability-scored SHA-256d performance.", "benchmark", "Open Benchmark Lab"),
            ("Compare over time", "Monitoring keeps local historical performance data without cloud telemetry.", "monitoring", "Open Monitoring"),
        ],
        "pool": [
            (
                "Pool configuration detected" if pool_ready else "Configure your pool",
                "Enter a real Stratum endpoint and worker. Credentials remain in the secure credential backend.",
                "pool", "Open Pool PowerTools",
            ),
            ("Test endpoints", "Use Endpoint Diagnostics before starting a real mining session.", "pool", "Run Pool Diagnostics"),
            ("Review share health", "Watch accepted, rejected, stale, latency and failover metrics.", "monitoring", "Open Monitoring"),
        ],
        "asic": [
            (
                "ASIC evidence detected" if asic_ready else "Discover your ASIC",
                "Authorize private-LAN discovery only for equipment you own or administer.",
                "asic", "Open ASIC Control",
            ),
            ("Verify health", "Review hashrate, temperature, availability and positive ASIC identification.", "asic", "Open Fleet"),
            ("Choose pool or solo workflow", "Use explicit pool controls or the LAN-only ASIC Solo Bridge.", "asic", "Open ASIC Control"),
        ],
        "core": [
            (
                "Bitcoin Core is ready" if core_ready else "Detect Bitcoin Core",
                "Use Auto Detect / Auto Configure and cookie authentication where available.",
                "core", "Open Bitcoin Core",
            ),
            ("Verify synchronization", "Mainnet mining tools should use a fully synchronized node.", "core", "Check Node Health"),
            ("Try Regtest", "Practice block generation on the isolated Regtest Laboratory before mainnet solo workflows.", "core", "Open Regtest Lab"),
        ],
        "solo": [
            (
                "Bitcoin Core is synchronized" if core_ready else "Prepare Bitcoin Core",
                "Solo mining requires fresh block templates from your local node.",
                "core", "Open Bitcoin Core",
            ),
            (
                "Payout address validated" if payout_ready else "Configure a public payout address",
                "Only a public Bitcoin address is needed; Miner Studio never needs a seed phrase or private key.",
                "core", "Open Coinbase & Payout",
            ),
            ("Practice in Regtest", "Use the isolated lab to understand candidate creation before mainnet.", "core", "Open Regtest Lab"),
            ("Review solo odds", "CPU solo mining on Bitcoin mainnet is educational and extraordinarily unlikely to find a block.", "core", "Open Solo Dashboard"),
        ],
    }

    return [
        {"title": title, "detail": detail, "route": route, "action": action, "index": i + 1}
        for i, (title, detail, route, action) in enumerate(paths[goal])
    ]


def _goal_readiness(goal, readiness, overall, overall_status):
    if goal == "learn":
        return {
            "key": "learn",
            "heading": "LEARN & TEST",
            "label": overall,
            "status": overall_status,
            "detail": "Your local learning/testing environment is summarized below.",
            "route": "assistant",
            "action": "Review Readiness",
        }

    item = readiness[goal]
    return {
        "key": goal,
        "heading": ASSISTANT_GOALS[goal]["name"].upper(),
        "label": item["label"],
        "status": item["status"],
        "detail": item["detail"],
        "route": item["route"],
        "action": item["action"],
    }


def build_mining_assistant_snapshot(
    cfg,
    *,
    core_setup=None,
    core_state=None,
    asic_devices=None,
    security_state=None,
    regtest_state=None,
    benchmark_state=None,
    analytics_status=None,
    goal=None,
):
    cfg = dict(cfg or {})
    core_setup = dict(core_setup or {})
    core_state = dict(core_state or {})
    asic_devices = list(asic_devices or [])
    security_state = dict(security_state or {})
    regtest_state = dict(regtest_state or {})
    benchmark_state = dict(benchmark_state or {})
    analytics_status = dict(analytics_status or {})
    goal = normalize_goal(goal or cfg.get("mining_assistant_goal"))

    cpu_threads = max(1, int(os.cpu_count() or 1))
    free_gb = _disk_free_gb()
    python_ok = sys.version_info >= (3, 11)
    cpu_ready = python_ok and cpu_threads >= 1

    security_checked = bool(security_state.get("checked"))
    security_verified = bool(security_state.get("verified"))
    if security_verified:
        security = _status(
            "ready", "VERIFIED",
            "Purple Dragon integrity is trusted; critical controls may be used.",
            "security", "Open Security", ready=True,
        )
    elif not security_checked:
        security = _status(
            "checking", "CHECKING",
            "Purple Dragon verification is still running.",
            "security", "Open Security",
        )
    else:
        security = _status(
            "blocked", "ATTENTION",
            "Build integrity is not trusted. Critical mining controls remain locked.",
            "security", "Review Security",
        )

    cpu = _status(
        "ready" if cpu_ready else "blocked",
        "READY" if cpu_ready else "UNAVAILABLE",
        (
            f"{cpu_threads} logical CPU thread(s) available. CPU SHA-256d is useful for "
            "benchmarking, learning and local testing; Bitcoin mainnet mining is ASIC-dominated."
        ),
        "benchmark", "Open Benchmark Lab", ready=cpu_ready,
    )
    cpu["meta"] = {
        "name": _cpu_name(),
        "threads": cpu_threads,
        "architecture": platform.machine() or "unknown",
        "python": platform.python_version(),
        "python_ok": python_ok,
        "benchmark_running": bool(benchmark_state.get("running")),
        "benchmark_hashrate": float(benchmark_state.get("hashrate") or 0),
        "benchmark_peak": float(benchmark_state.get("peak_hashrate") or 0),
    }

    pool_ready = _pool_is_real(cfg)
    pool = _status(
        "ready" if pool_ready else "setup",
        "CONFIGURED" if pool_ready else "SETUP NEEDED",
        (
            "A non-placeholder Stratum endpoint and worker are configured."
            if pool_ready
            else "No real pool profile is ready yet. The built-in Local Test Pool is available for practice."
        ),
        "pool", "Open Pool PowerTools", ready=pool_ready,
    )

    core_connected = bool(core_state.get("connected"))
    core_synced = core_connected and str(core_state.get("status") or "").lower() == "synced"
    installation_found = bool(core_setup.get("installation_found"))
    if core_synced:
        core = _status(
            "ready", "SYNCED",
            f"Bitcoin Core is connected on {core_state.get('chain') or 'the configured network'} with {int(core_state.get('connections') or 0)} peer connection(s).",
            "core", "Open Bitcoin Core", ready=True,
        )
    elif core_connected:
        core = _status(
            "setup", "SYNCING",
            f"Bitcoin Core is connected and currently {float(core_state.get('sync_percent') or 0):.2f}% synchronized.",
            "core", "Check Sync",
        )
    elif installation_found:
        core = _status(
            "setup", "DETECTED",
            "Bitcoin Core was detected but RPC/node readiness has not been verified.",
            "core", "Finish Core Setup",
        )
    else:
        core = _status(
            "optional", "NOT DETECTED",
            "Bitcoin Core is optional for pool benchmarking but required for local solo/block-template workflows.",
            "core", "Set Up Bitcoin Core", optional=True,
        )

    asic_count = len(asic_devices)
    known_count = len(cfg.get("asic_known_devices") or [])
    if asic_count:
        online_count = sum(1 for d in asic_devices if str(d.get("status") or "") in ("Online", "Web UI only"))
        asic = _status(
            "ready", f"{asic_count} DETECTED",
            f"{online_count} positively identified/known ASIC device(s) are currently online or reachable.",
            "asic", "Open ASIC Control", ready=True,
        )
    elif known_count:
        asic = _status(
            "setup", "KNOWN · OFFLINE",
            f"{known_count} previously known ASIC device(s) are saved, but none are active in the fleet view.",
            "asic", "Refresh ASIC Fleet",
        )
    else:
        asic = _status(
            "optional", "NONE DETECTED",
            "No positively identified ASIC is present. Discovery is private-LAN only and requires ownership/admin authorization.",
            "asic", "Discover ASICs", optional=True,
        )
    asic["meta"] = {"detected": asic_count, "known": known_count}

    payout_valid = _payout_valid(cfg)
    if core_synced and payout_valid and security_verified:
        solo = _status(
            "ready", "PREPARED",
            "Core synchronization, payout validation and Purple Dragon trust are ready for the guarded solo workflow.",
            "core", "Open Solo Dashboard", ready=True,
        )
    else:
        needs = []
        if not core_synced:
            needs.append("synced Bitcoin Core")
        if not payout_valid:
            needs.append("valid public payout address")
        if not security_verified:
            needs.append("trusted Purple Dragon build")
        solo = _status(
            "setup", "SETUP NEEDED",
            "Solo workflow needs " + ", ".join(needs) + ".",
            "core", "Prepare Solo Mining",
        )
    solo["meta"] = {"payout_valid": payout_valid, "core_synced": core_synced}

    regtest_running = bool(regtest_state.get("running"))
    if installation_found or core_synced:
        regtest = _status(
            "ready" if regtest_running else "available",
            "RUNNING" if regtest_running else "AVAILABLE",
            "The isolated Regtest Laboratory can be used for safe local block-generation practice.",
            "core", "Open Regtest Lab", ready=True,
        )
    else:
        regtest = _status(
            "setup", "CORE NEEDED",
            "Install or locate Bitcoin Core before starting the isolated Regtest Laboratory.",
            "core", "Set Up Bitcoin Core",
        )

    monitoring_ready = bool(analytics_status.get("running") or analytics_status.get("available"))
    monitoring = _status(
        "ready" if monitoring_ready else "available",
        "READY" if monitoring_ready else "AVAILABLE",
        "Local-only historical monitoring is available; mining credentials are excluded from its schema.",
        "monitoring", "Open Monitoring", ready=True,
    )

    storage = _status(
        "ready" if free_gb >= 2 else ("setup" if free_gb >= 0.5 else "blocked"),
        "READY" if free_gb >= 2 else ("LOW" if free_gb >= 0.5 else "CRITICAL"),
        f"{free_gb:.1f} GB free on the application-data volume.",
        "release", "Open Release Readiness", ready=free_gb >= 2,
    )

    readiness = {
        "cpu": cpu,
        "pool": pool,
        "core": core,
        "asic": asic,
        "solo": solo,
        "regtest": regtest,
        "security": security,
        "monitoring": monitoring,
        "storage": storage,
    }

    essentials = [cpu, security, storage]
    essential_ready = sum(1 for item in essentials if item["ready"])
    optional_ready = sum(
        1 for key in ("pool", "core", "asic", "solo", "regtest", "monitoring")
        if readiness[key]["ready"]
    )
    score = round((essential_ready / len(essentials)) * 55 + (optional_ready / 6) * 45)

    if security["status"] == "blocked" or storage["status"] == "blocked":
        overall = "ATTENTION REQUIRED"
        overall_status = "blocked"
    elif essential_ready == len(essentials):
        overall = "MINING LAB READY"
        overall_status = "ready"
    else:
        overall = "SETUP IN PROGRESS"
        overall_status = "setup"

    steps = _steps_for_goal(goal, readiness)
    goal_readiness = _goal_readiness(goal, readiness, overall, overall_status)

    return {
        "schema": 1,
        "goal": goal,
        "goal_name": ASSISTANT_GOALS[goal]["name"],
        "goal_description": ASSISTANT_GOALS[goal]["description"],
        "goals": [{"id": key, **value} for key, value in ASSISTANT_GOALS.items()],
        "overall": overall,
        "overall_status": overall_status,
        "score": int(score),
        "goal_readiness": goal_readiness,
        "goal_heading": goal_readiness["heading"],
        "goal_status_label": goal_readiness["label"],
        "goal_status": goal_readiness["status"],
        "goal_status_detail": goal_readiness["detail"],
        "readiness": readiness,
        "steps": steps,
        "disclaimer": (
            "Mining Assistant is advisory only. It never starts mining, changes pools, "
            "scans your LAN, controls ASICs, changes Bitcoin Core, or submits blocks by itself."
        ),
        "mainnet_note": (
            "CPU SHA-256d is useful for learning and benchmarking, but modern Bitcoin mainnet "
            "mining is dominated by dedicated ASIC hardware. Profitability is not guaranteed."
        ),
    }
