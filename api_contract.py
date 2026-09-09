"""Explicit pywebview API contract for Bitcoin Miner Studio v2.

v1.x exposed every public WebBackend method discovered by reflection. v2 keeps
flat pywebview wrappers, but only methods named in this contract can cross the
Python/JavaScript boundary. Adding a public backend helper no longer exposes it
implicitly.
"""
from __future__ import annotations

API_SCHEMA = 2

API_GROUPS = {
    "runtime": (
        "get_bootstrap", "get_state", "start_background_services", "clear_logs",
        "set_performance_plus", "set_ui_theme", "get_architecture_state",
        "record_workspace_view", "set_workspace_preferences", "record_workspace_command",
    ),
    "security": (
        "get_security_state", "verify_security_now", "get_security_policy", "get_provenance",
    ),
    "diagnostics": (
        "get_diagnostics_state", "run_diagnostics", "get_diagnostics_report",
        "create_diagnostics_support_bundle", "open_diagnostics_support_folder",
    ),
    "release": (
        "get_update_release_state", "set_update_channel", "choose_update_package", "choose_update_folder",
        "inspect_update_package", "stage_update_package", "clear_staged_update", "export_release_descriptor",
        "get_update_release_report", "open_update_staging_folder", "get_release_candidate_state",
        "run_release_preflight", "get_release_candidate_report", "create_release_support_bundle",
    ),
    "monitoring": (
        "get_analytics_dashboard", "get_analytics_status", "configure_analytics",
        "clear_analytics_history", "export_analytics", "get_tray_state", "save_tray_settings",
        "hide_to_tray", "show_from_tray", "test_tray_notification",
    ),
    "assistant": (
        "get_mining_assistant_state", "run_mining_assistant_check", "save_mining_assistant_preferences",
        "get_profitability_state", "calculate_profitability", "save_profitability_preferences",
        "use_core_profitability_data", "get_hardware_compatibility_state", "create_hardware_compatibility_report",
    ),
    "pool": (
        "get_pool_profiles_state", "save_pool_profile", "delete_pool_profile", "activate_pool_profile",
        "test_pool_profile", "export_pool_profiles", "save_pool_config", "toggle_local_pool",
        "start_pool_diagnostics", "clear_pool_diagnostics", "get_pool_diagnostic_report", "test_pool",
    ),
    "mining": (
        "start_mining", "stop_mining", "reset_session", "start_benchmark", "start_benchmark_lab",
        "stop_benchmark", "get_benchmark_lab", "start_benchmark_scaling_test", "clear_benchmark_history",
        "export_benchmark_history",
    ),
    "academy": (
        "get_mining_academy_state", "set_academy_lesson_status", "submit_academy_quiz",
        "reset_academy_progress", "run_academy_hash_lab", "run_academy_difficulty_lab",
        "run_academy_header_lab", "run_academy_merkle_lab", "run_academy_nonce_lab",
    ),
    "bitcoin_core": (
        "detect_core_setup", "auto_configure_core", "locate_core_executable", "locate_core_data_dir",
        "start_bitcoin_core", "open_core_data_dir", "download_bitcoin_core", "core_setup_recommendation",
        "save_core_config", "refresh_core", "test_core", "refresh_block_template", "test_block_template",
        "save_coinbase_config", "validate_payout_address", "build_coinbase_preview",
    ),
    "solo": (
        "test_solo_mining_pipeline", "start_solo_mining", "stop_solo_mining", "reset_solo_mining",
        "test_block_assembly", "assemble_solo_candidate", "validate_solo_candidate", "submit_solo_candidate",
        "start_regtest_lab", "refresh_regtest_lab", "mine_regtest_blocks", "stop_regtest_lab", "reset_regtest_lab",
    ),
    "asic": (
        "start_asic_solo_bridge", "stop_asic_solo_bridge", "assign_asic_to_solo", "restore_asic_pool_zero",
        "discover_asics", "refresh_asics", "add_asic", "remove_asic", "open_asic_web", "restart_asic",
        "switch_asic_pool",
    ),
    "external": ("open_paypal_donation",),
}

EXPOSED_API_METHODS = tuple(dict.fromkeys(name for group in API_GROUPS.values() for name in group))


def contract_snapshot(backend=None):
    available = []
    missing = []
    if backend is not None:
        for name in EXPOSED_API_METHODS:
            value = getattr(backend, name, None)
            (available if callable(value) else missing).append(name)
    return {
        "schema": API_SCHEMA,
        "groups": {key: list(value) for key, value in API_GROUPS.items()},
        "exposed_count": len(EXPOSED_API_METHODS),
        "available_count": len(available) if backend is not None else None,
        "missing": missing,
    }
