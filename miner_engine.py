import hashlib
import math
import multiprocessing as mp
import os
import queue
import struct
import time


def _sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _worker(stop_event, count_queue, worker_id):
    seed = hashlib.sha256(f"BitcoinMinerStudio:{worker_id}:{os.getpid()}".encode()).digest()
    prefix = (seed * 3)[:76]
    nonce = worker_id * 100_000_000
    batch = 25_000
    local_count = 0

    while not stop_event.is_set():
        for _ in range(batch):
            header = prefix + struct.pack("<I", nonce & 0xFFFFFFFF)
            _sha256d(header)
            nonce += 1
        local_count += batch
        try:
            count_queue.put_nowait(local_count)
            local_count = 0
        except queue.Full:
            pass


class BenchmarkEngine:
    """Multiprocess SHA-256d benchmark engine with Benchmark Lab 2.0 telemetry."""

    def __init__(self):
        self.processes = []
        self._mp_ctx = mp.get_context("spawn")
        self.stop_event = None
        self.count_queue = None
        self.total_hashes = 0
        self.started = None
        self.stopped = None
        self._running = False
        self.current_hashrate = 0.0
        self.peak_hashrate = 0.0
        self._last_sample_hashes = 0
        self._last_sample_at = None
        self._rate_samples = []

    @property
    def running(self):
        return self._running

    def start(self, workers=1):
        if self._running:
            return
        workers = max(1, min(64, int(workers)))
        self.stop_event = self._mp_ctx.Event()
        self.count_queue = self._mp_ctx.Queue(maxsize=max(64, workers * 8))
        self.total_hashes = 0
        self.started = time.perf_counter()
        self.stopped = None
        self.current_hashrate = 0.0
        self.peak_hashrate = 0.0
        self._last_sample_hashes = 0
        self._last_sample_at = self.started
        self._rate_samples = []
        self.processes = []
        for i in range(workers):
            p = self._mp_ctx.Process(target=_worker, args=(self.stop_event, self.count_queue, i), daemon=True)
            p.start()
            self.processes.append(p)
        self._running = True

    def _drain(self):
        if not self.count_queue:
            return
        while True:
            try:
                self.total_hashes += self.count_queue.get_nowait()
            except queue.Empty:
                break
            except (EOFError, OSError):
                break

    def _sample(self, now):
        if self._last_sample_at is None:
            self._last_sample_at = now
            self._last_sample_hashes = self.total_hashes
            return
        dt = now - self._last_sample_at
        if dt < 0.20:
            return
        delta = max(0, self.total_hashes - self._last_sample_hashes)
        rate = delta / max(0.001, dt)
        self.current_hashrate = rate
        if rate > 0:
            self.peak_hashrate = max(self.peak_hashrate, rate)
            self._rate_samples.append(rate)
            if len(self._rate_samples) > 120:
                self._rate_samples = self._rate_samples[-120:]
        self._last_sample_at = now
        self._last_sample_hashes = self.total_hashes

    def _stability(self):
        samples = [x for x in self._rate_samples[-30:] if x > 0]
        if len(samples) < 2:
            return 100.0
        mean = sum(samples) / len(samples)
        if mean <= 0:
            return 0.0
        variance = sum((x - mean) ** 2 for x in samples) / len(samples)
        cv = math.sqrt(variance) / mean
        return max(0.0, min(100.0, 100.0 - cv * 100.0))

    def stats(self):
        self._drain()
        if not self.started:
            return {
                "hashrate": 0.0,
                "current_hashrate": 0.0,
                "average_hashrate": 0.0,
                "peak_hashrate": 0.0,
                "total_hashes": self.total_hashes,
                "elapsed_seconds": 0.0,
                "stability_percent": 100.0,
                "samples": 0,
                "workers": 0,
            }
        now = time.perf_counter() if self._running else (self.stopped or time.perf_counter())
        self._sample(now)
        elapsed = max(0.001, now - self.started)
        average = self.total_hashes / elapsed
        # During very short startup windows, average is more representative than
        # an empty instantaneous sample.
        current = self.current_hashrate if self.current_hashrate > 0 else average
        peak = max(self.peak_hashrate, current, average)
        return {
            "hashrate": average,
            "current_hashrate": current,
            "average_hashrate": average,
            "peak_hashrate": peak,
            "total_hashes": self.total_hashes,
            "elapsed_seconds": elapsed,
            "stability_percent": self._stability(),
            "samples": len(self._rate_samples),
            "workers": len(self.processes) if self._running else 0,
        }

    def stop(self):
        if not self._running:
            return
        if self.stop_event:
            self.stop_event.set()
        for p in self.processes:
            p.join(timeout=1.0)
            if p.is_alive():
                p.terminate()
                p.join(timeout=0.5)
        self._drain()
        self.stopped = time.perf_counter()
        self._sample(self.stopped)
        self.processes = []
        self._running = False
