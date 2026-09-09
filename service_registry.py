"""Lifecycle/health registry for Bitcoin Miner Studio v2 backend services."""
from __future__ import annotations

import threading
import time
from typing import Dict, Iterable


VALID_STATES = {"registered", "starting", "running", "idle", "degraded", "stopped", "error"}


class ServiceRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._services: Dict[str, Dict[str, object]] = {}

    def register(self, service_id: str, *, label: str, category: str, critical: bool = False, state: str = "registered"):
        service_id = str(service_id).strip()
        if not service_id:
            raise ValueError("service_id is required")
        now = time.time()
        with self._lock:
            existing = self._services.get(service_id, {})
            self._services[service_id] = {
                "id": service_id,
                "label": str(label or service_id),
                "category": str(category or "system"),
                "critical": bool(critical),
                "state": state if state in VALID_STATES else "registered",
                "registered_at": existing.get("registered_at", now),
                "updated_at": now,
                "message": existing.get("message", ""),
                "last_error": existing.get("last_error", ""),
            }
        return self.get(service_id)

    def mark(self, service_id: str, state: str, message: str = "", *, error: str = ""):
        if state not in VALID_STATES:
            raise ValueError(f"Unsupported service state: {state}")
        with self._lock:
            if service_id not in self._services:
                self.register(service_id, label=service_id, category="system")
            row = self._services[service_id]
            row["state"] = state
            row["updated_at"] = time.time()
            if message:
                row["message"] = str(message)
            if error:
                row["last_error"] = str(error)
            elif state not in {"error", "degraded"}:
                row["last_error"] = ""
            return dict(row)

    def get(self, service_id: str):
        with self._lock:
            row = self._services.get(str(service_id))
            return dict(row) if row else None

    def snapshot(self):
        with self._lock:
            services = [dict(row) for _, row in sorted(self._services.items())]
        error_count = sum(1 for row in services if row["state"] == "error")
        degraded_count = sum(1 for row in services if row["state"] == "degraded")
        critical_bad = sum(1 for row in services if row["critical"] and row["state"] in {"error", "degraded", "stopped"})
        running = sum(1 for row in services if row["state"] == "running")
        overall = "HEALTHY"
        if critical_bad or error_count:
            overall = "DEGRADED"
        elif degraded_count:
            overall = "ATTENTION"
        return {
            "architecture": "BMS-ARCH-2",
            "overall": overall,
            "registered": len(services),
            "running": running,
            "degraded": degraded_count,
            "errors": error_count,
            "critical_issues": critical_bad,
            "services": services,
        }
