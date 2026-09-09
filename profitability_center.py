"""Bitcoin Miner Studio v1.2.0 — Profitability & Power Center.

All calculations are estimates. This module performs local arithmetic only.
It does not fetch market prices, make financial promises, start mining, change
pool settings, or control hardware.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


SECONDS_PER_DAY = 86400.0
DIFF1_HASHES = float(2 ** 32)
DAYS_PER_MONTH = 30.4375
DAYS_PER_YEAR = 365.25


def clamp(value, low, high):
    return max(low, min(high, value))


def block_subsidy_for_height(height: int) -> float:
    """Return consensus block subsidy in BTC for a given block height."""
    height = max(0, int(height or 0))
    halvings = height // 210000
    if halvings >= 64:
        return 0.0
    # Consensus subsidy starts at 50 BTC and halves every 210,000 blocks.
    return 50.0 / (2 ** halvings)


def network_hashrate_hs(difficulty: float, block_interval_seconds: float = 600.0) -> float:
    difficulty = max(0.0, float(difficulty or 0))
    if difficulty <= 0 or block_interval_seconds <= 0:
        return 0.0
    return difficulty * DIFF1_HASHES / float(block_interval_seconds)


def expected_blocks_per_day(hashrate_hs: float, difficulty: float) -> float:
    hashrate_hs = max(0.0, float(hashrate_hs or 0))
    difficulty = max(0.0, float(difficulty or 0))
    if hashrate_hs <= 0 or difficulty <= 0:
        return 0.0
    return hashrate_hs * SECONDS_PER_DAY / (difficulty * DIFF1_HASHES)


def probability_at_least_one(expected_blocks: float) -> float:
    expected_blocks = max(0.0, float(expected_blocks or 0))
    if expected_blocks <= 0:
        return 0.0
    # Poisson probability of one or more discoveries.
    if expected_blocks > 700:
        return 1.0
    return 1.0 - math.exp(-expected_blocks)


def mean_time_to_block_seconds(hashrate_hs: float, difficulty: float) -> float | None:
    hashrate_hs = max(0.0, float(hashrate_hs or 0))
    difficulty = max(0.0, float(difficulty or 0))
    if hashrate_hs <= 0 or difficulty <= 0:
        return None
    return difficulty * DIFF1_HASHES / hashrate_hs


def probability_time_50_seconds(hashrate_hs: float, difficulty: float) -> float | None:
    mean = mean_time_to_block_seconds(hashrate_hs, difficulty)
    if not mean:
        return None
    return mean * math.log(2.0)


def profitability_snapshot(
    *,
    hashrate_hs: float,
    power_watts: float,
    electricity_per_kwh: float,
    pool_fee_percent: float,
    btc_price: float,
    difficulty: float,
    block_subsidy_btc: float,
    avg_fees_btc_per_block: float = 0.0,
):
    hashrate_hs = max(0.0, float(hashrate_hs or 0))
    power_watts = max(0.0, float(power_watts or 0))
    electricity_per_kwh = max(0.0, float(electricity_per_kwh or 0))
    pool_fee_percent = clamp(float(pool_fee_percent or 0), 0.0, 100.0)
    btc_price = max(0.0, float(btc_price or 0))
    difficulty = max(0.0, float(difficulty or 0))
    block_subsidy_btc = max(0.0, float(block_subsidy_btc or 0))
    avg_fees_btc_per_block = max(0.0, float(avg_fees_btc_per_block or 0))

    reward_btc = block_subsidy_btc + avg_fees_btc_per_block
    blocks_day = expected_blocks_per_day(hashrate_hs, difficulty)
    gross_btc_day = blocks_day * reward_btc
    pool_multiplier = 1.0 - (pool_fee_percent / 100.0)
    net_btc_day = gross_btc_day * pool_multiplier

    gross_revenue_day = gross_btc_day * btc_price
    revenue_after_pool_day = net_btc_day * btc_price

    kwh_day = power_watts * 24.0 / 1000.0
    electricity_day = kwh_day * electricity_per_kwh
    net_day = revenue_after_pool_day - electricity_day

    gross_month = revenue_after_pool_day * DAYS_PER_MONTH
    electricity_month = electricity_day * DAYS_PER_MONTH
    net_month = net_day * DAYS_PER_MONTH

    gross_year = revenue_after_pool_day * DAYS_PER_YEAR
    electricity_year = electricity_day * DAYS_PER_YEAR
    net_year = net_day * DAYS_PER_YEAR

    efficiency_w_per_th = None
    ths = hashrate_hs / 1e12
    if ths > 0:
        efficiency_w_per_th = power_watts / ths

    break_even_electricity = None
    if kwh_day > 0:
        break_even_electricity = revenue_after_pool_day / kwh_day

    network_hs = network_hashrate_hs(difficulty)
    network_share = (hashrate_hs / network_hs) if network_hs > 0 else 0.0

    mean_seconds = mean_time_to_block_seconds(hashrate_hs, difficulty)
    p50_seconds = probability_time_50_seconds(hashrate_hs, difficulty)

    odds = {}
    for key, seconds in (
        ("1h", 3600.0),
        ("24h", 86400.0),
        ("7d", 7 * 86400.0),
        ("30d", 30 * 86400.0),
        ("365d", 365.25 * 86400.0),
    ):
        expected = 0.0
        if mean_seconds:
            expected = seconds / mean_seconds
        odds[key] = probability_at_least_one(expected)

    return {
        "inputs": {
            "hashrate_hs": hashrate_hs,
            "power_watts": power_watts,
            "electricity_per_kwh": electricity_per_kwh,
            "pool_fee_percent": pool_fee_percent,
            "btc_price": btc_price,
            "difficulty": difficulty,
            "block_subsidy_btc": block_subsidy_btc,
            "avg_fees_btc_per_block": avg_fees_btc_per_block,
        },
        "network": {
            "estimated_hashrate_hs": network_hs,
            "miner_share": network_share,
        },
        "mining": {
            "expected_blocks_per_day": blocks_day,
            "gross_btc_day": gross_btc_day,
            "net_btc_day": net_btc_day,
            "reward_btc_per_block": reward_btc,
            "mean_time_to_block_seconds": mean_seconds,
            "probability_50_seconds": p50_seconds,
            "solo_probability": odds,
        },
        "power": {
            "kwh_day": kwh_day,
            "electricity_day": electricity_day,
            "electricity_month": electricity_month,
            "electricity_year": electricity_year,
            "efficiency_w_per_th": efficiency_w_per_th,
            "break_even_electricity_per_kwh": break_even_electricity,
        },
        "financial": {
            "gross_revenue_day": gross_revenue_day,
            "revenue_after_pool_day": revenue_after_pool_day,
            "net_day": net_day,
            "gross_month": gross_month,
            "electricity_month": electricity_month,
            "net_month": net_month,
            "gross_year": gross_year,
            "electricity_year": electricity_year,
            "net_year": net_year,
        },
        "disclaimer": (
            "Estimates only. Actual mining results, pool payout methods, transaction "
            "fees, network difficulty, BTC price, hardware power draw, uptime and "
            "electricity billing can materially change results. Profit is not guaranteed."
        ),
    }


def default_profitability_inputs(cfg=None, core_state=None):
    cfg = dict(cfg or {})
    core_state = dict(core_state or {})

    height = int(core_state.get("blocks") or core_state.get("height") or 0)
    difficulty = float(core_state.get("difficulty") or 0)

    return {
        "hashrate_hs": float(cfg.get("profitability_hashrate_hs") or 0),
        "power_watts": float(cfg.get("profitability_power_watts") or 0),
        "electricity_per_kwh": float(cfg.get("profitability_electricity_per_kwh") or 0.15),
        "pool_fee_percent": float(cfg.get("profitability_pool_fee_percent") or 1.0),
        "btc_price": float(cfg.get("profitability_btc_price") or 0),
        "difficulty": difficulty or float(cfg.get("profitability_difficulty") or 0),
        "height": height or int(cfg.get("profitability_height") or 0),
        "block_subsidy_btc": (
            block_subsidy_for_height(height)
            if height > 0
            else float(cfg.get("profitability_block_subsidy_btc") or 3.125)
        ),
        "avg_fees_btc_per_block": float(cfg.get("profitability_avg_fees_btc_per_block") or 0),
        "core_connected": bool(core_state.get("connected")),
    }
