"""Persistent local workspace/navigation preferences for Bitcoin Miner Studio v2."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


KNOWN_VIEWS = (
    "dashboard", "benchmark", "academy", "assistant", "profitability", "hardware",
    "asic", "pool", "core", "monitoring", "tray", "logs", "diagnostics", "minerxp",
    "release", "security",
)

DEFAULT_PINNED = ["dashboard", "pool", "core", "monitoring"]


class WorkspaceManager:
    SCHEMA = 2

    def __init__(self, storage_path: Path):
        self.path = Path(storage_path)
        self._lock = threading.RLock()
        self._state = self._load()

    def _default(self):
        return {
            "schema": self.SCHEMA,
            "last_view": "dashboard",
            "recent_views": ["dashboard"],
            "pinned_views": list(DEFAULT_PINNED),
            "sidebar_compact": False,
            "command_usage": {},
            "updated_at": time.time(),
        }

    def _load(self):
        state = self._default()
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    state.update(raw)
        except Exception:
            pass
        state["schema"] = self.SCHEMA
        state["last_view"] = state.get("last_view") if state.get("last_view") in KNOWN_VIEWS else "dashboard"
        recent = [x for x in state.get("recent_views", []) if x in KNOWN_VIEWS]
        state["recent_views"] = recent[:8] or [state["last_view"]]
        pinned = []
        for view in state.get("pinned_views", DEFAULT_PINNED):
            if view in KNOWN_VIEWS and view not in pinned:
                pinned.append(view)
        state["pinned_views"] = pinned[:8]
        state["sidebar_compact"] = bool(state.get("sidebar_compact", False))
        usage = state.get("command_usage")
        state["command_usage"] = dict(usage) if isinstance(usage, dict) else {}
        return state

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self._state))

    def record_view(self, view: str):
        view = str(view or "").strip().lower()
        if view not in KNOWN_VIEWS:
            raise ValueError("Unknown workspace view")
        with self._lock:
            recent = [x for x in self._state.get("recent_views", []) if x != view]
            recent.insert(0, view)
            self._state["recent_views"] = recent[:8]
            self._state["last_view"] = view
            self._state["updated_at"] = time.time()
            self._save()
            return self.snapshot()

    def set_preferences(self, *, sidebar_compact=None, pinned_views=None):
        with self._lock:
            if sidebar_compact is not None:
                self._state["sidebar_compact"] = bool(sidebar_compact)
            if pinned_views is not None:
                clean = []
                for view in list(pinned_views or []):
                    view = str(view or "").strip().lower()
                    if view in KNOWN_VIEWS and view not in clean:
                        clean.append(view)
                self._state["pinned_views"] = clean[:8]
            self._state["updated_at"] = time.time()
            self._save()
            return self.snapshot()

    def record_command(self, command_id: str):
        command_id = str(command_id or "").strip()
        if not command_id:
            return self.snapshot()
        with self._lock:
            usage = self._state.setdefault("command_usage", {})
            usage[command_id] = min(999999, int(usage.get(command_id, 0) or 0) + 1)
            if len(usage) > 80:
                ranked = sorted(usage.items(), key=lambda item: item[1], reverse=True)[:60]
                self._state["command_usage"] = dict(ranked)
            self._state["updated_at"] = time.time()
            self._save()
            return self.snapshot()
