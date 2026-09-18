"""Bitcoin Miner Studio v0.8.0 — Monitoring & Analytics.

Local-only persistent observability for pool mining, solo mining, Bitcoin Core,
and authorized ASIC fleet telemetry. The SQLite database deliberately excludes
pool/RPC passwords, wallet seed phrases, private keys, and raw credentials.
"""
from __future__ import annotations

import csv
import json
from contextlib import contextmanager
import math
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_SAMPLE_SECONDS = 10
DEFAULT_RETENTION_DAYS = 30
MAX_POINTS = 480

SAMPLE_COLUMNS = [
    "ts",
    "pool_running", "pool_hashrate", "pool_avg_hashrate", "pool_acceptance",
    "pool_accepted", "pool_rejected", "pool_stale", "pool_share_p95_ms",
    "pool_health", "pool_job_age", "pool_failovers", "pool_reconnects",
    "solo_running", "solo_hashrate", "solo_avg_hashrate", "solo_peak_hashrate",
    "solo_best_difficulty", "solo_target_ratio", "solo_stale_batches",
    "core_connected", "core_rpc_latency_ms", "core_peers", "core_sync_percent", "core_height",
    "asic_total", "asic_online", "asic_hashrate", "asic_avg_temp", "asic_max_temp", "asic_avg_health",
]


def _f(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else float(default)
    except Exception:
        return float(default)


def _i(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)


def percentile(values, p):
    vals = sorted(_f(x) for x in values if x is not None)
    if not vals:
        return 0.0
    if len(vals) == 1:
        return vals[0]
    p = max(0.0, min(1.0, _f(p)))
    pos = (len(vals) - 1) * p
    lo = int(pos)
    hi = min(len(vals) - 1, lo + 1)
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def _positive_delta(rows, key):
    total = 0
    previous = None
    for row in rows:
        current = _i(row.get(key))
        if previous is not None and current >= previous:
            total += current - previous
        previous = current
    return total


def sanitized_snapshot(snapshot):
    """Normalize a provider snapshot to the fixed credential-free schema."""
    source = dict(snapshot or {})
    row = {key: 0 for key in SAMPLE_COLUMNS}
    row["ts"] = _f(source.get("ts") or time.time())
    integer_keys = {
        "pool_accepted", "pool_rejected", "pool_stale", "pool_failovers", "pool_reconnects",
        "solo_stale_batches", "core_peers", "core_height", "asic_total", "asic_online",
    }
    bool_keys = {"pool_running", "solo_running", "core_connected"}
    for key in SAMPLE_COLUMNS[1:]:
        if key in bool_keys:
            row[key] = 1 if source.get(key) else 0
        elif key in integer_keys:
            row[key] = _i(source.get(key))
        else:
            row[key] = _f(source.get(key))
    return row


class AnalyticsStore:
    def __init__(
        self,
        db_path,
        sample_seconds=DEFAULT_SAMPLE_SECONDS,
        retention_days=DEFAULT_RETENTION_DAYS,
        event_callback=None,
    ):
        self.db_path = Path(db_path)
        self.sample_seconds = max(5, min(300, int(sample_seconds)))
        self.retention_days = max(1, min(365, int(retention_days)))
        self.event_callback = event_callback or (lambda kind, payload: None)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._provider = None
        self._last_sample = 0.0
        self._last_prune = 0.0
        self._error = ""
        self._condition_state = {}
        self._initialize()

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=8.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def _connection(self):
        """Commit/rollback and always close a SQLite connection.

        sqlite3.Connection's built-in context manager manages transactions but
        does not close the connection. Explicit closure is required on Windows
        so analytics.sqlite3 is not left locked after a test, shutdown, export,
        or clear operation.
        """
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize(self):
        with self._lock, self._connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("""CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                pool_running INTEGER NOT NULL DEFAULT 0,
                pool_hashrate REAL NOT NULL DEFAULT 0,
                pool_avg_hashrate REAL NOT NULL DEFAULT 0,
                pool_acceptance REAL NOT NULL DEFAULT 0,
                pool_accepted INTEGER NOT NULL DEFAULT 0,
                pool_rejected INTEGER NOT NULL DEFAULT 0,
                pool_stale INTEGER NOT NULL DEFAULT 0,
                pool_share_p95_ms REAL NOT NULL DEFAULT 0,
                pool_health REAL NOT NULL DEFAULT 0,
                pool_job_age REAL NOT NULL DEFAULT 0,
                pool_failovers INTEGER NOT NULL DEFAULT 0,
                pool_reconnects INTEGER NOT NULL DEFAULT 0,
                solo_running INTEGER NOT NULL DEFAULT 0,
                solo_hashrate REAL NOT NULL DEFAULT 0,
                solo_avg_hashrate REAL NOT NULL DEFAULT 0,
                solo_peak_hashrate REAL NOT NULL DEFAULT 0,
                solo_best_difficulty REAL NOT NULL DEFAULT 0,
                solo_target_ratio REAL NOT NULL DEFAULT 0,
                solo_stale_batches INTEGER NOT NULL DEFAULT 0,
                core_connected INTEGER NOT NULL DEFAULT 0,
                core_rpc_latency_ms REAL NOT NULL DEFAULT 0,
                core_peers INTEGER NOT NULL DEFAULT 0,
                core_sync_percent REAL NOT NULL DEFAULT 0,
                core_height INTEGER NOT NULL DEFAULT 0,
                asic_total INTEGER NOT NULL DEFAULT 0,
                asic_online INTEGER NOT NULL DEFAULT 0,
                asic_hashrate REAL NOT NULL DEFAULT 0,
                asic_avg_temp REAL NOT NULL DEFAULT 0,
                asic_max_temp REAL NOT NULL DEFAULT 0,
                asic_avg_health REAL NOT NULL DEFAULT 0
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts)")
            conn.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                severity TEXT NOT NULL,
                source TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
            conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    def start(self, provider):
        with self._lock:
            self._provider = provider
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="MonitoringAnalyticsSampler",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def configure(self, sample_seconds=None, retention_days=None):
        with self._lock:
            if sample_seconds is not None:
                self.sample_seconds = max(5, min(300, int(sample_seconds)))
            if retention_days is not None:
                self.retention_days = max(1, min(365, int(retention_days)))
        return self.status()

    def _loop(self):
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                provider = self._provider
                if provider:
                    self.record(provider())
                    self._error = ""
            except Exception as exc:
                self._error = str(exc)
                try:
                    self.event_callback("log", f"Monitoring sample error: {exc}")
                except Exception:
                    pass
            delay = max(0.25, self.sample_seconds - (time.monotonic() - started))
            self._stop.wait(delay)

    def record(self, snapshot):
        row = sanitized_snapshot(snapshot)
        placeholders = ",".join("?" for _ in SAMPLE_COLUMNS)
        with self._lock, self._connection() as conn:
            conn.execute(
                f"INSERT INTO samples ({','.join(SAMPLE_COLUMNS)}) VALUES ({placeholders})",
                [row[key] for key in SAMPLE_COLUMNS],
            )
            self._detect_events(conn, row)
            now = time.time()
            if now - self._last_prune >= 3600:
                cutoff = now - self.retention_days * 86400
                conn.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
                conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
                self._last_prune = now
            self._last_sample = row["ts"]
        return row

    def _condition(self, conn, key, active, severity, source, kind, message, recovery=None):
        previous = bool(self._condition_state.get(key, False))
        active = bool(active)
        if active and not previous:
            conn.execute(
                "INSERT INTO events(ts,severity,source,kind,message,active) VALUES (?,?,?,?,?,1)",
                (time.time(), severity, source, kind, message),
            )
        elif previous and not active and recovery:
            conn.execute(
                "INSERT INTO events(ts,severity,source,kind,message,active) VALUES (?,?,?,?,?,0)",
                (time.time(), "info", source, f"{kind}_recovered", recovery),
            )
        self._condition_state[key] = active

    def _detect_events(self, conn, row):
        decided = row["pool_accepted"] + row["pool_rejected"] + row["pool_stale"]
        bad_ratio = ((row["pool_rejected"] + row["pool_stale"]) / decided) if decided else 0.0
        self._condition(conn, "pool_health", row["pool_running"] and row["pool_health"] < 70,
                        "warning", "Pool", "health", f"Pool health fell to {row['pool_health']:.0f}/100.",
                        "Pool health recovered above the alert threshold.")
        self._condition(conn, "pool_share_latency", row["pool_running"] and row["pool_share_p95_ms"] > 2000,
                        "warning", "Pool", "latency", f"Pool p95 share response latency reached {row['pool_share_p95_ms']:.0f} ms.",
                        "Pool p95 share response latency recovered.")
        self._condition(conn, "pool_bad_share_ratio", row["pool_running"] and decided >= 10 and bad_ratio >= 0.05,
                        "warning", "Pool", "share_quality", f"Rejected/stale share ratio reached {bad_ratio*100:.1f}%.",
                        "Rejected/stale share ratio recovered.")
        self._condition(conn, "core_offline", not row["core_connected"], "warning", "Bitcoin Core", "offline",
                        "Bitcoin Core RPC monitoring is offline.", "Bitcoin Core RPC monitoring recovered.")
        self._condition(conn, "core_latency", row["core_connected"] and row["core_rpc_latency_ms"] > 2500,
                        "warning", "Bitcoin Core", "rpc_latency", f"Bitcoin Core RPC latency reached {row['core_rpc_latency_ms']:.0f} ms.",
                        "Bitcoin Core RPC latency recovered.")
        self._condition(conn, "solo_stale", row["solo_running"] and row["solo_stale_batches"] > 0,
                        "warning", "Solo Mining", "stale_work", f"Solo mining discarded {row['solo_stale_batches']} stale batch(es).",
                        "Solo stale-work counter returned to zero.")
        self._condition(conn, "asic_offline", row["asic_total"] > 0 and row["asic_online"] < row["asic_total"],
                        "warning", "ASIC Fleet", "offline", f"{row['asic_total']-row['asic_online']} of {row['asic_total']} ASIC(s) are not online.",
                        "All monitored ASICs are online.")
        self._condition(conn, "asic_hot", row["asic_total"] > 0 and row["asic_max_temp"] >= 80,
                        "critical", "ASIC Fleet", "temperature", f"ASIC maximum temperature reached {row['asic_max_temp']:.1f} °C.",
                        "ASIC temperatures recovered below 80 °C.")

    def _rows(self, since, max_points=MAX_POINTS):
        with self._connection() as conn:
            rows = [
                dict(row) for row in conn.execute(
                    "SELECT * FROM samples WHERE ts>=? ORDER BY ts ASC", (float(since),)
                ).fetchall()
            ]
        if len(rows) <= max_points:
            return rows
        step = (len(rows) - 1) / (max_points - 1)
        indices = sorted(set(round(i * step) for i in range(max_points)))
        return [rows[index] for index in indices]

    def dashboard(self, range_seconds=3600, max_points=MAX_POINTS):
        now = time.time()
        range_seconds = max(300, min(365 * 86400, int(range_seconds)))
        since = now - range_seconds
        rows = self._rows(since, max_points=max_points)
        with self._connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            first = conn.execute("SELECT MIN(ts) FROM samples").fetchone()[0]
            events = [
                dict(row) for row in conn.execute(
                    "SELECT ts,severity,source,kind,message,active FROM events WHERE ts>=? ORDER BY ts DESC LIMIT 100",
                    (since,),
                ).fetchall()
            ]
        latest = rows[-1] if rows else {}
        pool_rows = [r for r in rows if r.get("pool_running")]
        solo_rows = [r for r in rows if r.get("solo_running")]
        core_rows = [r for r in rows if r.get("core_connected")]
        asic_rows = [r for r in rows if r.get("asic_total", 0) > 0]
        accepted = _positive_delta(rows, "pool_accepted")
        rejected = _positive_delta(rows, "pool_rejected")
        stale = _positive_delta(rows, "pool_stale")
        decided = accepted + rejected + stale
        summary = {
            "sample_count": count,
            "range_sample_count": len(rows),
            "first_sample": _f(first),
            "last_sample": _f(latest.get("ts")),
            "pool_avg_hashrate": sum(_f(r.get("pool_hashrate")) for r in pool_rows) / len(pool_rows) if pool_rows else 0.0,
            "pool_peak_hashrate": max((_f(r.get("pool_hashrate")) for r in pool_rows), default=0.0),
            "pool_acceptance": accepted / decided * 100 if decided else _f(latest.get("pool_acceptance")),
            "pool_accepted_delta": accepted,
            "pool_rejected_delta": rejected,
            "pool_stale_delta": stale,
            "pool_health_avg": sum(_f(r.get("pool_health")) for r in pool_rows) / len(pool_rows) if pool_rows else 0.0,
            "pool_share_p95_ms": percentile([r.get("pool_share_p95_ms") for r in pool_rows if _f(r.get("pool_share_p95_ms")) > 0], 0.95),
            "solo_avg_hashrate": sum(_f(r.get("solo_hashrate")) for r in solo_rows) / len(solo_rows) if solo_rows else 0.0,
            "solo_peak_hashrate": max((_f(r.get("solo_hashrate")) for r in solo_rows), default=0.0),
            "solo_best_difficulty": max((_f(r.get("solo_best_difficulty")) for r in rows), default=0.0),
            "core_availability": sum(1 for r in rows if r.get("core_connected")) / len(rows) * 100 if rows else 0.0,
            "core_rpc_p95_ms": percentile([r.get("core_rpc_latency_ms") for r in core_rows if _f(r.get("core_rpc_latency_ms")) > 0], 0.95),
            "core_height": _i(latest.get("core_height")),
            "asic_avg_hashrate": sum(_f(r.get("asic_hashrate")) for r in asic_rows) / len(asic_rows) if asic_rows else 0.0,
            "asic_avg_health": sum(_f(r.get("asic_avg_health")) for r in asic_rows) / len(asic_rows) if asic_rows else 0.0,
            "asic_max_temp": max((_f(r.get("asic_max_temp")) for r in asic_rows), default=0.0),
        }
        series_keys = (
            "ts", "pool_hashrate", "pool_health", "pool_share_p95_ms",
            "solo_hashrate", "solo_best_difficulty", "core_rpc_latency_ms",
            "core_peers", "core_sync_percent", "asic_hashrate", "asic_avg_temp",
            "asic_max_temp", "asic_avg_health",
        )
        series = [{key: row.get(key) for key in series_keys} for row in rows]
        return {
            "ok": True,
            "status": self.status(),
            "range_seconds": range_seconds,
            "summary": summary,
            "latest": latest,
            "series": series,
            "events": events,
        }

    def status(self):
        with self._lock:
            size = self.db_path.stat().st_size if self.db_path.exists() else 0
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "sample_seconds": self.sample_seconds,
                "retention_days": self.retention_days,
                "last_sample": self._last_sample,
                "database_path": str(self.db_path),
                "database_size": size,
                "error": self._error,
                "local_only": True,
                "schema_version": SCHEMA_VERSION,
            }

    def clear(self):
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM samples")
            conn.execute("DELETE FROM events")
            conn.commit()
            conn.execute("VACUUM")
            self._last_sample = 0.0
            self._condition_state.clear()
        return self.status()

    def export(self, destination, range_seconds, fmt="csv"):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        rows = self._rows(time.time() - max(300, int(range_seconds)), max_points=1_000_000)
        fmt = str(fmt).lower()
        if fmt == "json":
            payload = {
                "exported_at": time.time(),
                "range_seconds": int(range_seconds),
                "credential_free": True,
                "samples": rows,
            }
            destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        elif fmt == "csv":
            with destination.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id"] + SAMPLE_COLUMNS)
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: row.get(key) for key in ["id"] + SAMPLE_COLUMNS})
        else:
            raise ValueError("Analytics export format must be csv or json.")
        return {
            "path": str(destination),
            "rows": len(rows),
            "format": fmt,
            "bytes": destination.stat().st_size,
        }
