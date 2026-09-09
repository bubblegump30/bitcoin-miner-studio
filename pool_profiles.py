"""Bitcoin Miner Studio v1.4.0 — Pool Profiles & Smart Failover.

Profile metadata is local-only. Pool passwords are deliberately excluded from
this file and are stored through the existing credential backend by WebBackend.
Exports are sanitized and never include credentials or free-form private notes.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from pool_powertools import normalize_endpoints

PROFILE_SCHEMA = 1
MAX_PROFILES = 32
MAX_NAME = 60
MAX_NOTES = 1000

FAILOVER_POLICIES = {
    "manual": {
        "label": "Manual Only",
        "failover_enabled": False,
        "failure_threshold": 999999,
        "max_backoff_seconds": 30,
        "primary_recovery_seconds": 0,
        "description": "Stay on the selected endpoint and reconnect there only.",
    },
    "conservative": {
        "label": "Conservative",
        "failover_enabled": True,
        "failure_threshold": 2,
        "max_backoff_seconds": 30,
        "primary_recovery_seconds": 900,
        "description": "Require two consecutive endpoint failures before switching; retry primary after 15 minutes.",
    },
    "balanced": {
        "label": "Balanced",
        "failover_enabled": True,
        "failure_threshold": 1,
        "max_backoff_seconds": 15,
        "primary_recovery_seconds": 300,
        "description": "Fail over after one confirmed endpoint failure and retry primary after 5 minutes on backup.",
    },
    "aggressive": {
        "label": "Aggressive",
        "failover_enabled": True,
        "failure_threshold": 1,
        "max_backoff_seconds": 5,
        "primary_recovery_seconds": 60,
        "description": "Switch immediately and attempt primary recovery after 1 minute on backup.",
    },
}


def normalize_failover_policy(value):
    key = str(value or "balanced").strip().lower()
    return key if key in FAILOVER_POLICIES else "balanced"


def policy_for(value):
    key = normalize_failover_policy(value)
    return {"key": key, **dict(FAILOVER_POLICIES[key])}


def policy_options():
    return [{"key": key, **dict(value)} for key, value in FAILOVER_POLICIES.items()]


def _clean_name(value):
    value = " ".join(str(value or "").strip().split())
    if not value:
        raise ValueError("Profile name is required.")
    if len(value) > MAX_NAME:
        raise ValueError(f"Profile name must be {MAX_NAME} characters or fewer.")
    return value


def _clean_notes(value):
    value = str(value or "").strip()
    return value[:MAX_NOTES]


def _safe_id(value=""):
    value = str(value or "").strip().lower()
    if re.fullmatch(r"[a-f0-9]{12,40}", value):
        return value
    return uuid.uuid4().hex[:16]


def normalize_profile_payload(payload, existing=None):
    payload = dict(payload or {})
    existing = dict(existing or {})
    primary = str(payload.get("pool_url", existing.get("pool_url", "")) or "").strip()
    backups = payload.get("pool_backup_urls", existing.get("pool_backup_urls", []))
    if isinstance(backups, str):
        backups = [x.strip() for x in backups.replace(",", "\n").splitlines() if x.strip()]
    endpoints = normalize_endpoints(primary, backups or [])
    if not endpoints:
        raise ValueError("At least one valid Stratum endpoint is required for a pool profile.")

    worker = str(payload.get("pool_worker", existing.get("pool_worker", "")) or "").strip()
    if not worker:
        raise ValueError("Worker / wallet is required for a pool profile.")

    policy = normalize_failover_policy(payload.get("failover_policy", existing.get("failover_policy", "balanced")))
    policy_defaults = policy_for(policy)
    try:
        timeout = int(payload.get("job_timeout_seconds", existing.get("job_timeout_seconds", 120)))
    except (TypeError, ValueError):
        timeout = 120
    timeout = max(20, min(1800, timeout))

    try:
        recovery = int(payload.get("primary_recovery_seconds", existing.get("primary_recovery_seconds", policy_defaults["primary_recovery_seconds"])))
    except (TypeError, ValueError):
        recovery = policy_defaults["primary_recovery_seconds"]
    recovery = max(0, min(86400, recovery))

    try:
        fee = float(payload.get("pool_fee_percent", existing.get("pool_fee_percent", 1.0)))
    except (TypeError, ValueError):
        fee = 1.0
    fee = max(0.0, min(100.0, fee))

    try:
        processes = int(payload.get("mining_processes", existing.get("mining_processes", 2)))
    except (TypeError, ValueError):
        processes = 2
    processes = max(1, min(64, processes))

    try:
        suggested = float(payload.get("suggest_difficulty", existing.get("suggest_difficulty", 1.0)))
    except (TypeError, ValueError):
        suggested = 1.0
    if suggested <= 0:
        suggested = 1.0

    return {
        "id": _safe_id(payload.get("id") or existing.get("id")),
        "name": _clean_name(payload.get("name", existing.get("name", ""))),
        "pool_url": endpoints[0],
        "pool_backup_urls": endpoints[1:],
        "pool_worker": worker,
        "failover_policy": policy,
        "job_timeout_seconds": timeout,
        "primary_recovery_seconds": recovery,
        "pool_fee_percent": fee,
        "mining_processes": processes,
        "suggest_difficulty_enabled": bool(payload.get("suggest_difficulty_enabled", existing.get("suggest_difficulty_enabled", False))),
        "suggest_difficulty": suggested,
        "enabled": bool(payload.get("enabled", existing.get("enabled", True))),
        "notes": _clean_notes(payload.get("notes", existing.get("notes", ""))),
    }


class PoolProfileStore:
    def __init__(self, path):
        self.path = Path(path)
        self._profiles = []
        self._load()

    def _load(self):
        try:
            if not self.path.exists():
                self._profiles = []
                return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            rows = raw.get("profiles", []) if isinstance(raw, dict) else []
            clean = []
            for row in rows[:MAX_PROFILES]:
                try:
                    normalized = normalize_profile_payload(row, row)
                    normalized["created_at"] = float(row.get("created_at") or time.time())
                    normalized["updated_at"] = float(row.get("updated_at") or normalized["created_at"])
                    clean.append(normalized)
                except Exception:
                    continue
            self._profiles = clean
        except Exception:
            self._profiles = []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": PROFILE_SCHEMA, "profiles": self._profiles}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def list(self):
        return [dict(row) for row in sorted(self._profiles, key=lambda x: (str(x.get("name", "")).lower(), x.get("id", "")))]

    def get(self, profile_id):
        profile_id = str(profile_id or "").strip()
        for row in self._profiles:
            if row.get("id") == profile_id:
                return dict(row)
        return None

    def upsert(self, payload):
        payload = dict(payload or {})
        profile_id = str(payload.get("id") or "").strip()
        existing = self.get(profile_id) if profile_id else None
        if not existing and len(self._profiles) >= MAX_PROFILES:
            raise ValueError(f"Maximum pool profile count is {MAX_PROFILES}.")
        row = normalize_profile_payload(payload, existing)
        now = time.time()
        row["created_at"] = float((existing or {}).get("created_at") or now)
        row["updated_at"] = now
        if existing:
            self._profiles = [row if x.get("id") == row["id"] else x for x in self._profiles]
        else:
            self._profiles.append(row)
        self._save()
        return dict(row)

    def delete(self, profile_id):
        profile_id = str(profile_id or "").strip()
        before = len(self._profiles)
        self._profiles = [row for row in self._profiles if row.get("id") != profile_id]
        if len(self._profiles) == before:
            return False
        self._save()
        return True

    def sanitized_export(self, active_profile_id=""):
        rows = []
        for row in self.list():
            rows.append({
                "id": row.get("id"),
                "name": row.get("name"),
                "pool_url": row.get("pool_url"),
                "pool_backup_urls": list(row.get("pool_backup_urls") or []),
                "pool_worker": row.get("pool_worker"),
                "failover_policy": row.get("failover_policy"),
                "job_timeout_seconds": row.get("job_timeout_seconds"),
                "primary_recovery_seconds": row.get("primary_recovery_seconds"),
                "pool_fee_percent": row.get("pool_fee_percent"),
                "mining_processes": row.get("mining_processes"),
                "suggest_difficulty_enabled": row.get("suggest_difficulty_enabled"),
                "suggest_difficulty": row.get("suggest_difficulty"),
                "enabled": row.get("enabled"),
                # Free-form notes are intentionally excluded because users may put private data there.
            })
        return {
            "schema": PROFILE_SCHEMA,
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "active_profile_id": str(active_profile_id or ""),
            "profiles": rows,
            "credentials": "excluded",
            "notes": "excluded",
        }


def profile_to_pool_config(profile):
    row = dict(profile or {})
    policy = policy_for(row.get("failover_policy"))
    return {
        "pool_url": row.get("pool_url", ""),
        "pool_backup_urls": list(row.get("pool_backup_urls") or []),
        "pool_worker": row.get("pool_worker", ""),
        "pool_failover_policy": policy["key"],
        "pool_failover_enabled": bool(policy["failover_enabled"]),
        "pool_job_timeout_seconds": int(row.get("job_timeout_seconds") or 120),
        "pool_primary_recovery_seconds": int(row.get("primary_recovery_seconds") or 0),
        "mining_processes": int(row.get("mining_processes") or 2),
        "suggest_difficulty_enabled": bool(row.get("suggest_difficulty_enabled")),
        "suggest_difficulty": float(row.get("suggest_difficulty") or 1.0),
    }
