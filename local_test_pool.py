import hashlib
import json
import os
import socket
import threading
import time

from bitcoin_utils import difficulty_to_target


class LocalStratumTestPool:
    """
    Tiny local-only Stratum V1 validation server.

    It listens on 127.0.0.1 and deliberately uses a very low share
    difficulty so Bitcoin Miner Studio can demonstrate end-to-end:
      subscribe -> authorize -> notify -> mine -> submit -> accepted

    It does not connect to Bitcoin mainnet, pay rewards, or relay blocks.
    """

    def __init__(self, host="127.0.0.1", port=0, difficulty=0.000001, event_callback=None):
        self.host = host
        self.port = int(port)
        self.difficulty = float(difficulty)
        self.event_callback = event_callback or (lambda kind, payload: None)

        self._listener = None
        self._thread = None
        self._stop = threading.Event()
        self._clients = set()
        self._client_threads = set()
        self._client_lock = threading.RLock()
        self._counter_lock = threading.RLock()
        self._job_counter = 0
        self.accepted = 0
        self.rejected = 0
        self.connections = 0

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    @property
    def endpoint(self):
        return f"stratum+tcp://{self.host}:{self.port}"

    def _emit(self, kind, payload):
        try:
            self.event_callback(kind, payload)
        except Exception:
            pass

    def start(self):
        if self.running:
            return self.endpoint
        self._stop.clear()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))
        # PowerTools diagnostics may connect while the local mining client
        # is already attached. Keep enough backlog and handle each session on
        # its own daemon thread.
        self._listener.listen(16)
        self._listener.settimeout(0.5)
        self.port = self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._server_loop, daemon=True)
        self._thread.start()
        self._emit("log", f"Local test pool listening on {self.endpoint}")
        return self.endpoint

    def stop(self):
        self._stop.set()

        listener = self._listener
        self._listener = None
        if listener:
            try:
                listener.close()
            except Exception:
                pass

        with self._client_lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass

        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)

        with self._client_lock:
            threads = list(self._client_threads)
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=0.5)

        with self._client_lock:
            self._clients.clear()
            self._client_threads.clear()

        self._emit("log", "Local test pool stopped.")

    def _server_loop(self):
        while not self._stop.is_set():
            listener = self._listener
            if listener is None:
                break
            try:
                conn, addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with self._counter_lock:
                self.connections += 1
            with self._client_lock:
                self._clients.add(conn)

            self._emit("log", f"Local test miner connected from {addr[0]}:{addr[1]}")
            thread = threading.Thread(
                target=self._client_session,
                args=(conn,),
                name=f"LocalStratumClient-{addr[1]}",
                daemon=True,
            )
            with self._client_lock:
                self._client_threads.add(thread)
            thread.start()

    def _client_session(self, conn):
        try:
            self._handle_client(conn)
        except Exception as exc:
            if not self._stop.is_set():
                self._emit("log", f"Local test pool client error: {exc}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
            current = threading.current_thread()
            with self._client_lock:
                self._clients.discard(conn)
                self._client_threads.discard(current)

    def _send(self, conn, payload):
        conn.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))

    def _make_job(self):
        with self._counter_lock:
            self._job_counter += 1
            job_id = f"local-{self._job_counter:04d}"

        # Valid serialized transaction framing is not necessary for a local
        # share-validation test; the miner only needs deterministic coinbase
        # bytes to construct a merkle root/header.
        coinb1 = (
            "01000000"
            "01"
            + ("00" * 32)
            + "ffffffff"
            "08"
            "04"
        )
        coinb2 = (
            "ffffffff"
            "01"
            "0000000000000000"
            "00"
            "00000000"
        )

        return [
            job_id,
            "00" * 32,
            coinb1,
            coinb2,
            [],
            "20000000",
            "1d00ffff",
            f"{int(time.time()) & 0xffffffff:08x}",
            True,
        ]

    def _handle_client(self, conn):
        conn.settimeout(0.5)
        authorized = False
        extranonce1 = os.urandom(4).hex()
        extranonce2_size = 4
        buffer = b""

        while not self._stop.is_set():
            try:
                chunk = conn.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            if len(buffer) > 2_000_000:
                raise RuntimeError("Local test pool input buffer exceeded safety limit.")

            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                raw = raw.strip()
                if not raw:
                    continue
                msg = json.loads(raw.decode("utf-8", errors="replace"))
                method = msg.get("method")
                msg_id = msg.get("id")
                params = msg.get("params") or []

                if method == "mining.subscribe":
                    self._send(conn, {
                        "id": msg_id,
                        "result": [
                            [
                                ["mining.set_difficulty", "local-sub"],
                                ["mining.notify", "local-sub"],
                            ],
                            extranonce1,
                            extranonce2_size,
                        ],
                        "error": None,
                    })

                elif method == "mining.authorize":
                    authorized = True
                    self._send(conn, {"id": msg_id, "result": True, "error": None})
                    self._send(conn, {
                        "id": None,
                        "method": "mining.set_difficulty",
                        "params": [self.difficulty],
                    })
                    self._send(conn, {
                        "id": None,
                        "method": "mining.notify",
                        "params": self._make_job(),
                    })

                elif method == "mining.suggest_difficulty":
                    if params:
                        try:
                            requested = float(params[0])
                            if requested > 0:
                                self.difficulty = max(0.0000001, min(requested, 1.0))
                        except Exception:
                            pass
                    self._send(conn, {"id": msg_id, "result": True, "error": None})
                    self._send(conn, {
                        "id": None,
                        "method": "mining.set_difficulty",
                        "params": [self.difficulty],
                    })

                elif method == "mining.submit":
                    if not authorized or len(params) < 5:
                        with self._counter_lock:
                            self.rejected += 1
                        self._send(conn, {
                            "id": msg_id,
                            "result": False,
                            "error": [20, "not authorized or malformed share", None],
                        })
                        continue

                    with self._counter_lock:
                        self.accepted += 1
                        accepted_count = self.accepted
                    self._send(conn, {"id": msg_id, "result": True, "error": None})
                    self._emit("share", {
                        "accepted": accepted_count,
                        "worker": params[0],
                        "job_id": params[1],
                        "nonce": params[4],
                    })

                    if accepted_count % 5 == 0:
                        self._send(conn, {
                            "id": None,
                            "method": "mining.notify",
                            "params": self._make_job(),
                        })

                else:
                    if msg_id is not None:
                        self._send(conn, {
                            "id": msg_id,
                            "result": None,
                            "error": [20, f"unsupported method: {method}", None],
                        })
