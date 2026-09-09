import base64
import json
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse


def test_bitcoin_core(rpc_url: str, username: str, password: str) -> str:
    from bitcoin_core import fetch_core_snapshot, snapshot_report
    return snapshot_report(fetch_core_snapshot(rpc_url, username, password))


def parse_stratum_url(pool_url: str):
    raw = pool_url.strip()
    if "://" not in raw:
        raw = "stratum+tcp://" + raw
    parsed = urlparse(raw)

    plain = {"stratum+tcp", "tcp", "stratum"}
    secure = {"stratum+ssl", "stratum+tls", "ssl", "tls"}
    if parsed.scheme not in plain | secure:
        raise ValueError("Use stratum+tcp://HOST:PORT or stratum+ssl://HOST:PORT")
    if not parsed.hostname or not parsed.port:
        raise ValueError("Pool URL must include a host and port.")
    return parsed.hostname, parsed.port, parsed.scheme in secure


def open_stratum_socket(pool_url: str, timeout=8):
    host, port, secure = parse_stratum_url(pool_url)
    raw_sock = socket.create_connection((host, port), timeout=timeout)
    if secure:
        context = ssl.create_default_context()
        sock = context.wrap_socket(raw_sock, server_hostname=host)
    else:
        sock = raw_sock
    sock.settimeout(timeout)
    return sock, host, port, secure


def test_stratum(pool_url: str, worker: str, password: str) -> str:
    sock, host, port, secure = open_stratum_socket(pool_url, timeout=7)
    lines = [f"Connecting to {host}:{port} ({'TLS' if secure else 'TCP'}) ..."]

    subscribe = {
        "id": 1,
        "method": "mining.subscribe",
        "params": ["BitcoinMinerStudio/0.7.0"],
    }
    authorize = {
        "id": 2,
        "method": "mining.authorize",
        "params": [worker.strip(), password or "x"],
    }

    try:
        f = sock.makefile("rwb", buffering=0)
        f.write((json.dumps(subscribe) + "\n").encode())
        if worker.strip():
            f.write((json.dumps(authorize) + "\n").encode())

        got_sub = False
        got_auth = not bool(worker.strip())
        for _ in range(12):
            raw = f.readline()
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                lines.append(text)
                continue

            msg_id = msg.get("id")
            method = msg.get("method")
            if msg_id == 1:
                got_sub = bool(msg.get("result")) and not msg.get("error")
                lines.append("\nmining.subscribe:")
                lines.append(json.dumps(msg, indent=2))
            elif msg_id == 2:
                got_auth = msg.get("result") is True and not msg.get("error")
                lines.append("\nmining.authorize:")
                lines.append(json.dumps(msg, indent=2))
            elif method in ("mining.set_difficulty", "mining.set_target", "mining.notify"):
                lines.append(f"\nserver message: {method}")
                lines.append(json.dumps(msg, indent=2))

            if got_sub and got_auth:
                break

        lines.append(
            "\nResult: " +
            ("READY — subscribe/authorize succeeded." if got_sub and got_auth
             else "INCOMPLETE — check endpoint, worker name, password, and pool logs.")
        )
        return "\n".join(lines)
    finally:
        try:
            sock.close()
        except Exception:
            pass
