import json
from pathlib import Path

from ui_theme import DEFAULT_UI_THEME, normalize_ui_theme
from branding import DEFAULT_COINBASE_TAG

CONFIG_DIR = Path.home() / ".bitcoin-miner-studio"
CONFIG_FILE = CONFIG_DIR / "settings.json"

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


def load_config():
    cfg = dict(DEFAULTS)
    loaded = {}
    try:
        if CONFIG_FILE.exists():
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            loaded.pop("pool_password", None)
            loaded.pop("rpc_password", None)
            cfg.update(loaded)
    except Exception:
        pass
    if "pool_failover_policy" not in loaded:
        cfg["pool_failover_policy"] = "balanced" if bool(cfg.get("pool_failover_enabled", True)) else "manual"
    if str(cfg.get("pool_failover_policy") or "balanced").lower() not in {"manual", "conservative", "balanced", "aggressive"}:
        cfg["pool_failover_policy"] = "balanced"
    try:
        cfg["pool_primary_recovery_seconds"] = max(0, min(86400, int(cfg.get("pool_primary_recovery_seconds", 300))))
    except (TypeError, ValueError):
        cfg["pool_primary_recovery_seconds"] = 300

    # Branding migration applies only to exact former built-in defaults.
    # Any custom user-authored coinbase message remains unchanged.
    if str(cfg.get("coinbase_tag") or "").strip() in {
        "Bitcoin Miner Studio / Purple Dragon",
        "Bitcoin Miner Studio / Purple Dragon Foundation",
    }:
        cfg["coinbase_tag"] = DEFAULT_COINBASE_TAG


    try:
        cfg["benchmark_processes"] = max(1, min(64, int(cfg.get("benchmark_processes", 2))))
    except (TypeError, ValueError):
        cfg["benchmark_processes"] = 2
    try:
        cfg["benchmark_duration_seconds"] = max(3, min(3600, int(cfg.get("benchmark_duration_seconds", 30))))
    except (TypeError, ValueError):
        cfg["benchmark_duration_seconds"] = 30
    try:
        cfg["benchmark_scaling_seconds"] = max(3, min(120, int(cfg.get("benchmark_scaling_seconds", 8))))
    except (TypeError, ValueError):
        cfg["benchmark_scaling_seconds"] = 8

    cfg["ui_theme"] = normalize_ui_theme(cfg.get("ui_theme"))
    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    safe = dict(cfg)
    safe.pop("pool_password", None)
    safe.pop("rpc_password", None)
    CONFIG_FILE.write_text(json.dumps(safe, indent=2), encoding="utf-8")
