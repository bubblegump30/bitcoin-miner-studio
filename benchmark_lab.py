"""Bitcoin Miner Studio v1.6.0 — Benchmark Lab 2.0.

Local-only SHA-256d benchmark orchestration. The lab never connects to a pool,
Bitcoin Core, a wallet, or an ASIC. Results are stored locally under the normal
Bitcoin Miner Studio configuration directory.
"""

from __future__ import annotations

import csv
import json
import math
import os
import platform
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import CONFIG_DIR

BENCHMARK_HISTORY_FILE = CONFIG_DIR / "benchmark-history.json"
BENCHMARK_HISTORY_LIMIT = 100
BENCHMARK_SCHEMA = 2


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def benchmark_score(avg_hashrate: float, stability_percent: float) -> float:
    """Local comparison score: kH/s multiplied by measured stability factor."""
    avg_hashrate = max(0.0, _safe_float(avg_hashrate))
    stability = _clamp(_safe_float(stability_percent, 100.0), 0.0, 100.0) / 100.0
    return (avg_hashrate / 1000.0) * stability


def recommended_worker_counts(cpu_count=None):
    cpu_count = max(1, min(64, _safe_int(cpu_count or os.cpu_count() or 1, 1)))
    counts = [1]
    n = 2
    while n < cpu_count:
        counts.append(n)
        n *= 2
    if cpu_count not in counts:
        counts.append(cpu_count)
    return sorted(set(max(1, min(64, x)) for x in counts))


class BenchmarkHistoryStore:
    def __init__(self, path: Path | None = None, limit: int = BENCHMARK_HISTORY_LIMIT):
        self.path = Path(path or BENCHMARK_HISTORY_FILE)
        self.limit = max(10, int(limit))
        self._lock = threading.RLock()

    def load(self):
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                rows = raw.get("history", []) if isinstance(raw, dict) else raw
                if not isinstance(rows, list):
                    return []
                return [dict(row) for row in rows if isinstance(row, dict)][-self.limit :]
            except Exception:
                return []

    def save(self, rows):
        clean = [dict(row) for row in list(rows or []) if isinstance(row, dict)][-self.limit :]
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"schema": BENCHMARK_SCHEMA, "history": clean}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return clean

    def append(self, row):
        rows = self.load()
        rows.append(dict(row))
        self.save(rows)
        return row

    def clear(self):
        self.save([])


class BenchmarkLabController:
    """Orchestrates single and worker-scaling benchmark runs around BenchmarkEngine."""

    def __init__(self, engine, history_path: Path | None = None, log_callback=None):
        self.engine = engine
        self.history = BenchmarkHistoryStore(history_path)
        self.log_callback = log_callback
        self._lock = threading.RLock()
        self._mode = "idle"
        self._active = {}
        self._last_result = None
        self._suite = self._empty_suite_state()
        self._suite_thread = None
        self._suite_stop = threading.Event()

    @staticmethod
    def _empty_suite_state():
        return {
            "running": False,
            "suite_id": "",
            "current_step": 0,
            "total_steps": 0,
            "worker_counts": [],
            "seconds_per_step": 0,
            "results": [],
            "started_at": "",
            "completed_at": "",
            "stop_requested": False,
        }

    def _log(self, message):
        if self.log_callback:
            try:
                self.log_callback(str(message))
            except Exception:
                pass

    def _new_active(self, workers, duration_seconds, label, source, suite_id=""):
        return {
            "run_id": uuid.uuid4().hex[:12],
            "suite_id": str(suite_id or ""),
            "workers": max(1, min(64, int(workers))),
            "duration_seconds": max(0, min(3600, int(duration_seconds or 0))),
            "label": str(label or "Custom")[:80],
            "source": str(source or "benchmark-lab")[:40],
            "started_at": _utc_now_iso(),
        }

    def start(self, workers=2, duration_seconds=30, label="Standard", source="benchmark-lab"):
        with self._lock:
            if self._suite.get("running"):
                raise RuntimeError("Worker Scaling Test is running. Stop it before starting a single benchmark.")
            if self.engine.running:
                self._finish_active_locked("replaced", record=True)
            workers = max(1, min(64, int(workers)))
            duration_seconds = max(0, min(3600, int(duration_seconds or 0)))
            self.engine.start(workers)
            self._active = self._new_active(workers, duration_seconds, label, source)
            self._mode = "single"
            self._log(f"Benchmark Lab: {label} run started — {workers} worker(s), {duration_seconds or 'manual'} sec.")
            return self.snapshot()

    def _build_result(self, active, stats, stop_reason, scaling_efficiency=0.0):
        avg = _safe_float(stats.get("average_hashrate") or stats.get("hashrate"))
        peak = _safe_float(stats.get("peak_hashrate"))
        stability = _safe_float(stats.get("stability_percent"), 100.0)
        elapsed = _safe_float(stats.get("elapsed_seconds"))
        result = {
            "schema": BENCHMARK_SCHEMA,
            "run_id": active.get("run_id") or uuid.uuid4().hex[:12],
            "suite_id": active.get("suite_id") or "",
            "timestamp": active.get("started_at") or _utc_now_iso(),
            "completed_at": _utc_now_iso(),
            "label": active.get("label") or "Benchmark",
            "source": active.get("source") or "benchmark-lab",
            "stop_reason": str(stop_reason or "completed"),
            "workers": _safe_int(active.get("workers"), 1),
            "planned_duration_seconds": _safe_int(active.get("duration_seconds"), 0),
            "elapsed_seconds": round(elapsed, 3),
            "total_hashes": _safe_int(stats.get("total_hashes"), 0),
            "average_hashrate": round(avg, 6),
            "peak_hashrate": round(peak, 6),
            "stability_percent": round(stability, 3),
            "score": round(benchmark_score(avg, stability), 3),
            "scaling_efficiency_percent": round(_safe_float(scaling_efficiency), 3),
            "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "") or "Unknown CPU",
            "logical_cpus": int(os.cpu_count() or 1),
            "platform": platform.platform(),
            "python": platform.python_version(),
        }
        return result

    def _finish_active_locked(self, reason="manual", record=True, scaling_efficiency=0.0):
        if not self._active:
            if self.engine.running:
                self.engine.stop()
            self._mode = "suite" if self._suite.get("running") else "idle"
            return None
        if self.engine.running:
            self.engine.stop()
        stats = self.engine.stats()
        active = dict(self._active)
        result = self._build_result(active, stats, reason, scaling_efficiency)
        if record and result["elapsed_seconds"] >= 0.5 and result["total_hashes"] > 0:
            self.history.append(result)
            self._last_result = result
        self._active = {}
        self._mode = "suite" if self._suite.get("running") else "idle"
        return result

    def stop(self, reason="manual"):
        with self._lock:
            if self._suite.get("running"):
                self._suite_stop.set()
                self._suite["stop_requested"] = True
                return self.snapshot()
            self._finish_active_locked(reason, record=True)
            self._log("Benchmark Lab: benchmark stopped.")
            return self.snapshot()

    def _maybe_complete_single_locked(self, stats):
        if self._mode != "single" or not self._active or not self.engine.running:
            return stats
        duration = _safe_int(self._active.get("duration_seconds"), 0)
        if duration > 0 and _safe_float(stats.get("elapsed_seconds")) >= duration:
            self._finish_active_locked("completed", record=True)
            return self.engine.stats()
        return stats

    def _history_summary(self, rows=None):
        rows = list(rows if rows is not None else self.history.load())
        if not rows:
            return {"count": 0, "best": None, "latest": None, "best_score": 0.0, "latest_score": 0.0, "delta_vs_best_percent": 0.0}
        latest = rows[-1]
        best = max(rows, key=lambda r: _safe_float(r.get("score")))
        best_score = _safe_float(best.get("score"))
        latest_score = _safe_float(latest.get("score"))
        delta = ((latest_score / best_score) - 1.0) * 100.0 if best_score > 0 else 0.0
        return {
            "count": len(rows),
            "best": best,
            "latest": latest,
            "best_score": best_score,
            "latest_score": latest_score,
            "delta_vs_best_percent": delta,
        }

    def snapshot(self):
        with self._lock:
            stats = self.engine.stats()
            stats = self._maybe_complete_single_locked(stats)
            active = dict(self._active)
            duration = _safe_int(active.get("duration_seconds"), 0)
            elapsed = _safe_float(stats.get("elapsed_seconds")) if active else 0.0
            remaining = max(0.0, duration - elapsed) if duration else 0.0
            progress = _clamp((elapsed / duration) * 100.0, 0.0, 100.0) if duration else 0.0
            rows = self.history.load()
            return {
                "schema": BENCHMARK_SCHEMA,
                "mode": self._mode,
                "running": bool(self.engine.running),
                "active": active,
                "stats": dict(stats),
                "duration_seconds": duration,
                "remaining_seconds": remaining,
                "progress_percent": progress,
                "score_live": benchmark_score(stats.get("average_hashrate", 0), stats.get("stability_percent", 100)),
                "history": rows[-30:][::-1],
                "history_summary": self._history_summary(rows),
                "last_result": dict(self._last_result or (rows[-1] if rows else {})),
                "recommended_worker_counts": recommended_worker_counts(),
                "cpu_count": int(os.cpu_count() or 1),
                "suite": dict(self._suite),
            }

    def clear_history(self):
        with self._lock:
            if self.engine.running or self._suite.get("running"):
                raise RuntimeError("Stop the active benchmark before clearing history.")
            self.history.clear()
            self._last_result = None
            return self.snapshot()

    def start_suite(self, worker_counts=None, seconds_per_step=8):
        with self._lock:
            if self._suite.get("running"):
                raise RuntimeError("Worker Scaling Test is already running.")
            if self.engine.running:
                self._finish_active_locked("replaced", record=True)
            counts = worker_counts or recommended_worker_counts()
            counts = sorted(set(max(1, min(64, int(x))) for x in counts))
            if not counts:
                counts = [1]
            seconds_per_step = max(3, min(120, int(seconds_per_step or 8)))
            suite_id = "suite-" + uuid.uuid4().hex[:10]
            self._suite_stop.clear()
            self._suite = {
                "running": True,
                "suite_id": suite_id,
                "current_step": 0,
                "total_steps": len(counts),
                "worker_counts": counts,
                "seconds_per_step": seconds_per_step,
                "results": [],
                "started_at": _utc_now_iso(),
                "completed_at": "",
                "stop_requested": False,
            }
            self._mode = "suite"
            self._suite_thread = threading.Thread(
                target=self._run_suite,
                args=(suite_id, counts, seconds_per_step),
                name="BMSBenchmarkScalingSuite",
                daemon=True,
            )
            self._suite_thread.start()
            self._log(f"Benchmark Lab: Worker Scaling Test started — {counts}, {seconds_per_step}s per step.")
            return self.snapshot()

    def _run_suite(self, suite_id, counts, seconds_per_step):
        baseline_workers = None
        baseline_avg = 0.0
        try:
            for index, workers in enumerate(counts, start=1):
                if self._suite_stop.is_set():
                    break
                with self._lock:
                    if not self._suite.get("running") or self._suite.get("suite_id") != suite_id:
                        break
                    self._suite["current_step"] = index
                    self.engine.start(workers)
                    self._active = self._new_active(workers, seconds_per_step, f"Scaling {workers} worker{'s' if workers != 1 else ''}", "scaling-suite", suite_id)
                deadline = time.monotonic() + seconds_per_step
                while time.monotonic() < deadline and not self._suite_stop.wait(0.25):
                    self.engine.stats()
                with self._lock:
                    if self.engine.running:
                        self.engine.stop()
                    stats = self.engine.stats()
                    avg = _safe_float(stats.get("average_hashrate") or stats.get("hashrate"))
                    if baseline_workers is None and avg > 0:
                        baseline_workers = workers
                        baseline_avg = avg
                    efficiency = 100.0
                    if baseline_avg > 0 and baseline_workers:
                        ideal = baseline_avg * (workers / baseline_workers)
                        efficiency = (avg / ideal) * 100.0 if ideal > 0 else 0.0
                    result = self._build_result(dict(self._active), stats, "completed" if not self._suite_stop.is_set() else "suite-stopped", efficiency)
                    if result["total_hashes"] > 0:
                        self.history.append(result)
                        self._last_result = result
                        self._suite["results"] = list(self._suite.get("results") or []) + [result]
                    self._active = {}
                if self._suite_stop.is_set():
                    break
        finally:
            with self._lock:
                if self.engine.running:
                    self.engine.stop()
                self._active = {}
                self._suite["running"] = False
                self._suite["completed_at"] = _utc_now_iso()
                self._suite["stop_requested"] = bool(self._suite_stop.is_set())
                self._mode = "idle"
                result_count = len(self._suite.get("results") or [])
            self._log(f"Benchmark Lab: Worker Scaling Test {'stopped' if self._suite_stop.is_set() else 'completed'} — {result_count} result(s).")

    def export(self, path: Path, fmt="json"):
        fmt = str(fmt or "json").strip().lower()
        if fmt not in {"json", "csv"}:
            raise ValueError("Benchmark export format must be json or csv.")
        rows = self.history.load()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            payload = {
                "product": "Bitcoin Miner Studio",
                "feature": "Benchmark Lab 2.0",
                "schema": BENCHMARK_SCHEMA,
                "exported_at": _utc_now_iso(),
                "summary": self._history_summary(rows),
                "history": rows,
            }
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        else:
            fields = [
                "timestamp", "completed_at", "run_id", "suite_id", "label", "stop_reason",
                "workers", "planned_duration_seconds", "elapsed_seconds", "total_hashes",
                "average_hashrate", "peak_hashrate", "stability_percent", "score",
                "scaling_efficiency_percent", "cpu", "logical_cpus", "platform", "python",
            ]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        return {"path": str(path), "rows": len(rows), "format": fmt}
