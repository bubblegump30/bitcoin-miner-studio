import base64
import json
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse


MAX_STRATUM_LINE_BYTES = 1_000_000


def test_bitcoin_core(rpc_url: str, username: str, password: str) -> str:
    from bitcoin_core import fetch_core_snapshot, snapshot_report
    return snapshot_report(fetch_core_snapshot(rpc_url, username, password))


def parse_stratum_url(pool_url: str):
    raw = str(pool_url or "").strip()
    if not raw:
        raise ValueError("Pool URL is required.")
    if "://" not in raw:
        raw = "stratum+tcp://" + raw
    parsed = urlparse(raw)

    plain = {"stratum+tcp", "tcp", "stratum"}
    secure = {"stratum+ssl", "stratum+tls", "ssl", "tls"}
    scheme = str(parsed.scheme or "").lower()
    if scheme not in plain | secure:
        raise ValueError("Use stratum+tcp://HOST:PORT or stratum+ssl://HOST:PORT")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Do not put worker names or passwords in the Stratum URL.")
    if parsed.query or parsed.fragment or parsed.params:
        raise ValueError("Stratum URLs cannot contain query strings, fragments, or parameters.")
    if parsed.path not in ("", "/"):
        raise ValueError("Stratum URLs cannot contain a path.")
    if not parsed.hostname:
        raise ValueError("Pool URL must include a host and port.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Pool URL contains an invalid port.") from exc
    if port is None or not 1 <= int(port) <= 65535:
        raise ValueError("Pool URL must include a port between 1 and 65535.")
    return parsed.hostname, int(port), scheme in secure


def open_stratum_socket(pool_url: str, timeout=8):
    host, port, secure = parse_stratum_url(pool_url)
    raw_sock = socket.create_connection((host, port), timeout=timeout)
    if secure:
        context = ssl.create_default_context()
        try:
            sock = context.wrap_socket(raw_sock, server_hostname=host)
        except Exception:
            try:
                raw_sock.close()
            finally:
                raise
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
        with sock.makefile("rwb", buffering=0) as f:
            f.write((json.dumps(subscribe) + "\n").encode())
            if worker.strip():
                f.write((json.dumps(authorize) + "\n").encode())

            got_sub = False
            got_auth = not bool(worker.strip())
            for _ in range(12):
                raw = f.readline(MAX_STRATUM_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_STRATUM_LINE_BYTES:
                    raise RuntimeError("Pool response exceeded the 1 MB Stratum line safety limit.")
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    lines.append(text[:2000])
                    continue

                msg_id = msg.get("id")
                method = msg.get("method")
                if msg_id == 1:
                    got_sub = bool(msg.get("result")) and not msg.get("error")
                    lines.append("\nmining.subscribe:")
                    lines.append(json.dumps(msg, indent=2)[:10000])
                elif msg_id == 2:
                    got_auth = msg.get("result") is True and not msg.get("error")
                    lines.append("\nmining.authorize:")
                    lines.append(json.dumps(msg, indent=2)[:10000])
                elif method in ("mining.set_difficulty", "mining.set_target", "mining.notify"):
                    lines.append(f"\nserver message: {method}")
                    lines.append(json.dumps(msg, indent=2)[:10000])

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
