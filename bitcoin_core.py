import base64
import json
import socket
import time
import urllib.error
import urllib.request


class BitcoinCoreRPCError(RuntimeError):
    def __init__(self, message, *, kind="rpc", rpc_code=None, http_status=None):
        super().__init__(message)
        self.kind = kind
        self.rpc_code = rpc_code
        self.http_status = http_status

    def as_dict(self):
        return {
            "kind": self.kind,
            "message": str(self),
            "rpc_code": self.rpc_code,
            "http_status": self.http_status,
        }


def _auth_header(username, password):
    if not username and not password:
        return None
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def rpc_call(rpc_url, username, password, method, params=None, timeout=6.0):
    """Call one Bitcoin Core JSON-RPC method and return (result, latency_ms)."""
    rpc_url = str(rpc_url or "").strip()
    if not rpc_url:
        raise BitcoinCoreRPCError("RPC URL is required.", kind="configuration")

    body = json.dumps({
        "jsonrpc": "2.0",
        "id": "bitcoin-miner-studio",
        "method": str(method),
        "params": list(params or []),
    }).encode("utf-8")

    request = urllib.request.Request(rpc_url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    auth = _auth_header(str(username or ""), str(password or ""))
    if auth:
        request.add_header("Authorization", auth)

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        if exc.code == 401:
            raise BitcoinCoreRPCError(
                "Bitcoin Core rejected the RPC credentials (HTTP 401). Check rpcuser/rpcpassword or your authentication setup.",
                kind="authentication",
                http_status=401,
            ) from exc
        raise BitcoinCoreRPCError(
            f"Bitcoin Core returned HTTP {exc.code}: {detail[:500] or exc.reason}",
            kind="http",
            http_status=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ConnectionRefusedError):
            raise BitcoinCoreRPCError(
                "Connection refused. Confirm Bitcoin Core is running and RPC is listening at this address.",
                kind="connection_refused",
            ) from exc
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise BitcoinCoreRPCError(
                "Bitcoin Core RPC timed out. Check the RPC address, firewall, and node responsiveness.",
                kind="timeout",
            ) from exc
        raise BitcoinCoreRPCError(f"RPC connection failed: {reason}", kind="connection") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise BitcoinCoreRPCError("Bitcoin Core RPC timed out.", kind="timeout") from exc
    except OSError as exc:
        raise BitcoinCoreRPCError(f"RPC socket error: {exc}", kind="connection") from exc

    latency_ms = (time.perf_counter() - started) * 1000.0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BitcoinCoreRPCError(
            f"Bitcoin Core returned invalid JSON: {raw[:300]}",
            kind="invalid_response",
        ) from exc

    error = payload.get("error")
    if error:
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise BitcoinCoreRPCError(
            f"RPC {method} failed" + (f" ({code})" if code is not None else "") + f": {message}",
            kind="rpc",
            rpc_code=code,
        )

    if "result" not in payload:
        raise BitcoinCoreRPCError(
            f"RPC {method} returned no result field.",
            kind="invalid_response",
        )
    return payload.get("result"), latency_ms


def _sync_percent(blockchain):
    progress = blockchain.get("verificationprogress")
    try:
        if progress is not None:
            return max(0.0, min(100.0, float(progress) * 100.0))
    except (TypeError, ValueError):
        pass
    blocks = int(blockchain.get("blocks", 0) or 0)
    headers = int(blockchain.get("headers", 0) or 0)
    if headers > 0:
        return max(0.0, min(100.0, blocks / headers * 100.0))
    return 0.0


def fetch_core_snapshot(rpc_url, username, password, timeout=6.0):
    """Fetch the v0.4.0 node health snapshot using three Bitcoin Core RPCs."""
    blockchain, latency_blockchain = rpc_call(
        rpc_url, username, password, "getblockchaininfo", timeout=timeout
    )
    mining, latency_mining = rpc_call(
        rpc_url, username, password, "getmininginfo", timeout=timeout
    )
    network, latency_network = rpc_call(
        rpc_url, username, password, "getnetworkinfo", timeout=timeout
    )

    blockchain = blockchain or {}
    mining = mining or {}
    network = network or {}

    blocks = int(blockchain.get("blocks", mining.get("blocks", 0)) or 0)
    headers = int(blockchain.get("headers", blocks) or blocks)
    sync_percent = _sync_percent(blockchain)
    initial_download = bool(blockchain.get("initialblockdownload", False))
    synced = (not initial_download) and sync_percent >= 99.99 and abs(headers - blocks) <= 2

    connections = network.get("connections")
    if connections is None:
        connections = int(network.get("connections_in", 0) or 0) + int(network.get("connections_out", 0) or 0)

    warnings = network.get("warnings") or mining.get("warnings") or blockchain.get("warnings") or ""
    if isinstance(warnings, list):
        warnings = " | ".join(str(x) for x in warnings)

    total_latency = latency_blockchain + latency_mining + latency_network
    return {
        "connected": True,
        "status": "Synced" if synced else "Syncing",
        "chain": str(blockchain.get("chain", mining.get("chain", "unknown"))),
        "blocks": blocks,
        "headers": headers,
        "bestblockhash": str(blockchain.get("bestblockhash", "")),
        "difficulty": float(mining.get("difficulty", blockchain.get("difficulty", 0)) or 0),
        "networkhashps": float(mining.get("networkhashps", 0) or 0),
        "pooledtx": int(mining.get("pooledtx", 0) or 0),
        "sync_percent": sync_percent,
        "verificationprogress": float(blockchain.get("verificationprogress", 0) or 0),
        "initialblockdownload": initial_download,
        "pruned": bool(blockchain.get("pruned", False)),
        "size_on_disk": int(blockchain.get("size_on_disk", 0) or 0),
        "connections": int(connections or 0),
        "connections_in": int(network.get("connections_in", 0) or 0),
        "connections_out": int(network.get("connections_out", 0) or 0),
        "networkactive": bool(network.get("networkactive", True)),
        "version": int(network.get("version", 0) or 0),
        "subversion": str(network.get("subversion", "")),
        "protocolversion": int(network.get("protocolversion", 0) or 0),
        "relayfee": float(network.get("relayfee", 0) or 0),
        "warnings": str(warnings),
        "latency_ms": total_latency,
        "last_check": time.time(),
        "error": "",
        "error_kind": "",
        "rpc_methods": ["getblockchaininfo", "getmininginfo", "getnetworkinfo"],
    }


def disconnected_snapshot(error=None):
    kind = getattr(error, "kind", "connection") if error else "connection"
    message = str(error) if error else "Bitcoin Core has not been checked yet."
    return {
        "connected": False,
        "status": "Offline",
        "chain": "—",
        "blocks": 0,
        "headers": 0,
        "bestblockhash": "",
        "difficulty": 0.0,
        "networkhashps": 0.0,
        "pooledtx": 0,
        "sync_percent": 0.0,
        "verificationprogress": 0.0,
        "initialblockdownload": False,
        "pruned": False,
        "size_on_disk": 0,
        "connections": 0,
        "connections_in": 0,
        "connections_out": 0,
        "networkactive": False,
        "version": 0,
        "subversion": "",
        "protocolversion": 0,
        "relayfee": 0.0,
        "warnings": "",
        "latency_ms": 0.0,
        "last_check": time.time(),
        "error": message,
        "error_kind": kind,
        "rpc_methods": ["getblockchaininfo", "getmininginfo", "getnetworkinfo"],
    }


def snapshot_report(snapshot):
    if not snapshot.get("connected"):
        return f"OFFLINE\n\n{snapshot.get('error') or 'Bitcoin Core RPC is unavailable.'}"
    return (
        "CONNECTED\n\n"
        f"Status: {snapshot.get('status', 'unknown')}\n"
        f"Chain: {snapshot.get('chain', 'unknown')}\n"
        f"Blocks / headers: {snapshot.get('blocks', 0):,} / {snapshot.get('headers', 0):,}\n"
        f"Sync progress: {snapshot.get('sync_percent', 0):.4f}%\n"
        f"Difficulty: {snapshot.get('difficulty', 0):,.4f}\n"
        f"Network hash rate: {snapshot.get('networkhashps', 0):,.0f} H/s\n"
        f"Mempool transactions: {snapshot.get('pooledtx', 0):,}\n"
        f"Connections: {snapshot.get('connections', 0)}\n"
        f"Node: {snapshot.get('subversion') or snapshot.get('version') or 'unknown'}\n"
        f"RPC round-trip total: {snapshot.get('latency_ms', 0):.1f} ms\n\n"
        "getblockchaininfo, getmininginfo, and getnetworkinfo succeeded."
    )


def get_best_block_hash(rpc_url, username, password, timeout=6.0):
    result, latency_ms = rpc_call(
        rpc_url, username, password, "getbestblockhash", timeout=timeout
    )
    value = str(result or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise BitcoinCoreRPCError("getbestblockhash returned an invalid block hash.", kind="invalid_response")
    return value, latency_ms


def validate_block_proposal(rpc_url, username, password, block_hex, timeout=15.0):
    """Ask Bitcoin Core to validate a full candidate block without submitting it."""
    block_hex = str(block_hex or "").strip().lower()
    if not block_hex or len(block_hex) % 2:
        raise BitcoinCoreRPCError("A complete raw block hex string is required.", kind="configuration")
    request = {"mode": "proposal", "data": block_hex, "rules": ["segwit"]}
    result, latency_ms = rpc_call(
        rpc_url,
        username,
        password,
        "getblocktemplate",
        [request],
        timeout=timeout,
    )
    # BIP22 proposal mode: null means the proposal is valid. A string is the reject reason.
    if result is None:
        return {"valid": True, "reason": "", "latency_ms": latency_ms}
    return {"valid": False, "reason": str(result), "latency_ms": latency_ms}


def submit_block(rpc_url, username, password, block_hex, timeout=20.0):
    """Submit one complete block to the user's configured local Bitcoin Core node."""
    block_hex = str(block_hex or "").strip().lower()
    if not block_hex or len(block_hex) % 2:
        raise BitcoinCoreRPCError("A complete raw block hex string is required.", kind="configuration")
    result, latency_ms = rpc_call(
        rpc_url,
        username,
        password,
        "submitblock",
        [block_hex],
        timeout=timeout,
    )
    # submitblock returns null when accepted, otherwise a BIP22-style rejection string.
    if result is None:
        return {"accepted": True, "reason": "", "latency_ms": latency_ms}
    return {"accepted": False, "reason": str(result), "latency_ms": latency_ms}
