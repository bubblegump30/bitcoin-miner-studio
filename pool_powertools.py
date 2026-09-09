"""Bitcoin Miner Studio v0.7.0 — Pool & Stratum PowerTools 2.0.

Read-only diagnostic helpers and pool-session scoring. Credentials are never
included in diagnostic output. Endpoint diagnostics run in a background worker
through PoolDiagnosticsController so the WebView remains responsive.
"""

import json
import socket
import threading
import time
from collections import deque

from connections import open_stratum_socket, parse_stratum_url


MAX_ENDPOINTS = 4


def normalize_endpoints(primary, backups=None):
    values = [str(primary or "").strip()] + [
        str(x or "").strip() for x in list(backups or [])
    ]
    out = []
    seen = set()
    for value in values:
        if not value:
            continue
        host, port, secure = parse_stratum_url(value)
        scheme = "stratum+ssl" if secure else "stratum+tcp"
        normalized = f"{scheme}://{host}:{int(port)}"
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
        if len(out) >= MAX_ENDPOINTS:
            break
    return out


def percentile(values, p):
    vals = sorted(float(x) for x in values if x is not None)
    if not vals:
        return 0.0
    if len(vals) == 1:
        return vals[0]
    p = max(0.0, min(1.0, float(p)))
    pos = (len(vals) - 1) * p
    lo = int(pos)
    hi = min(len(vals) - 1, lo + 1)
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def pool_health_score(stats):
    """0..100 pool-session health score. Idle sessions return 0."""
    stats = dict(stats or {})
    if not stats.get("session_started"):
        return 0

    score = 100.0
    active = bool(stats.get("running"))
    if active and not stats.get("connected"):
        score -= 35
    if active and stats.get("connected") and not stats.get("authorized"):
        score -= 25

    decided = (
        int(stats.get("accepted") or 0)
        + int(stats.get("rejected") or 0)
        + int(stats.get("stale") or 0)
    )
    if decided:
        bad_ratio = (
            int(stats.get("rejected") or 0) + int(stats.get("stale") or 0)
        ) / decided
        score -= min(45.0, bad_ratio * 100.0)

    p95 = float(stats.get("share_response_p95_ms") or 0)
    if p95 > 2500:
        score -= 20
    elif p95 > 1200:
        score -= 12
    elif p95 > 600:
        score -= 6

    connect = float(stats.get("connect_latency_ms") or 0)
    if connect > 2500:
        score -= 12
    elif connect > 1000:
        score -= 7
    elif connect > 500:
        score -= 3

    job_age = float(stats.get("job_age_seconds") or 0)
    timeout = float(stats.get("job_timeout_seconds") or 0)
    if active and timeout > 0 and job_age > timeout * 0.75:
        score -= 15

    score -= min(15.0, float(stats.get("failover_count") or 0) * 3.0)
    score -= min(10.0, float(stats.get("disconnects") or 0) * 1.5)
    return max(0, min(100, round(score)))


def diagnostic_score(result):
    result = dict(result or {})
    if result.get("error"):
        stage = str(result.get("failed_stage") or "")
        return {"dns": 0, "tcp": 15, "tls": 25, "subscribe": 45, "authorize": 60, "job": 75}.get(stage, 0)
    score = 100.0
    connect = float(result.get("connect_ms") or 0)
    if connect > 2500:
        score -= 25
    elif connect > 1000:
        score -= 15
    elif connect > 500:
        score -= 8
    if result.get("worker_supplied") and not result.get("authorized"):
        score -= 35
    if not result.get("subscribed"):
        score -= 50
    if not result.get("job_received"):
        score -= 8
    return max(0, min(100, round(score)))


def probe_stratum_endpoint(endpoint, worker="", password="x", timeout=5.0):
    """Perform DNS → TCP/TLS → subscribe → authorize → first-job diagnostics."""
    started = time.perf_counter()
    host = ""
    port = 0
    secure = False
    result = {
        "endpoint": str(endpoint or ""),
        "host": "",
        "port": 0,
        "transport": "",
        "resolved_ips": [],
        "dns_ms": 0.0,
        "connect_ms": 0.0,
        "subscribe_ms": 0.0,
        "authorize_ms": 0.0,
        "first_job_ms": 0.0,
        "subscribed": False,
        "authorized": False,
        "worker_supplied": bool(str(worker or "").strip()),
        "job_received": False,
        "difficulty": None,
        "extranonce1": "",
        "extranonce2_size": 0,
        "server_methods": [],
        "tls_version": "",
        "tls_cipher": "",
        "score": 0,
        "error": "",
        "failed_stage": "",
    }

    try:
        host, port, secure = parse_stratum_url(endpoint)
        result["host"] = host
        result["port"] = int(port)
        result["transport"] = "TLS" if secure else "TCP"
    except Exception as exc:
        result["error"] = str(exc)
        result["failed_stage"] = "url"
        result["score"] = diagnostic_score(result)
        return result

    dns_started = time.perf_counter()
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = []
        for item in infos:
            ip = str(item[4][0])
            if ip not in ips:
                ips.append(ip)
        result["resolved_ips"] = ips[:6]
        result["dns_ms"] = (time.perf_counter() - dns_started) * 1000.0
    except Exception as exc:
        result["dns_ms"] = (time.perf_counter() - dns_started) * 1000.0
        result["error"] = f"DNS resolution failed: {exc}"
        result["failed_stage"] = "dns"
        result["score"] = diagnostic_score(result)
        return result

    connect_started = time.perf_counter()
    sock = None
    try:
        sock, _, _, _ = open_stratum_socket(endpoint, timeout=timeout)
        result["connect_ms"] = (time.perf_counter() - connect_started) * 1000.0
        if secure:
            try:
                result["tls_version"] = str(sock.version() or "")
                cipher = sock.cipher()
                result["tls_cipher"] = str(cipher[0] if cipher else "")
            except Exception:
                pass
        sock.settimeout(0.5)
    except Exception as exc:
        result["connect_ms"] = (time.perf_counter() - connect_started) * 1000.0
        result["error"] = f"{'TLS' if secure else 'TCP'} connection failed: {exc}"
        result["failed_stage"] = "tls" if secure else "tcp"
        result["score"] = diagnostic_score(result)
        return result

    subscribe_sent = time.perf_counter()
    auth_sent = None
    try:
        def send(payload):
            sock.sendall(
                (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
            )

        send({
            "id": 701,
            "method": "mining.subscribe",
            "params": ["BitcoinMinerStudio/0.7.0-Diagnostics"],
        })
        if str(worker or "").strip():
            auth_sent = time.perf_counter()
            send({
                "id": 702,
                "method": "mining.authorize",
                "params": [str(worker).strip(), password or "x"],
            })

        deadline = time.monotonic() + max(2.0, float(timeout))
        buffer = b""
        methods = []
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            buffer += chunk
            if len(buffer) > 1_000_000:
                raise RuntimeError("Pool diagnostic response exceeded 1 MB.")

            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8", errors="replace"))
                except Exception:
                    continue

                msg_id = msg.get("id")
                method = str(msg.get("method") or "")
                params = msg.get("params") or []

                if method:
                    if method not in methods:
                        methods.append(method)
                    if method == "mining.set_difficulty" and params:
                        try:
                            result["difficulty"] = float(params[0])
                        except Exception:
                            pass
                    elif method == "mining.notify":
                        result["job_received"] = True
                        if not result["first_job_ms"]:
                            result["first_job_ms"] = (
                                time.perf_counter() - subscribe_sent
                            ) * 1000.0

                if msg_id == 701:
                    if msg.get("error"):
                        result["error"] = f"Subscription rejected: {msg.get('error')}"
                        result["failed_stage"] = "subscribe"
                        break
                    sub = msg.get("result")
                    if isinstance(sub, list) and len(sub) >= 3:
                        result["subscribed"] = True
                        result["subscribe_ms"] = (
                            time.perf_counter() - subscribe_sent
                        ) * 1000.0
                        result["extranonce1"] = str(sub[1] or "")
                        try:
                            result["extranonce2_size"] = int(sub[2])
                        except Exception:
                            pass
                    else:
                        result["error"] = "Invalid mining.subscribe result."
                        result["failed_stage"] = "subscribe"
                        break

                if msg_id == 702:
                    result["authorize_ms"] = (
                        time.perf_counter() - (auth_sent or subscribe_sent)
                    ) * 1000.0
                    if msg.get("result") is True and not msg.get("error"):
                        result["authorized"] = True
                    else:
                        result["error"] = f"Worker authorization failed: {msg.get('error')}"
                        result["failed_stage"] = "authorize"
                        break

            if result["error"]:
                break

            auth_ok = result["authorized"] or not result["worker_supplied"]
            if result["subscribed"] and auth_ok and result["job_received"]:
                break

        result["server_methods"] = methods[:20]
        if not result["subscribed"] and not result["error"]:
            result["error"] = "No successful mining.subscribe response before timeout."
            result["failed_stage"] = "subscribe"
        elif result["worker_supplied"] and not result["authorized"] and not result["error"]:
            result["error"] = "No successful mining.authorize response before timeout."
            result["failed_stage"] = "authorize"

    except Exception as exc:
        if not result["error"]:
            result["error"] = str(exc)
            result["failed_stage"] = "protocol"
    finally:
        try:
            sock.close()
        except Exception:
            pass

    result["elapsed_ms"] = (time.perf_counter() - started) * 1000.0
    result["score"] = diagnostic_score(result)
    return result


def diagnostic_report(state):
    state = dict(state or {})
    lines = [
        "POOL & STRATUM POWERTOOLS 2.0 — ENDPOINT DIAGNOSTICS",
        "",
        f"Status: {state.get('status', 'Idle')}",
    ]
    for index, row in enumerate(state.get("results") or [], 1):
        lines.extend([
            "",
            f"[{index}] {row.get('endpoint', '')}",
            f"  Score: {row.get('score', 0)}/100",
            f"  Transport: {row.get('transport') or '—'}",
            f"  DNS: {float(row.get('dns_ms') or 0):.1f} ms",
            f"  Connect: {float(row.get('connect_ms') or 0):.1f} ms",
            f"  Subscribe: {'OK' if row.get('subscribed') else 'FAIL'}"
                + (f" ({float(row.get('subscribe_ms') or 0):.1f} ms)" if row.get('subscribe_ms') else ""),
            f"  Authorize: {'OK' if row.get('authorized') else ('SKIPPED' if not row.get('worker_supplied') else 'FAIL')}",
            f"  First job: {'YES' if row.get('job_received') else 'NO'}",
            f"  Extranonce2 size: {row.get('extranonce2_size') or '—'}",
        ])
        if row.get("error"):
            lines.append(f"  Error: {row.get('error')}")
    return "\n".join(lines)


class PoolDiagnosticsController:
    def __init__(self, event_callback=None):
        self.event_callback = event_callback or (lambda kind, payload: None)
        self._lock = threading.RLock()
        self._thread = None
        self._generation = 0
        self._state = {
            "running": False,
            "status": "Idle",
            "detail": "Run Test All Endpoints to profile configured Stratum endpoints.",
            "results": [],
            "started_at": 0.0,
            "completed_at": 0.0,
            "error": "",
            "endpoints": [],
            "stale": False,
        }

    @property
    def running(self):
        with self._lock:
            return bool(self._state.get("running"))

    def state(self):
        with self._lock:
            return dict(self._state)

    def start(self, endpoints, worker="", password="x", timeout=5.0):
        endpoints = normalize_endpoints(
            endpoints[0] if endpoints else "",
            endpoints[1:] if endpoints else [],
        )
        if not endpoints:
            raise ValueError("At least one Stratum endpoint is required.")
        if self.running:
            raise RuntimeError("Pool diagnostics are already running.")

        with self._lock:
            self._generation += 1
            generation = self._generation
            self._state = {
                "running": True,
                "status": "Running",
                "detail": f"Testing {len(endpoints)} configured endpoint(s) in the background.",
                "results": [],
                "started_at": time.time(),
                "completed_at": 0.0,
                "error": "",
                "endpoints": list(endpoints),
                "stale": False,
            }

        self._thread = threading.Thread(
            target=self._run,
            args=(generation, endpoints, worker, password, timeout),
            name="PoolStratumDiagnostics",
            daemon=True,
        )
        self._thread.start()
        return self.state()

    def _run(self, generation, endpoints, worker, password, timeout):
        results = []
        error = ""
        try:
            for endpoint in endpoints:
                row = probe_stratum_endpoint(
                    endpoint,
                    worker=worker,
                    password=password,
                    timeout=timeout,
                )
                results.append(row)
                with self._lock:
                    if generation != self._generation:
                        return
                    self._state["results"] = list(results)
                    self._state["detail"] = (
                        f"Completed {len(results)} / {len(endpoints)} endpoint diagnostics."
                    )
                try:
                    self.event_callback(
                        "log",
                        f"Stratum diagnostic {endpoint}: {row.get('score', 0)}/100"
                        + (f" — {row.get('error')}" if row.get("error") else ""),
                    )
                except Exception:
                    pass
        except Exception as exc:
            error = str(exc)
        finally:
            with self._lock:
                if generation != self._generation:
                    return
                self._state["running"] = False
                self._state["status"] = "Error" if error else "Complete"
                self._state["detail"] = (
                    f"Diagnostics completed for {len(results)} endpoint(s)."
                    if not error
                    else error
                )
                self._state["results"] = list(results)
                self._state["completed_at"] = time.time()
                self._state["error"] = error

    def invalidate(self, reason="Configured pool endpoints changed."):
        """Discard results tied to an obsolete endpoint set.

        May cancel an in-flight diagnostic run by advancing the generation
        token. The old worker may finish its current socket call, but its
        results are ignored.
        """
        with self._lock:
            self._generation += 1
            self._state = {
                "running": False,
                "status": "Stale",
                "detail": str(reason or "Configured pool endpoints changed."),
                "results": [],
                "started_at": 0.0,
                "completed_at": 0.0,
                "error": "",
                "endpoints": [],
                "stale": True,
            }
        return self.state()

    def clear(self):
        with self._lock:
            if self.running:
                raise RuntimeError("Wait for endpoint diagnostics to finish before clearing.")
            self._generation += 1
            self._state = {
                "running": False,
                "status": "Idle",
                "detail": "Diagnostics cleared.",
                "results": [],
                "started_at": 0.0,
                "completed_at": 0.0,
                "error": "",
                "endpoints": [],
                "stale": False,
            }
        return self.state()
