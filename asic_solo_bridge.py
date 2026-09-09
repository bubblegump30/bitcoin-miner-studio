"""Bitcoin Miner Studio v0.5.0 — LAN-only ASIC Solo Mining Stratum V1 bridge."""

import copy
import hashlib
import ipaddress
import json
import math
import socket
import threading
import time
from collections import OrderedDict

from branding import DEFAULT_ASIC_COINBASE_TAG
from bitcoin_utils import build_header_prefix, difficulty_to_target, sha256d, target_to_difficulty
from coinbase_builder import build_coinbase_transaction, decode_payout_address
from solo_miner import prepare_solo_work

DEFAULT_PORT = 3333
DEFAULT_SHARE_DIFFICULTY = 65536.0
EXTRANONCE1_SIZE = 4
EXTRANONCE2_SIZE = 4
TOTAL_EXTRANONCE_SIZE = 8
MAX_LINE_BYTES = 1_000_000
MAX_CLIENTS = 64


class AsicSoloBridgeError(RuntimeError):
    pass


def detect_private_lan_ip():
    candidates = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            candidates.append(sock.getsockname()[0])
        finally:
            sock.close()
    except Exception:
        pass
    try:
        _, _, values = socket.gethostbyname_ex(socket.gethostname())
        candidates.extend(values)
    except Exception:
        pass
    for value in candidates:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        if (
            isinstance(ip, ipaddress.IPv4Address)
            and ip.is_private
            and not ip.is_loopback
            and not ip.is_unspecified
        ):
            return str(ip)
    return ""


def validate_bridge_bind_ip(value, *, allow_loopback=False):
    try:
        ip = ipaddress.ip_address(str(value or "").strip())
    except ValueError as exc:
        raise AsicSoloBridgeError("Solo Bridge bind address must be a literal private IPv4 address.") from exc
    if not isinstance(ip, ipaddress.IPv4Address):
        raise AsicSoloBridgeError("ASIC Solo Bridge currently supports IPv4 LAN interfaces only.")
    if ip.is_unspecified:
        raise AsicSoloBridgeError("Binding the Solo Bridge to 0.0.0.0 is not allowed.")
    if ip.is_loopback and not allow_loopback:
        raise AsicSoloBridgeError("Choose a private LAN address, not 127.0.0.1, so your ASIC can reach the bridge.")
    if not (ip.is_private or ip.is_link_local or (allow_loopback and ip.is_loopback)):
        raise AsicSoloBridgeError("ASIC Solo Bridge is restricted to private/local IPv4 interfaces.")
    return str(ip)


def validate_client_ip(value):
    try:
        ip = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return (
        isinstance(ip, ipaddress.IPv4Address)
        and (ip.is_private or ip.is_link_local or ip.is_loopback)
    )


def _valid_hex(value, byte_length, label):
    value = str(value or "").strip().lower()
    if len(value) != byte_length * 2 or any(ch not in "0123456789abcdef" for ch in value):
        raise AsicSoloBridgeError(f"{label} must be exactly {byte_length} bytes of hexadecimal.")
    return value


def _stratum_prevhash(display_hash):
    raw_serial = bytes.fromhex(_valid_hex(display_hash, 32, "Previous block hash"))[::-1]
    return b"".join(raw_serial[i:i + 4][::-1] for i in range(0, 32, 4)).hex()


def _merkle_branch_for_coinbase(txids):
    txids = list(txids or [])
    if not txids:
        return []
    level = [b"\x00" * 32] + [
        bytes.fromhex(_valid_hex(txid, 32, "Template transaction ID"))[::-1]
        for txid in txids
    ]
    index = 0
    branch = []
    while len(level) > 1:
        if len(level) & 1:
            level.append(level[-1])
        branch.append(level[index ^ 1].hex())
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        index //= 2
    return branch


def _template_fingerprint(template):
    digest = hashlib.sha256()
    for value in (
        template.get("height"),
        template.get("previousblockhash"),
        template.get("bits"),
        template.get("version"),
        template.get("coinbase_value_sats"),
    ):
        digest.update(str(value or "").encode())
    for txid in list(template.get("_txids") or []):
        digest.update(str(txid).encode())
    return digest.hexdigest()


def build_stratum_job(
    template,
    payout_address,
    *,
    network="main",
    tag=DEFAULT_ASIC_COINBASE_TAG,
    job_id="1",
    clean_jobs=True,
):
    if not isinstance(template, dict) or not template.get("available"):
        raise AsicSoloBridgeError("A ready Bitcoin Core block template is required.")

    txids = list(template.get("_txids") or [])
    txdata = list(template.get("_transaction_data") or [])
    tx_count = int(template.get("transactions") or 0)
    if tx_count != len(txids) or not template.get("_txids_complete"):
        raise AsicSoloBridgeError("Block template transaction IDs are incomplete.")
    if tx_count != len(txdata) or not template.get("_transaction_data_complete"):
        raise AsicSoloBridgeError("Block template raw transactions are incomplete.")

    decode_payout_address(payout_address, network)

    placeholder = bytes.fromhex("505552504452474e")  # "PURPDRGN"
    preview = build_coinbase_transaction(
        template,
        payout_address,
        network=network,
        tag=tag,
        extranonce_size=TOTAL_EXTRANONCE_SIZE,
        extranonce_value=placeholder,
    )
    base_hex = str(preview.get("base_transaction") or "")
    placeholder_hex = placeholder.hex()
    if base_hex.count(placeholder_hex) != 1:
        raise AsicSoloBridgeError("Could not uniquely locate the Stratum extranonce placeholder in coinbase.")
    coinb1, coinb2 = base_hex.split(placeholder_hex, 1)

    ntime = max(
        int(template.get("mintime") or 0),
        int(template.get("curtime") or 0),
        int(time.time()),
    )
    version = int(template.get("version") or 0) & 0xFFFFFFFF
    bits = int(str(template.get("bits") or "0"), 16) & 0xFFFFFFFF

    return {
        "job_id": str(job_id),
        "height": int(template.get("height") or 0),
        "template": copy.deepcopy(template),
        "template_fingerprint": _template_fingerprint(template),
        "payout_address": str(payout_address),
        "network": str(network),
        "tag": str(tag),
        "coinb1": coinb1,
        "coinb2": coinb2,
        "merkle_branch": _merkle_branch_for_coinbase(txids),
        "prevhash": _stratum_prevhash(template.get("previousblockhash")),
        "version": f"{version:08x}",
        "nbits": f"{bits:08x}",
        "ntime": f"{ntime & 0xFFFFFFFF:08x}",
        "clean_jobs": bool(clean_jobs),
        "created_at": time.time(),
    }


def job_notify_params(job):
    return [
        job["job_id"],
        job["prevhash"],
        job["coinb1"],
        job["coinb2"],
        list(job["merkle_branch"]),
        job["version"],
        job["nbits"],
        job["ntime"],
        bool(job["clean_jobs"]),
    ]


def verify_stratum_submit(job, extranonce1, extranonce2, ntime_hex, nonce_hex, share_difficulty):
    extranonce1 = _valid_hex(extranonce1, EXTRANONCE1_SIZE, "Extranonce1")
    extranonce2 = _valid_hex(extranonce2, EXTRANONCE2_SIZE, "Extranonce2")
    ntime_hex = _valid_hex(ntime_hex, 4, "ntime")
    nonce_hex = _valid_hex(nonce_hex, 4, "nonce")

    ntime = int(ntime_hex, 16)
    mintime = int(job["template"].get("mintime") or 0)
    if ntime < mintime:
        raise AsicSoloBridgeError("Submitted ntime is below the template minimum time.")
    if ntime > int(time.time()) + 2 * 60 * 60:
        raise AsicSoloBridgeError("Submitted ntime is implausibly far in the future.")

    fields = {
        "version": job["version"],
        "prevhash": job["prevhash"],
        "coinb1": job["coinb1"],
        "coinb2": job["coinb2"],
        "merkle_branch": job["merkle_branch"],
        "ntime": ntime_hex,
        "nbits": job["nbits"],
    }
    prefix, merkle_internal = build_header_prefix(fields, extranonce1, extranonce2)
    nonce = int(nonce_hex, 16)
    header = prefix + nonce.to_bytes(4, "little")
    digest = sha256d(header)
    hash_int = int.from_bytes(digest, "little")
    block_hash = digest[::-1].hex()

    network_target = int(str(job["template"].get("target_int") or "0"))
    if network_target <= 0:
        raise AsicSoloBridgeError("Job network target is invalid.")

    share_difficulty = max(0.00000001, float(share_difficulty))
    share_target = difficulty_to_target(share_difficulty)
    network_valid = hash_int <= network_target
    share_valid = network_valid or hash_int <= share_target
    share_diff = math.inf if hash_int == 0 else target_to_difficulty(hash_int)

    result = {
        "share_valid": bool(share_valid),
        "network_valid": bool(network_valid),
        "hash": block_hash,
        "hash_int": hash_int,
        "share_difficulty": share_diff,
        "nonce": nonce,
        "ntime": ntime,
        "merkle_root": merkle_internal[::-1].hex(),
        "candidate_bundle": None,
    }
    if not network_valid:
        return result

    combined = bytes.fromhex(extranonce1 + extranonce2)
    extranonce_value = int.from_bytes(combined, "little")
    work = prepare_solo_work(
        job["template"],
        job["payout_address"],
        network=job["network"],
        tag=job["tag"],
        extranonce_size=TOTAL_EXTRANONCE_SIZE,
        extranonce_value=extranonce_value,
        ntime=ntime,
    )
    expected_header = work["header_prefix"] + nonce.to_bytes(4, "little")
    if expected_header != header:
        raise AsicSoloBridgeError(
            "ASIC candidate header did not match Miner Studio's independently reconstructed work."
        )

    result["candidate_bundle"] = {
        "template": copy.deepcopy(job["template"]),
        "work": work,
        "candidate": {
            "hash": block_hash,
            "hash_int": hash_int,
            "nonce": nonce,
            "header_hex": header.hex(),
        },
    }
    return result


def unavailable_bridge_state(message="ASIC Solo Bridge is stopped."):
    return {
        "running": False,
        "status": "Stopped",
        "detail": str(message),
        "bind_ip": "",
        "port": DEFAULT_PORT,
        "endpoint": "",
        "network": "",
        "payout_address": "",
        "share_difficulty": DEFAULT_SHARE_DIFFICULTY,
        "template_height": 0,
        "previousblockhash": "",
        "job_id": "",
        "job_age_seconds": 0.0,
        "connected_clients": 0,
        "authorized_workers": 0,
        "shares_accepted": 0,
        "shares_rejected": 0,
        "shares_stale": 0,
        "shares_duplicate": 0,
        "candidates_found": 0,
        "best_share_difficulty": 0.0,
        "estimated_hashrate_hs": 0.0,
        "started_at": 0.0,
        "uptime": 0.0,
        "last_share_at": 0.0,
        "last_share_hash": "",
        "last_candidate_hash": "",
        "workers": [],
        "error": "",
        "_accepted_work": 0.0,
    }


class AsicSoloBridge:
    def __init__(self, event_callback=None):
        self.event_callback = event_callback
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._server_socket = None
        self._server_thread = None
        self._clients = {}
        self._worker_history = OrderedDict()
        self._jobs = OrderedDict()
        self._current_job_id = ""
        self._job_counter = 0
        self._session_counter = 0
        self._seen_shares = OrderedDict()
        self._settings = {}
        self._state = unavailable_bridge_state()

    @property
    def running(self):
        with self._lock:
            return bool(self._state.get("running"))

    def _emit(self, kind, payload):
        if self.event_callback:
            try:
                self.event_callback(kind, payload)
            except Exception:
                pass

    def _log(self, message):
        self._emit("log", str(message))

    def _session_snapshot(self, session):
        return {
            "id": session["id"],
            "ip": session["ip"],
            "worker": session.get("worker") or "—",
            "authorized": bool(session.get("authorized")),
            "connected_at": float(session.get("connected_at") or 0),
            "last_share_at": float(session.get("last_share_at") or 0),
            "shares_accepted": int(session.get("shares_accepted") or 0),
            "shares_rejected": int(session.get("shares_rejected") or 0),
            "shares_stale": int(session.get("shares_stale") or 0),
            "best_difficulty": float(session.get("best_difficulty") or 0.0),
            "active": bool(session.get("active", True)),
        }

    def stats(self):
        now = time.time()
        with self._lock:
            state = dict(self._state)
            started = float(state.get("started_at") or 0)
            state["uptime"] = max(0.0, now - started) if started else 0.0
            job = self._jobs.get(self._current_job_id)
            state["job_age_seconds"] = max(
                0.0, now - float(job.get("created_at") or 0)
            ) if job else 0.0

            active = [self._session_snapshot(x) for x in self._clients.values()]
            active_ids = {x["id"] for x in active}
            history = [x for x in self._worker_history.values() if x["id"] not in active_ids]
            workers = active + history
            workers.sort(
                key=lambda x: (
                    not x.get("active"),
                    -(x.get("last_share_at") or x.get("connected_at") or 0),
                )
            )
            state["workers"] = workers[:24]
            state["connected_clients"] = len(active)
            state["authorized_workers"] = sum(1 for x in active if x.get("authorized"))
            elapsed = max(1.0, state["uptime"])
            state["estimated_hashrate_hs"] = (
                float(state.get("_accepted_work") or 0.0) * (2 ** 32) / elapsed
            )
            state.pop("_accepted_work", None)
            return state

    def _send(self, session, payload):
        raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        with session["send_lock"]:
            session["socket"].sendall(raw)

    def _response(self, session, msg_id, result=None, error=None):
        self._send(session, {"id": msg_id, "result": result, "error": error})

    def _new_job(self, template, *, clean_jobs=True):
        self._job_counter += 1
        job_id = f"{int(template.get('height') or 0):x}-{self._job_counter:x}"
        job = build_stratum_job(
            template,
            self._settings["payout_address"],
            network=self._settings["network"],
            tag=self._settings["tag"],
            job_id=job_id,
            clean_jobs=clean_jobs,
        )
        with self._lock:
            self._jobs[job_id] = job
            self._current_job_id = job_id
            while len(self._jobs) > 8:
                self._jobs.popitem(last=False)
            self._state["template_height"] = job["height"]
            self._state["previousblockhash"] = str(template.get("previousblockhash") or "")
            self._state["job_id"] = job_id
        return job

    def _send_work(self, session):
        with self._lock:
            job = self._jobs.get(self._current_job_id)
            difficulty = float(self._state.get("share_difficulty") or DEFAULT_SHARE_DIFFICULTY)
        if not job or not session.get("subscribed"):
            return
        self._send(session, {"id": None, "method": "mining.set_difficulty", "params": [difficulty]})
        self._send(session, {"id": None, "method": "mining.notify", "params": job_notify_params(job)})

    def _broadcast_work(self):
        with self._lock:
            sessions = list(self._clients.values())
        for session in sessions:
            try:
                self._send_work(session)
            except Exception:
                pass

    def start(
        self,
        template,
        payout_address,
        *,
        network="main",
        tag=DEFAULT_ASIC_COINBASE_TAG,
        bind_ip="",
        port=DEFAULT_PORT,
        share_difficulty=DEFAULT_SHARE_DIFFICULTY,
    ):
        if self.running:
            return self.stats()

        bind_ip = validate_bridge_bind_ip(bind_ip)
        port = int(port)
        if not 1024 <= port <= 65535:
            raise AsicSoloBridgeError("Choose a Solo Bridge TCP port between 1024 and 65535.")
        share_difficulty = float(share_difficulty)
        if not 0.00000001 <= share_difficulty <= 1e15:
            raise AsicSoloBridgeError("Solo Bridge share difficulty is outside the supported range.")

        decode_payout_address(payout_address, network)
        self._settings = {
            "payout_address": str(payout_address),
            "network": str(network),
            "tag": str(tag),
            "bind_ip": bind_ip,
            "port": port,
            "share_difficulty": share_difficulty,
        }
        first_job = self._new_job(template, clean_jobs=True)

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((bind_ip, port))
            server.listen(MAX_CLIENTS)
            server.settimeout(0.5)
        except Exception:
            server.close()
            with self._lock:
                self._jobs.clear()
                self._current_job_id = ""
            raise

        self._stop.clear()
        with self._lock:
            self._server_socket = server
            state = unavailable_bridge_state()
            state.update({
                "running": True,
                "status": "Ready",
                "detail": "LAN-only Stratum V1 Solo Bridge is ready for authorized ASIC workers.",
                "bind_ip": bind_ip,
                "port": port,
                "endpoint": f"stratum+tcp://{bind_ip}:{port}",
                "network": str(network),
                "payout_address": str(payout_address),
                "share_difficulty": share_difficulty,
                "template_height": first_job["height"],
                "previousblockhash": str(template.get("previousblockhash") or ""),
                "job_id": first_job["job_id"],
                "started_at": time.time(),
                "_accepted_work": 0.0,
                "error": "",
            })
            self._state = state

        self._server_thread = threading.Thread(
            target=self._accept_loop,
            name="AsicSoloStratumBridge",
            daemon=True,
        )
        self._server_thread.start()
        self._log(
            f"ASIC Solo Bridge listening on {state['endpoint']} "
            f"at share difficulty {share_difficulty:g}."
        )
        return self.stats()

    def stop(self, reason="ASIC Solo Bridge stopped."):
        self._stop.set()
        with self._lock:
            server = self._server_socket
            sessions = list(self._clients.values())
            self._server_socket = None
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
        for session in sessions:
            try:
                session["socket"].shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                session["socket"].close()
            except Exception:
                pass

        thread = self._server_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)

        with self._lock:
            old = dict(self._state)
            old.update({
                "running": False,
                "status": "Stopped",
                "detail": str(reason),
                "connected_clients": 0,
                "authorized_workers": 0,
            })
            self._state = old
        self._log(str(reason))
        return self.stats()

    def update_template(self, template):
        if not self.running or not template.get("available"):
            return False
        with self._lock:
            current = self._jobs.get(self._current_job_id)
        fingerprint = _template_fingerprint(template)
        if current and current.get("template_fingerprint") == fingerprint:
            return False
        job = self._new_job(template, clean_jobs=True)
        self._broadcast_work()
        self._log(
            f"Broadcast clean work {job['job_id']} for height {job['height']:,}."
        )
        return True

    def _accept_loop(self):
        while not self._stop.is_set():
            with self._lock:
                server = self._server_socket
            if server is None:
                break
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            ip = str(addr[0])
            if not validate_client_ip(ip):
                conn.close()
                self._log(f"Rejected non-private Stratum client {ip}.")
                continue

            with self._lock:
                if len(self._clients) >= MAX_CLIENTS:
                    conn.close()
                    self._log(f"Rejected ASIC {ip}: Solo Bridge client limit reached.")
                    continue

                self._session_counter += 1
                session_id = f"asic-{self._session_counter:08x}"
                extranonce1 = self._session_counter.to_bytes(
                    EXTRANONCE1_SIZE, "big"
                ).hex()
                session = {
                    "id": session_id,
                    "socket": conn,
                    "send_lock": threading.Lock(),
                    "ip": ip,
                    "worker": "",
                    "authorized": False,
                    "subscribed": False,
                    "extranonce1": extranonce1,
                    "connected_at": time.time(),
                    "last_share_at": 0.0,
                    "shares_accepted": 0,
                    "shares_rejected": 0,
                    "shares_stale": 0,
                    "best_difficulty": 0.0,
                    "active": True,
                }
                self._clients[session_id] = session

            conn.settimeout(1.0)
            threading.Thread(
                target=self._client_loop,
                args=(session,),
                name=f"AsicSoloClient-{session_id}",
                daemon=True,
            ).start()
            self._log(f"ASIC Stratum client connected from {ip}.")

    def _mark_disconnected(self, session):
        with self._lock:
            sid = session["id"]
            current = self._clients.pop(sid, None)
            snap = self._session_snapshot(current or session)
            snap["active"] = False
            self._worker_history[sid] = snap
            while len(self._worker_history) > 24:
                self._worker_history.popitem(last=False)
        try:
            session["socket"].close()
        except Exception:
            pass
        self._log(
            f"ASIC Stratum client disconnected: {session.get('worker') or session['ip']}."
        )

    def _client_loop(self, session):
        buffer = b""
        try:
            while not self._stop.is_set():
                try:
                    chunk = session["socket"].recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > MAX_LINE_BYTES:
                    raise AsicSoloBridgeError("ASIC sent an oversized Stratum request buffer.")

                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        msg = json.loads(raw.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue
                    self._handle_message(session, msg)
        except Exception as exc:
            self._log(f"ASIC Stratum session {session['ip']} ended: {exc}")
        finally:
            self._mark_disconnected(session)

    def _handle_message(self, session, msg):
        msg_id = msg.get("id")
        method = str(msg.get("method") or "")
        params = msg.get("params") or []
        if not isinstance(params, list):
            params = []

        if method == "mining.configure":
            requested = params[0] if params and isinstance(params[0], list) else []
            self._response(
                session,
                msg_id,
                result={str(extension): False for extension in requested},
                error=None,
            )
            return

        if method == "mining.subscribe":
            session["subscribed"] = True
            self._response(
                session,
                msg_id,
                result=[
                    [
                        ["mining.set_difficulty", session["id"]],
                        ["mining.notify", session["id"]],
                    ],
                    session["extranonce1"],
                    EXTRANONCE2_SIZE,
                ],
                error=None,
            )
            self._send_work(session)
            return

        if method == "mining.authorize":
            worker = str(params[0] if params else "").strip()[:160]
            session["worker"] = worker or f"ASIC-{session['ip']}"
            session["authorized"] = True
            self._response(session, msg_id, result=True, error=None)
            self._send_work(session)
            self._log(
                f"ASIC worker authorized: {session['worker']} ({session['ip']})."
            )
            return

        if method in ("mining.extranonce.subscribe", "mining.suggest_difficulty"):
            self._response(session, msg_id, result=True, error=None)
            return

        if method == "mining.submit":
            self._handle_submit(session, msg_id, params)
            return

        if msg_id is not None:
            self._response(
                session,
                msg_id,
                result=None,
                error=[20, f"unsupported method: {method}", None],
            )

    def _handle_submit(self, session, msg_id, params):
        if not session.get("authorized") or len(params) < 5:
            with self._lock:
                self._state["shares_rejected"] += 1
                session["shares_rejected"] += 1
            self._response(
                session, msg_id, result=False,
                error=[24, "not authorized or malformed share", None],
            )
            return

        worker, job_id, extranonce2, ntime_hex, nonce_hex = params[:5]
        job_id = str(job_id)
        with self._lock:
            job = copy.deepcopy(self._jobs.get(job_id))
            current_job = self._current_job_id
            share_difficulty = float(
                self._state.get("share_difficulty") or DEFAULT_SHARE_DIFFICULTY
            )

        if not job or job_id != current_job:
            with self._lock:
                self._state["shares_stale"] += 1
                session["shares_stale"] += 1
            self._response(session, msg_id, result=False, error=[21, "stale job", None])
            return

        duplicate_key = (
            session["extranonce1"], job_id, str(extranonce2).lower(),
            str(ntime_hex).lower(), str(nonce_hex).lower(),
        )
        with self._lock:
            if duplicate_key in self._seen_shares:
                self._state["shares_duplicate"] += 1
                session["shares_rejected"] += 1
                self._response(
                    session, msg_id, result=False,
                    error=[22, "duplicate share", None],
                )
                return
            self._seen_shares[duplicate_key] = time.time()
            while len(self._seen_shares) > 20000:
                self._seen_shares.popitem(last=False)

        try:
            result = verify_stratum_submit(
                job,
                session["extranonce1"],
                extranonce2,
                ntime_hex,
                nonce_hex,
                share_difficulty,
            )
        except Exception as exc:
            with self._lock:
                self._state["shares_rejected"] += 1
                session["shares_rejected"] += 1
            self._response(session, msg_id, result=False, error=[23, str(exc), None])
            return

        now = time.time()
        session["last_share_at"] = now
        session["best_difficulty"] = max(
            float(session.get("best_difficulty") or 0.0),
            float(result.get("share_difficulty") or 0.0),
        )
        with self._lock:
            self._state["last_share_at"] = now
            self._state["last_share_hash"] = str(result.get("hash") or "")
            self._state["best_share_difficulty"] = max(
                float(self._state.get("best_share_difficulty") or 0.0),
                float(result.get("share_difficulty") or 0.0),
            )

        if not result.get("share_valid"):
            with self._lock:
                self._state["shares_rejected"] += 1
                session["shares_rejected"] += 1
            self._response(
                session, msg_id, result=False,
                error=[23, "low difficulty share", None],
            )
            return

        with self._lock:
            self._state["shares_accepted"] += 1
            self._state["_accepted_work"] = (
                float(self._state.get("_accepted_work") or 0.0) + share_difficulty
            )
            session["shares_accepted"] += 1

        self._response(session, msg_id, result=True, error=None)
        self._emit(
            "share",
            {
                "worker": str(worker or session.get("worker") or ""),
                "ip": session["ip"],
                "job_id": job_id,
                "hash": result["hash"],
                "difficulty": result["share_difficulty"],
                "network_valid": bool(result.get("network_valid")),
            },
        )

        if not result.get("network_valid"):
            return

        with self._lock:
            self._state["candidates_found"] += 1
            self._state["last_candidate_hash"] = result["hash"]
            self._state["status"] = "Candidate Found"
            self._state["detail"] = (
                "ASIC found a Bitcoin-network-target-valid candidate. "
                "The bridge is pausing while Miner Studio preserves it."
            )

        self._emit(
            "candidate",
            {
                "worker": str(worker or session.get("worker") or ""),
                "ip": session["ip"],
                "hash": result["hash"],
                "nonce": result["nonce"],
                "height": job["height"],
                "bundle": result["candidate_bundle"],
            },
        )

        threading.Thread(
            target=self.stop,
            args=("ASIC Solo Bridge paused after target-valid candidate discovery.",),
            name="AsicSoloCandidatePause",
            daemon=True,
        ).start()
