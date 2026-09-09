"""In-process event stream for Bitcoin Miner Studio v2.

The event stream is intentionally local and bounded. It gives independent
subsystems a common observability surface without introducing cloud telemetry or
network transport.
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Dict, Iterable, List


class LocalEventBus:
    def __init__(self, max_events: int = 300):
        self._lock = threading.RLock()
        self._events = deque(maxlen=max(50, int(max_events)))
        self._sequence = 0

    def publish(self, source: str, kind: str, message: str, *, level: str = "info", data=None) -> Dict[str, object]:
        event = {
            "seq": 0,
            "ts": time.time(),
            "source": str(source or "system"),
            "kind": str(kind or "event"),
            "level": str(level or "info").lower(),
            "message": str(message or ""),
        }
        if isinstance(data, dict) and data:
            # Event metadata must stay lightweight. Callers should never put
            # passwords/keys in this field.
            event["data"] = dict(data)
        with self._lock:
            self._sequence += 1
            event["seq"] = self._sequence
            self._events.append(event)
            return dict(event)

    def recent(self, limit: int = 50, *, sources: Iterable[str] | None = None) -> List[Dict[str, object]]:
        limit = max(1, min(300, int(limit or 50)))
        wanted = {str(x) for x in (sources or []) if str(x)}
        with self._lock:
            rows = list(self._events)
        if wanted:
            rows = [row for row in rows if row.get("source") in wanted]
        return [dict(row) for row in rows[-limit:]]

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            rows = list(self._events)
            sequence = self._sequence
        levels = Counter(str(row.get("level") or "info") for row in rows)
        sources = Counter(str(row.get("source") or "system") for row in rows)
        return {
            "sequence": sequence,
            "retained": len(rows),
            "levels": dict(levels),
            "sources": dict(sources),
            "recent": [dict(row) for row in rows[-20:]],
        }
