import copy
from pathlib import Path

from ui_theme import DEFAULT_UI_THEME, normalize_ui_theme
from branding import DEFAULT_COINBASE_TAG
from reliability_io import atomic_json_write, read_json, preserve_corrupt_file

CONFIG_DIR = Path.home() / ".bitcoin-miner-studio"
CONFIG_FILE = CONFIG_DIR / "settings.json"
RECOVERY_STATUS = {"recovered": False, "reason": "", "preserved": False, "write_blocked": False, "fields": []}


def recovery_status():
    """Session-sticky, support-safe recovery evidence; never includes values."""
    return copy.deepcopy(RECOVERY_STATUS)


def _preserve_settings(reason, fields=()):
    RECOVERY_STATUS.update(recovered=True, reason=reason, fields=sorted(set(fields)))
    preserved = preserve_corrupt_file(CONFIG_FILE)
    RECOVERY_STATUS.update(preserved=preserved, write_blocked=not preserved)


def _read_settings(path):
    loaded = read_json(path)
    if not isinstance(loaded, dict):
        raise ValueError("Settings must be a JSON object")
    return loaded

DEFAULTS = {
    "benchmark_processes": 2,
    "benchmark_duration_seconds": 30,
    "benchmark_scaling_seconds": 8,
    "mining_processes": 2,
    "pool_url": "stratum+tcp://example.com:3333",
    "pool_backup_urls": [],
    "pool_failover_enabled": True,
    "pool_failover_policy": "balanced",
    "pool_primary_recovery_seconds": 300,
    "active_pool_profile_id": "",
    "pool_job_timeout_seconds": 120,
    "pool_url_ephemeral_local_test": False,
    "pool_restore_after_local_test": {},
    "pool_worker": "wallet.worker1",
    "rpc_url": "http://127.0.0.1:8332",
    "rpc_user": "bitcoinrpc",
    "core_auth_mode": "password",
    "core_data_dir": "",
    "core_executable": "",
    "core_cookie_path": "",
    "core_network": "main",
    "core_auto_refresh": True,
    "core_refresh_seconds": 10,
    "template_auto_refresh": True,
    "template_refresh_seconds": 15,
    "coinbase_payout_address": "",
    "coinbase_tag": DEFAULT_COINBASE_TAG,
    "coinbase_extranonce_size": 8,
    "solo_batch_size": 20000,
    "solo_extranonce_roll_hashes": 2000000,
    "solo_auto_new_template": True,
    "block_submit_require_proposal": True,
    "candidate_auto_archive": True,
    "performance_plus_enabled": False,
    "analytics_enabled": True,
    "analytics_sample_seconds": 10,
    "analytics_retention_days": 30,
    "tray_enabled": True,
    "tray_minimize_to_tray": True,
    "tray_close_to_tray": False,
    "tray_notifications_enabled": True,
    "tray_poll_seconds": 10,
    "release_channel": "Stable",
    "rc_preflight_on_start": True,
    "regtest_lab_rpc_port": 19443,
    "regtest_lab_p2p_port": 19444,
    "suggest_difficulty_enabled": False,
    "suggest_difficulty": 1.0,
    "local_test_difficulty": 0.000001,
    "asic_subnet": "",
    "asic_refresh_seconds": 10,
    "asic_manual_devices": [],
    "asic_solo_bind_ip": "",
    "asic_solo_port": 3333,
    "asic_solo_share_difficulty": 65536.0,
    "asic_aliases": {},
    "asic_groups": {},
    "asic_temp_alert_c": 80.0,
    "asic_hashrate_drop_percent": 25.0,
    "asic_notes": {},
    "asic_known_devices": [],
    "ui_scale_mode": "Large",
    "ui_theme": DEFAULT_UI_THEME,
    "mining_assistant_goal": "learn",
    "mining_assistant_intro_seen": False,
    "mining_assistant_completed": False,
    "profitability_hashrate_hs": 0.0,
    "profitability_power_watts": 0.0,
    "profitability_electricity_per_kwh": 0.15,
    "profitability_pool_fee_percent": 1.0,
    "profitability_btc_price": 0.0,
    "profitability_difficulty": 0.0,
    "profitability_height": 0,
    "profitability_block_subsidy_btc": 3.125,
    "profitability_avg_fees_btc_per_block": 0.0,
}


NUMERIC_LIMITS = {
    "benchmark_processes": (1, 64), "mining_processes": (1, 64),
    "benchmark_duration_seconds": (3, 3600), "benchmark_scaling_seconds": (3, 120),
    "pool_primary_recovery_seconds": (0, 86400), "pool_job_timeout_seconds": (20, 1800),
    "core_refresh_seconds": (5, 300), "template_refresh_seconds": (5, 300),
    "analytics_sample_seconds": (5, 300), "analytics_retention_days": (1, 365),
    "tray_poll_seconds": (5, 300), "asic_refresh_seconds": (5, 300),
    "regtest_lab_rpc_port": (1, 65535), "regtest_lab_p2p_port": (1, 65535),
    "asic_solo_port": (1, 65535), "coinbase_extranonce_size": (2, 32),
    "solo_batch_size": (1, 10000000), "solo_extranonce_roll_hashes": (1, 1000000000),
    "local_test_difficulty": (1e-12, 1e12), "suggest_difficulty": (1e-12, 1e20),
    "asic_solo_share_difficulty": (1e-12, 1e20), "asic_temp_alert_c": (1, 200),
    "asic_hashrate_drop_percent": (0, 100), "profitability_pool_fee_percent": (0, 100),
}


def _valid_setting(key, value):
    default = DEFAULTS[key]
    valid = type(value) is type(default)
    if isinstance(default, float):
        valid = type(value) in (float, int)
    if valid and key in NUMERIC_LIMITS:
        low, high = NUMERIC_LIMITS[key]
        valid = low <= value <= high
    if valid and key.startswith("profitability_") and type(value) in (float, int):
        valid = 0 <= value <= 1e100
    return valid


def load_config():
    cfg = copy.deepcopy(DEFAULTS)
    loaded = {}
    invalid_fields = []
    try:
        if CONFIG_FILE.exists():
            loaded = _read_settings(CONFIG_FILE)
            loaded.pop("pool_password", None)
            loaded.pop("rpc_password", None)
            cfg.update(loaded)
    except (OSError, ValueError, UnicodeError, RecursionError):
        # Preserve damaged input locally before any later settings save.
        # Never include its contents or exception text in support evidence.
        _preserve_settings("settings_unreadable")
        loaded = {}
    for key, default in DEFAULTS.items():
        value = loaded.get(key, default)
        if not _valid_setting(key, value):
            cfg[key] = copy.deepcopy(default)
            invalid_fields.append(key)
    restore = cfg["pool_restore_after_local_test"]
    restore_backups = restore.get("pool_backup_urls", [])
    if any(key in DEFAULTS and not _valid_setting(key, value) for key, value in restore.items()) or (
        isinstance(restore_backups, list) and any(not isinstance(item, str) for item in restore_backups)
    ):
        cfg["pool_restore_after_local_test"] = {}
        invalid_fields.append("pool_restore_after_local_test")
    for key in ("pool_backup_urls", "asic_manual_devices", "asic_known_devices"):
        if any(not isinstance(item, str) for item in cfg[key]):
            cfg[key] = []
            invalid_fields.append(key)
    if cfg["regtest_lab_rpc_port"] == cfg["regtest_lab_p2p_port"]:
        cfg["regtest_lab_rpc_port"], cfg["regtest_lab_p2p_port"] = 19443, 19444
        invalid_fields.extend(("regtest_lab_rpc_port", "regtest_lab_p2p_port"))
    if invalid_fields:
        _preserve_settings("settings_invalid_fields", invalid_fields)
    if "pool_failover_policy" not in loaded:
        cfg["pool_failover_policy"] = "balanced" if bool(cfg.get("pool_failover_enabled", True)) else "manual"
    if str(cfg.get("pool_failover_policy") or "balanced").lower() not in {"manual", "conservative", "balanced", "aggressive"}:
        cfg["pool_failover_policy"] = "balanced"

    # Branding migration applies only to exact former built-in defaults.
    # Any custom user-authored coinbase message remains unchanged.
    if str(cfg.get("coinbase_tag") or "").strip() in {
        "Bitcoin Miner Studio / Purple Dragon",
        "Bitcoin Miner Studio / Purple Dragon Foundation",
    }:
        cfg["coinbase_tag"] = DEFAULT_COINBASE_TAG

    cfg["ui_theme"] = normalize_ui_theme(cfg.get("ui_theme"))
    return cfg


def save_config(cfg):
    """Persist settings atomically so an interrupted write cannot corrupt JSON."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    safe = dict(cfg)
    safe.pop("pool_password", None)
    safe.pop("rpc_password", None)
    if RECOVERY_STATUS.get("write_blocked"):
        raise OSError("Original settings could not be preserved; refusing to overwrite them.")
    atomic_json_write(CONFIG_FILE, safe)
