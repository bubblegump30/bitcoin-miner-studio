import json
import multiprocessing as mp
import queue
import socket
import struct
import threading
import time
from collections import deque

from bitcoin_utils import (
    DIFF1_TARGET,
    build_header_prefix,
    difficulty_to_target,
    make_extranonce2,
    sha256d,
    target_to_difficulty,
)
from connections import open_stratum_socket
from pool_powertools import normalize_endpoints, percentile


_FAILOVER_POLICIES = {
    "manual": {"failure_threshold": 999999, "max_backoff": 30, "recovery": 0},
    "conservative": {"failure_threshold": 2, "max_backoff": 30, "recovery": 900},
    "balanced": {"failure_threshold": 1, "max_backoff": 15, "recovery": 300},
    "aggressive": {"failure_threshold": 1, "max_backoff": 5, "recovery": 60},
}


def _normalize_failover_policy(value):
    key = str(value or "balanced").strip().lower()
    return key if key in _FAILOVER_POLICIES else "balanced"


class _PrimaryRecoveryRequested(Exception):
    pass


def _mine_worker(
    stop_event,
    event_queue,
    header_prefix,
    share_target,
    worker_id,
    worker_count,
    job_id,
    extranonce2,
    ntime,
):
    nonce = worker_id
    batch = 5000
    target = int(share_target)
    step = worker_count

    while not stop_event.is_set():
        done = 0
        for _ in range(batch):
            if nonce > 0xFFFFFFFF:
                try:
                    event_queue.put(("exhausted", worker_id, job_id), timeout=0.2)
                except Exception:
                    pass
                return

            header = header_prefix + struct.pack("<I", nonce)
            digest = sha256d(header)
            if int.from_bytes(digest, "little") <= target:
                try:
                    event_queue.put(
                        ("share", worker_id, job_id, extranonce2, ntime, nonce, digest.hex()),
                        timeout=0.5,
                    )
                except Exception:
                    pass
            nonce += step
            done += 1

        try:
            event_queue.put(("hashes", done), timeout=0.2)
        except Exception:
            pass


class StratumMiner:
    def __init__(self, event_callback=None):
        self.event_callback = event_callback or (lambda kind, payload: None)

        self.pool_url = ""
        self.worker_name = ""
        self.password = ""
        self.worker_count = 1
        self.suggest_difficulty = None

        self._endpoints = []
        self._active_endpoint_index = 0
        self._failover_enabled = True
        self._failover_policy = "balanced"
        self._failure_threshold = 1
        self._max_reconnect_backoff = 15
        self._primary_recovery_seconds = 300
        self._endpoint_failure_streaks = {}
        self._active_endpoint_since = 0.0
        self._last_failover_at = 0.0
        self._last_failover_reason = ""
        self._primary_recovery_attempts = 0
        self._last_primary_recovery_at = 0.0
        self._job_timeout_seconds = 120

        self._stop = threading.Event()
        self._network_thread = None
        self._event_thread = None
        self._socket = None
        self._send_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._process_lock = threading.RLock()

        self._mp_ctx = mp.get_context("spawn")
        self._worker_stop = None
        self._worker_queue = None
        self._processes = []

        self._request_id = 10
        self._pending_submits = {}

        self._connected = False
        self._authorized = False
        self._status = "Idle"
        self._difficulty = 1.0
        self._target_override = None
        self._extranonce1 = None
        self._extranonce2_size = None
        self._extranonce_counter = 0
        self._current_job = None
        self._active_job_id = None
        self._active_extranonce2 = None

        self._total_hashes = 0
        self._accepted = 0
        self._rejected = 0
        self._stale = 0
        self._submitted = 0
        self._started_at = None
        self._hash_samples = deque()
        self._recent_shares = deque(maxlen=100)
        self._peak_hashrate = 0.0
        self._last_hashrate = 0.0
        self._stopped_at = None
        self._connect_latency_ms = 0.0
        self._job_count = 0
        self._clean_job_count = 0
        self._job_update_count = 0
        self._reconnect_count = 0
        self._failover_count = 0
        self._connection_attempts = 0
        self._disconnects = 0
        self._difficulty_changes = 0
        self._difficulty_history = deque(maxlen=40)
        self._protocol_events = deque(maxlen=120)
        self._share_response_samples = deque(maxlen=200)
        self._best_share_difficulty = 0.0
        self._duplicate_prevented = 0
        self._submitted_keys = set()
        self._submitted_key_order = deque(maxlen=10000)
        self._last_job_monotonic = 0.0
        self._last_job_at = 0.0
        self._authorized_monotonic = 0.0
        self._last_share_at = 0.0
        self._last_disconnect_reason = ""

    @property
    def running(self):
        return self._network_thread is not None and self._network_thread.is_alive() and not self._stop.is_set()

    def _emit(self, kind, payload):
        try:
            self.event_callback(kind, payload)
        except Exception:
            pass

    def _set_status(self, status):
        with self._state_lock:
            self._status = status
        self._emit("status", status)

    def _log(self, text):
        self._emit("log", text)

    def _protocol(self, direction, method, detail=""):
        row = {
            "time": time.strftime("%H:%M:%S"),
            "direction": str(direction),
            "method": str(method or "response"),
            "detail": str(detail or "")[:220],
        }
        with self._state_lock:
            self._protocol_events.appendleft(row)

    def _active_endpoint(self):
        with self._state_lock:
            if not self._endpoints:
                return self.pool_url
            index = max(0, min(len(self._endpoints) - 1, self._active_endpoint_index))
            return self._endpoints[index]

    def _advance_endpoint(self, reason=""):
        with self._state_lock:
            if not self._endpoints or len(self._endpoints) <= 1 or not self._failover_enabled:
                return False
            previous = self._active_endpoint_index
            self._active_endpoint_index = (self._active_endpoint_index + 1) % len(self._endpoints)
            changed = self._active_endpoint_index != previous
            if changed:
                self._failover_count += 1
                self._last_failover_at = time.time()
                self._last_failover_reason = str(reason or "endpoint failure")[:220]
                self._active_endpoint_since = 0.0
            return changed

    def _primary_recovery_due(self):
        with self._state_lock:
            if (
                not self._failover_enabled
                or self._active_endpoint_index <= 0
                or self._primary_recovery_seconds <= 0
                or not self._connected
                or not self._authorized
                or not self._active_endpoint_since
            ):
                return False
            return time.monotonic() - self._active_endpoint_since >= self._primary_recovery_seconds

    def _prepare_primary_recovery(self):
        with self._state_lock:
            if not self._endpoints or self._active_endpoint_index <= 0:
                return False
            previous = self._active_endpoint_index
            self._active_endpoint_index = 0
            self._primary_recovery_attempts += 1
            self._last_primary_recovery_at = time.time()
            self._last_failover_reason = "scheduled primary recovery"
            self._active_endpoint_since = 0.0
            current = self._endpoints[previous]
            primary = self._endpoints[0]
        self._log(f"Smart Failover: backup {current} was stable; retrying primary {primary}.")
        self._protocol("local", "primary_recovery", f"{current} → {primary}")
        return True

    def start(
        self,
        pool_url,
        worker_name,
        password,
        worker_count=1,
        suggest_difficulty=None,
        backup_urls=None,
        failover_enabled=True,
        job_timeout_seconds=120,
        failover_policy="balanced",
        primary_recovery_seconds=None,
    ):
        if self.running:
            return
        if not str(pool_url or "").strip():
            raise ValueError("Pool URL is required.")
        if not str(worker_name or "").strip():
            raise ValueError("Worker / wallet is required.")

        endpoints = normalize_endpoints(pool_url, backup_urls or [])
        if not endpoints:
            raise ValueError("At least one valid Stratum endpoint is required.")

        self.pool_url = endpoints[0]
        self.worker_name = worker_name.strip()
        self.password = password or "x"
        self.worker_count = max(1, min(64, int(worker_count)))
        self.suggest_difficulty = None if suggest_difficulty in (None, "") else float(suggest_difficulty)
        if self.suggest_difficulty is not None and self.suggest_difficulty <= 0:
            raise ValueError("Suggested difficulty must be greater than zero.")

        self._endpoints = endpoints
        self._active_endpoint_index = 0
        policy = _normalize_failover_policy(failover_policy)
        if not bool(failover_enabled):
            policy = "manual"
        policy_cfg = _FAILOVER_POLICIES[policy]
        self._failover_policy = policy
        self._failover_enabled = bool(failover_enabled) and policy != "manual"
        self._failure_threshold = int(policy_cfg["failure_threshold"])
        self._max_reconnect_backoff = int(policy_cfg["max_backoff"])
        if primary_recovery_seconds is None:
            self._primary_recovery_seconds = int(policy_cfg["recovery"])
        else:
            self._primary_recovery_seconds = max(0, min(86400, int(primary_recovery_seconds)))
        self._endpoint_failure_streaks = {endpoint: 0 for endpoint in endpoints}
        self._active_endpoint_since = 0.0
        self._last_failover_at = 0.0
        self._last_failover_reason = ""
        self._primary_recovery_attempts = 0
        self._last_primary_recovery_at = 0.0
        self._job_timeout_seconds = max(20, min(1800, int(job_timeout_seconds)))

        self._stop.clear()
        with self._state_lock:
            self._connected = False
            self._authorized = False
            self._status = "Connecting"
            self._difficulty = 1.0
            self._target_override = None
            self._extranonce1 = None
            self._extranonce2_size = None
            self._extranonce_counter = 0
            self._current_job = None
            self._active_job_id = None
            self._active_extranonce2 = None
            self._total_hashes = 0
            self._accepted = 0
            self._rejected = 0
            self._stale = 0
            self._submitted = 0
            self._pending_submits.clear()
            self._hash_samples.clear()
            self._recent_shares.clear()
            self._peak_hashrate = 0.0
            self._last_hashrate = 0.0
            self._stopped_at = None
            self._connect_latency_ms = 0.0
            self._job_count = 0
            self._clean_job_count = 0
            self._job_update_count = 0
            self._reconnect_count = 0
            self._failover_count = 0
            self._connection_attempts = 0
            self._disconnects = 0
            self._difficulty_changes = 0
            self._difficulty_history.clear()
            self._protocol_events.clear()
            self._share_response_samples.clear()
            self._best_share_difficulty = 0.0
            self._duplicate_prevented = 0
            self._submitted_keys.clear()
            self._submitted_key_order.clear()
            self._last_job_monotonic = 0.0
            self._last_job_at = 0.0
            self._authorized_monotonic = 0.0
            self._last_share_at = 0.0
            self._last_disconnect_reason = ""
            self._started_at = time.monotonic()

        self._worker_queue = self._mp_ctx.Queue()
        self._event_thread = threading.Thread(target=self._worker_event_loop, daemon=True)
        self._network_thread = threading.Thread(target=self._network_loop, daemon=True)
        self._event_thread.start()
        self._network_thread.start()

    def stop(self):
        self._stop.set()
        self._set_status("Stopping")
        self._stop_workers()
        sock = self._socket
        self._socket = None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

        if self._network_thread and self._network_thread is not threading.current_thread():
            self._network_thread.join(timeout=2.0)
        if self._event_thread and self._event_thread is not threading.current_thread():
            self._event_thread.join(timeout=1.0)

        with self._state_lock:
            self._connected = False
            self._authorized = False
            self._active_job_id = None
            if self._started_at is not None:
                self._stopped_at = time.monotonic()
        self._set_status("Stopped" if self._started_at is not None else "Idle")

    def _network_loop(self):
        backoff = 1
        while not self._stop.is_set():
            endpoint = self._active_endpoint()
            try:
                with self._state_lock:
                    self._connection_attempts += 1
                self._connect_and_run(endpoint)
                backoff = 1
            except _PrimaryRecoveryRequested:
                if self._stop.is_set():
                    break
                self._stop_workers()
                self._set_status("Recovering primary")
                backoff = 1
                self._stop.wait(0.2)
                continue
            except Exception as exc:
                if self._stop.is_set():
                    break

                reason = str(exc)
                with self._state_lock:
                    self._reconnect_count += 1
                    self._disconnects += 1
                    self._last_disconnect_reason = reason
                    self._connected = False
                    self._authorized = False
                    self._active_endpoint_since = 0.0
                    streak = int(self._endpoint_failure_streaks.get(endpoint, 0)) + 1
                    self._endpoint_failure_streaks[endpoint] = streak
                    threshold = int(self._failure_threshold)

                should_switch = bool(self._failover_enabled and len(self._endpoints) > 1 and streak >= threshold)
                switched = self._advance_endpoint(reason) if should_switch else False
                if switched:
                    next_endpoint = self._active_endpoint()
                    with self._state_lock:
                        self._endpoint_failure_streaks[endpoint] = 0
                    self._log(
                        f"Smart Failover ({self._failover_policy}): {endpoint} failed — {reason}. "
                        f"Switching to {next_endpoint}."
                    )
                    self._protocol("local", "failover", f"{endpoint} → {next_endpoint}")
                    self._set_status("Failing over")
                    backoff = 1
                else:
                    if self._failover_enabled and len(self._endpoints) > 1 and threshold > 1:
                        self._log(
                            f"Pool endpoint error ({streak}/{threshold} before failover): {reason}"
                        )
                    else:
                        self._log(f"Pool connection error: {reason}")
                    self._set_status(f"Reconnecting in {backoff}s")

                self._stop_workers()
                self._stop.wait(backoff)
                if not switched:
                    backoff = min(self._max_reconnect_backoff, backoff * 2)

        self._stop_workers()
        with self._state_lock:
            self._connected = False
            self._authorized = False

    def _connect_and_run(self, endpoint):
        connect_started = time.perf_counter()
        sock, host, port, secure = open_stratum_socket(endpoint, timeout=8)
        connect_latency_ms = (time.perf_counter() - connect_started) * 1000.0
        with self._state_lock:
            self._connect_latency_ms = connect_latency_ms
            self._active_endpoint_since = time.monotonic()
            self._endpoint_failure_streaks[endpoint] = 0
            self._last_job_monotonic = 0.0
            self._last_job_at = 0.0
            self._authorized_monotonic = 0.0
        sock.settimeout(1.0)
        self._socket = sock
        self._log(
            f"Connected to {host}:{port} via {'TLS' if secure else 'TCP'} "
            f"in {connect_latency_ms:.1f} ms."
        )
        self._protocol("in", "connect", f"{endpoint} · {connect_latency_ms:.1f} ms")
        self._set_status("Subscribing")

        with self._state_lock:
            self._connected = True
            self._authorized = False
            self._extranonce1 = None
            self._extranonce2_size = None

        self._send({
            "id": 1,
            "method": "mining.subscribe",
            "params": ["BitcoinMinerStudio/0.7.0"],
        })
        if self.suggest_difficulty is not None:
            self._send({
                "id": 3,
                "method": "mining.suggest_difficulty",
                "params": [self.suggest_difficulty],
            })
            self._log(
                f"Requested share difficulty {self.suggest_difficulty:g}. "
                "The pool may ignore or reject this optional Stratum extension."
            )

        self._send({
            "id": 2,
            "method": "mining.authorize",
            "params": [self.worker_name, self.password],
        })

        buffer = b""
        try:
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    now_mono = time.monotonic()
                    with self._state_lock:
                        authorized = self._authorized
                        last_job = self._last_job_monotonic
                        authorized_at = self._authorized_monotonic
                        timeout_seconds = self._job_timeout_seconds
                    reference = last_job or authorized_at
                    if authorized and reference and now_mono - reference > timeout_seconds:
                        raise TimeoutError(
                            f"No mining.notify work received for {timeout_seconds} seconds."
                        )
                    if self._primary_recovery_due() and self._prepare_primary_recovery():
                        raise _PrimaryRecoveryRequested()
                    continue
                if not chunk:
                    raise ConnectionError("Pool closed the connection.")
                if self._primary_recovery_due() and self._prepare_primary_recovery():
                    raise _PrimaryRecoveryRequested()
                buffer += chunk
                if len(buffer) > 2_000_000:
                    raise ConnectionError("Pool sent an oversized response buffer.")

                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        msg = json.loads(raw.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        self._log(f"Ignored invalid JSON from pool: {raw[:180]!r}")
                        continue
                    self._handle_message(msg)
        finally:
            if self._socket is sock:
                self._socket = None
            try:
                sock.close()
            except Exception:
                pass

    def _send(self, payload):
        sock = self._socket
        if not sock:
            raise ConnectionError("Not connected to a pool.")
        raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        method = payload.get("method") if isinstance(payload, dict) else ""
        if method:
            detail = ""
            if method == "mining.authorize":
                detail = f"worker={self.worker_name}"
            elif method == "mining.submit":
                params = payload.get("params") or []
                detail = f"job={params[1] if len(params)>1 else ''}"
            self._protocol("out", method, detail)
        with self._send_lock:
            sock.sendall(raw)

    def _handle_message(self, msg):
        method = msg.get("method")
        msg_id = msg.get("id")

        if method:
            self._protocol("in", method)
            params = msg.get("params") or []

            if method == "mining.set_difficulty":
                if params:
                    difficulty = float(params[0])
                    if difficulty <= 0:
                        raise ValueError("Pool sent an invalid difficulty.")
                    with self._state_lock:
                        changed = difficulty != self._difficulty
                        self._difficulty = difficulty
                        self._target_override = None
                        if changed:
                            self._difficulty_changes += 1
                            self._difficulty_history.appendleft({
                                "time": time.strftime("%H:%M:%S"),
                                "difficulty": difficulty,
                                "source": "mining.set_difficulty",
                            })
                    self._emit("difficulty", difficulty)
                    self._log(f"Pool difficulty set to {difficulty:g}.")
                return

            if method == "mining.set_target":
                if params:
                    target = int(str(params[0]), 16)
                    if target <= 0:
                        raise ValueError("Pool sent an invalid share target.")
                    with self._state_lock:
                        new_difficulty = target_to_difficulty(target)
                        changed = new_difficulty != self._difficulty
                        self._target_override = target
                        self._difficulty = new_difficulty
                        if changed:
                            self._difficulty_changes += 1
                            self._difficulty_history.appendleft({
                                "time": time.strftime("%H:%M:%S"),
                                "difficulty": new_difficulty,
                                "source": "mining.set_target",
                            })
                    self._emit("difficulty", self._difficulty)
                    self._log("Pool supplied an explicit share target.")
                return

            if method == "mining.set_extranonce":
                if len(params) >= 2:
                    with self._state_lock:
                        self._extranonce1 = str(params[0])
                        self._extranonce2_size = int(params[1])
                    self._log("Pool updated extranonce parameters.")
                    if self._current_job:
                        self._activate_job(self._current_job)
                return

            if method == "mining.notify":
                self._handle_notify(params)
                return

            if method == "client.show_message":
                if params:
                    self._log(f"Pool message: {params[0]}")
                return

            if method == "client.reconnect":
                self._log("Pool requested client.reconnect. Reconnecting to the configured endpoint.")
                sock = self._socket
                if sock:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                return

            self._log(f"Unhandled pool method: {method}")
            return

        if msg_id == 1:
            self._protocol("in", "mining.subscribe.response")
            if msg.get("error"):
                raise RuntimeError(f"Subscription rejected: {msg['error']}")
            result = msg.get("result")
            if not isinstance(result, list) or len(result) < 3:
                raise RuntimeError("Pool returned an invalid mining.subscribe result.")
            with self._state_lock:
                self._extranonce1 = str(result[1])
                self._extranonce2_size = int(result[2])
            self._log(
                f"Subscribed. extranonce1={self._extranonce1}, "
                f"extranonce2_size={self._extranonce2_size}."
            )
            self._maybe_activate_pending_job()
            return

        if msg_id == 3:
            if msg.get("error"):
                self._log(
                    "Pool did not accept mining.suggest_difficulty: "
                    + json.dumps(msg.get("error"), ensure_ascii=False)
                )
            else:
                self._log("Pool acknowledged mining.suggest_difficulty.")
            return

        if msg_id == 2:
            if msg.get("result") is not True or msg.get("error"):
                raise RuntimeError(f"Worker authorization failed: {msg.get('error')}")
            with self._state_lock:
                self._authorized = True
                self._authorized_monotonic = time.monotonic()
            self._log(f"Worker authorized: {self.worker_name}")
            self._set_status("Waiting for job")
            self._maybe_activate_pending_job()
            return

        if msg_id in self._pending_submits:
            meta = self._pending_submits.pop(msg_id, None)
            ok = msg.get("result") is True and not msg.get("error")
            response_ms = max(0.0, (time.time() - meta.get("submitted_at", time.time())) * 1000.0)
            with self._state_lock:
                self._share_response_samples.append(response_ms)
                self._last_share_at = time.time()
            if ok:
                with self._state_lock:
                    self._accepted += 1
                    row = {
                        "time": time.strftime("%H:%M:%S"),
                        "result": "accepted",
                        "job_id": meta["job_id"],
                        "nonce": meta["nonce"],
                        "response_ms": response_ms,
                        "share_difficulty": float(meta.get("share_difficulty") or 0),
                    }
                    self._recent_shares.appendleft(row)
                self._emit("share", {"result": "accepted", "meta": meta, "response_ms": response_ms})
                self._log(
                    f"Share accepted — job {meta['job_id']} nonce {meta['nonce']} "
                    f"({response_ms:.1f} ms)."
                )
            else:
                error_text = json.dumps(msg.get("error"), ensure_ascii=False)
                is_stale = any(word in error_text.lower() for word in (
                    "stale", "job not found", "job not found", "unknown-work",
                    "unknown job", "obsolete",
                ))
                result = "stale" if is_stale else "rejected"
                with self._state_lock:
                    if is_stale:
                        self._stale += 1
                    else:
                        self._rejected += 1
                    row = {
                        "time": time.strftime("%H:%M:%S"),
                        "result": result,
                        "job_id": meta["job_id"],
                        "nonce": meta["nonce"],
                        "response_ms": response_ms,
                        "share_difficulty": float(meta.get("share_difficulty") or 0),
                    }
                    self._recent_shares.appendleft(row)
                self._emit(
                    "share",
                    {
                        "result": result,
                        "meta": meta,
                        "error": msg.get("error"),
                        "response_ms": response_ms,
                    },
                )
                self._log(f"Share {result} — {error_text} ({response_ms:.1f} ms).")
            return

    def _handle_notify(self, params):
        if len(params) < 9:
            raise ValueError("mining.notify did not contain 9 parameters.")
        job = {
            "job_id": str(params[0]),
            "prevhash": str(params[1]),
            "coinb1": str(params[2]),
            "coinb2": str(params[3]),
            "merkle_branch": list(params[4]),
            "version": str(params[5]),
            "nbits": str(params[6]),
            "ntime": str(params[7]),
            "clean_jobs": bool(params[8]),
        }
        with self._state_lock:
            self._current_job = job
            self._job_count += 1
            if job["clean_jobs"]:
                self._clean_job_count += 1
            else:
                self._job_update_count += 1
            self._last_job_monotonic = time.monotonic()
            self._last_job_at = time.time()
        self._emit("job", job["job_id"])
        self._log(
            f"New mining job {job['job_id']} "
            f"({'clean' if job['clean_jobs'] else 'update'})."
        )
        self._maybe_activate_pending_job()

    def _maybe_activate_pending_job(self):
        with self._state_lock:
            ready = (
                self._authorized
                and self._extranonce1 is not None
                and self._extranonce2_size is not None
                and self._current_job is not None
            )
            job = self._current_job
        if ready:
            self._activate_job(job)

    def _activate_job(self, job):
        with self._process_lock:
            self._stop_workers_locked()

            with self._state_lock:
                self._extranonce_counter += 1
                ex2 = make_extranonce2(self._extranonce_counter, self._extranonce2_size)
                target = (
                    self._target_override
                    if self._target_override is not None
                    else difficulty_to_target(self._difficulty)
                )
                ex1 = self._extranonce1
                job_id = job["job_id"]

            prefix, merkle = build_header_prefix(job, ex1, ex2)

            self._worker_stop = self._mp_ctx.Event()
            self._processes = []
            for worker_id in range(self.worker_count):
                p = self._mp_ctx.Process(
                    target=_mine_worker,
                    args=(
                        self._worker_stop,
                        self._worker_queue,
                        prefix,
                        target,
                        worker_id,
                        self.worker_count,
                        job_id,
                        ex2,
                        job["ntime"],
                    ),
                    daemon=True,
                )
                p.start()
                self._processes.append(p)

            with self._state_lock:
                self._active_job_id = job_id
                self._active_extranonce2 = ex2

            self._set_status("Mining")
            self._log(
                f"Mining job {job_id} with {self.worker_count} process(es); "
                f"extranonce2={ex2}; merkle={merkle[::-1].hex()[:16]}…"
            )

    def _stop_workers(self):
        with self._process_lock:
            self._stop_workers_locked()

    def _stop_workers_locked(self):
        if self._worker_stop:
            self._worker_stop.set()
        procs = self._processes
        for p in procs:
            p.join(timeout=0.35)
        for p in procs:
            if p.is_alive():
                p.terminate()
        for p in procs:
            if p.is_alive():
                p.join(timeout=0.2)
        self._processes = []
        self._worker_stop = None

    def _worker_event_loop(self):
        exhausted = set()
        while not self._stop.is_set():
            try:
                event = self._worker_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                break

            kind = event[0]
            if kind == "hashes":
                count = int(event[1])
                now = time.monotonic()
                with self._state_lock:
                    self._total_hashes += count
                    self._hash_samples.append((now, count))
                    cutoff = now - 5.0
                    while self._hash_samples and self._hash_samples[0][0] < cutoff:
                        self._hash_samples.popleft()

            elif kind == "share":
                _, worker_id, job_id, ex2, ntime, nonce, digest_hex = event
                with self._state_lock:
                    active = job_id == self._active_job_id
                if active and not self._stop.is_set():
                    self._submit_share(job_id, ex2, ntime, nonce, digest_hex)

            elif kind == "exhausted":
                _, worker_id, job_id = event
                with self._state_lock:
                    active = job_id == self._active_job_id
                    current_job = self._current_job
                if active:
                    exhausted.add(worker_id)
                    if len(exhausted) >= self.worker_count and current_job:
                        exhausted.clear()
                        self._log("Nonce space exhausted; rotating extranonce2.")
                        try:
                            self._activate_job(current_job)
                        except Exception as exc:
                            self._log(f"Could not rotate extranonce2: {exc}")

    def _submit_share(self, job_id, extranonce2, ntime, nonce, digest_hex):
        with self._state_lock:
            nonce_hex = f"{nonce:08x}"
            key = (str(job_id), str(extranonce2), str(ntime), nonce_hex)
            if key in self._submitted_keys:
                self._duplicate_prevented += 1
                self._log(
                    f"Duplicate share prevented locally — job {job_id} nonce {nonce_hex}."
                )
                return

            self._submitted_keys.add(key)
            self._submitted_key_order.append(key)
            if len(self._submitted_key_order) >= self._submitted_key_order.maxlen:
                live = set(self._submitted_key_order)
                self._submitted_keys.intersection_update(live)

            try:
                hash_int = int.from_bytes(bytes.fromhex(digest_hex), "little")
                share_difficulty = target_to_difficulty(hash_int) if hash_int > 0 else float("inf")
            except Exception:
                share_difficulty = 0.0

            self._best_share_difficulty = max(
                float(self._best_share_difficulty or 0),
                float(share_difficulty if share_difficulty != float("inf") else 1e300),
            )

            self._request_id += 1
            req_id = self._request_id
            meta = {
                "job_id": job_id,
                "extranonce2": extranonce2,
                "ntime": ntime,
                "nonce": nonce_hex,
                "hash": digest_hex,
                "share_difficulty": share_difficulty,
                "submitted_at": time.time(),
            }
            self._pending_submits[req_id] = meta
            self._submitted += 1

        try:
            self._send({
                "id": req_id,
                "method": "mining.submit",
                "params": [
                    self.worker_name,
                    job_id,
                    extranonce2,
                    ntime,
                    nonce_hex,
                ],
            })
            self._emit("share", {"result": "submitted", "meta": meta})
        except Exception:
            with self._state_lock:
                self._pending_submits.pop(req_id, None)
            raise

    def reset_stats(self):
        """Clear retained session counters while the miner is stopped."""
        if self.running:
            raise RuntimeError("Stop mining before resetting session statistics.")
        with self._state_lock:
            self._total_hashes = 0
            self._accepted = 0
            self._rejected = 0
            self._stale = 0
            self._submitted = 0
            self._pending_submits.clear()
            self._hash_samples.clear()
            self._recent_shares.clear()
            self._peak_hashrate = 0.0
            self._last_hashrate = 0.0
            self._started_at = None
            self._stopped_at = None
            self._connect_latency_ms = 0.0
            self._job_count = 0
            self._clean_job_count = 0
            self._job_update_count = 0
            self._reconnect_count = 0
            self._failover_count = 0
            self._connection_attempts = 0
            self._disconnects = 0
            self._difficulty_changes = 0
            self._difficulty_history.clear()
            self._protocol_events.clear()
            self._share_response_samples.clear()
            self._best_share_difficulty = 0.0
            self._duplicate_prevented = 0
            self._submitted_keys.clear()
            self._submitted_key_order.clear()
            self._last_job_monotonic = 0.0
            self._last_job_at = 0.0
            self._authorized_monotonic = 0.0
            self._last_share_at = 0.0
            self._last_disconnect_reason = ""
            self._endpoint_failure_streaks = {endpoint: 0 for endpoint in self._endpoints}
            self._active_endpoint_since = 0.0
            self._last_failover_at = 0.0
            self._last_failover_reason = ""
            self._primary_recovery_attempts = 0
            self._last_primary_recovery_at = 0.0
            self._difficulty = 1.0
            self._status = "Idle"

    def stats(self):
        now = time.monotonic()
        with self._state_lock:
            cutoff = now - 5.0
            while self._hash_samples and self._hash_samples[0][0] < cutoff:
                self._hash_samples.popleft()

            current_hashrate = 0.0
            if self._hash_samples:
                span = max(0.5, now - self._hash_samples[0][0])
                current_hashrate = sum(c for _, c in self._hash_samples) / span
                self._last_hashrate = current_hashrate
                self._peak_hashrate = max(self._peak_hashrate, current_hashrate)

            if self._started_at is None:
                uptime = 0.0
            else:
                endpoint = self._stopped_at if self._stopped_at is not None else now
                uptime = max(0.0, endpoint - self._started_at)

            average_hashrate = (self._total_hashes / uptime) if uptime > 0 else 0.0

            # Keep the completed session meaningful on screen after Stop.
            display_hashrate = current_hashrate if self.running else average_hashrate

            expected_share_seconds = 0.0
            basis_hashrate = current_hashrate if current_hashrate > 0 else average_hashrate
            if basis_hashrate > 0 and self._difficulty > 0:
                expected_share_seconds = (float(self._difficulty) * (2 ** 32)) / basis_hashrate

            decided = self._accepted + self._rejected + self._stale
            acceptance_rate = (self._accepted / decided * 100.0) if decided else 0.0

            responses = list(self._share_response_samples)
            response_avg = (sum(responses) / len(responses)) if responses else 0.0
            response_p95 = percentile(responses, 0.95) if responses else 0.0
            job_age_seconds = (
                max(0.0, now - self._last_job_monotonic)
                if self._last_job_monotonic
                else 0.0
            )
            active_endpoint = (
                self._endpoints[self._active_endpoint_index]
                if self._endpoints and 0 <= self._active_endpoint_index < len(self._endpoints)
                else self.pool_url
            )

            return {
                "hashrate": display_hashrate,
                "current_hashrate": current_hashrate,
                "average_hashrate": average_hashrate,
                "peak_hashrate": self._peak_hashrate,
                "total_hashes": self._total_hashes,
                "expected_share_seconds": expected_share_seconds,
                "accepted": self._accepted,
                "rejected": self._rejected,
                "stale": self._stale,
                "submitted": self._submitted,
                "acceptance_rate": acceptance_rate,
                "difficulty": self._difficulty,
                "status": self._status,
                "connected": self._connected,
                "authorized": self._authorized,
                "job_id": self._active_job_id or (self._current_job or {}).get("job_id", ""),
                "workers": len([p for p in self._processes if p.is_alive()]),
                "uptime": uptime,
                "connect_latency_ms": self._connect_latency_ms,
                "job_count": self._job_count,
                "clean_job_count": self._clean_job_count,
                "job_update_count": self._job_update_count,
                "endpoint": self.pool_url,
                "active_endpoint": active_endpoint,
                "active_endpoint_index": self._active_endpoint_index,
                "endpoint_count": len(self._endpoints),
                "endpoints": list(self._endpoints),
                "failover_enabled": self._failover_enabled,
                "failover_policy": self._failover_policy,
                "failure_threshold": self._failure_threshold,
                "primary_recovery_seconds": self._primary_recovery_seconds,
                "primary_recovery_attempts": self._primary_recovery_attempts,
                "last_primary_recovery_at": self._last_primary_recovery_at,
                "last_failover_at": self._last_failover_at,
                "last_failover_reason": self._last_failover_reason,
                "active_endpoint_uptime_seconds": (
                    max(0.0, now - self._active_endpoint_since)
                    if self._active_endpoint_since else 0.0
                ),
                "endpoint_failure_streaks": dict(self._endpoint_failure_streaks),
                "failover_count": self._failover_count,
                "reconnect_count": self._reconnect_count,
                "connection_attempts": self._connection_attempts,
                "disconnects": self._disconnects,
                "last_disconnect_reason": self._last_disconnect_reason,
                "job_timeout_seconds": self._job_timeout_seconds,
                "job_age_seconds": job_age_seconds,
                "last_job_at": self._last_job_at,
                "last_share_at": self._last_share_at,
                "difficulty_changes": self._difficulty_changes,
                "difficulty_history": list(self._difficulty_history),
                "protocol_events": list(self._protocol_events),
                "share_response_avg_ms": response_avg,
                "share_response_p95_ms": response_p95,
                "best_share_difficulty": self._best_share_difficulty,
                "duplicate_prevented": self._duplicate_prevented,
                "extranonce1": self._extranonce1 or "",
                "extranonce2_size": int(self._extranonce2_size or 0),
                "session_started": self._started_at is not None,
                "running": self.running,
                "recent_shares": list(self._recent_shares),
            }
