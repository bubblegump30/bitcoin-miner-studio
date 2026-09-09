"""Bitcoin Miner Studio v0.4.6 — isolated Regtest Mining Laboratory.

The lab launches a second local Bitcoin Core instance with:
- a dedicated data directory,
- regtest=1,
- loopback-only RPC on a non-mainnet port,
- no P2P listening/discovery,
- a dedicated descriptor wallet/address.

It exercises the same Bitcoin Miner Studio pipeline used for real candidates:
getblocktemplate -> coinbase -> merkle root -> SHA-256d -> full block assembly
-> Bitcoin Core proposal mode -> submitblock -> acceptance confirmation.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

from branding import DEFAULT_REGTEST_COINBASE_TAG
from bitcoin_core import BitcoinCoreRPCError, rpc_call, submit_block, validate_block_proposal
from block_submission import assemble_candidate_block
from block_template import fetch_block_template
from coinbase_builder import decode_payout_address
from core_setup import read_rpc_cookie, validate_core_executable
from solo_miner import prepare_solo_work, search_nonce_batch

DEFAULT_RPC_PORT = 19443
DEFAULT_P2P_PORT = 19444
DEFAULT_WALLET = "MinerStudioRegtest"
DEFAULT_TAG = DEFAULT_REGTEST_COINBASE_TAG


class RegtestLabError(RuntimeError):
    pass


def unavailable_regtest_state(message="Regtest laboratory is stopped."):
    return {
        "running": False,
        "ready": False,
        "busy": False,
        "status": "Stopped",
        "detail": str(message),
        "operation": "",
        "isolated": True,
        "network": "regtest",
        "rpc_url": f"http://127.0.0.1:{DEFAULT_RPC_PORT}",
        "rpc_port": DEFAULT_RPC_PORT,
        "data_dir": "",
        "cookie_path": "",
        "executable": "",
        "wallet_name": DEFAULT_WALLET,
        "payout_address": "",
        "height": 0,
        "bestblockhash": "",
        "spendable_btc": 0.0,
        "immature_btc": 0.0,
        "untrusted_btc": 0.0,
        "blocks_mined_session": 0,
        "progress_current": 0,
        "progress_total": 0,
        "last_block_hash": "",
        "last_candidate_hash": "",
        "last_nonce": 0,
        "last_hashes": 0,
        "last_merkle_root": "",
        "last_block_size": 0,
        "last_block_weight": 0,
        "proposal_valid": False,
        "submit_accepted": False,
        "result_text": "",
        "error": "",
    }


def default_lab_dir():
    return Path.home() / ".bitcoin-miner-studio" / "regtest-lab"


def resolve_regtest_executable(configured):
    """Prefer bitcoind next to a configured bitcoin-qt installation."""
    exe = validate_core_executable(configured)
    name = exe.name.lower()
    candidates = []

    if name in {"bitcoin-qt.exe", "bitcoin-qt"}:
        daemon_name = "bitcoind.exe" if name.endswith(".exe") else "bitcoind"
        candidates.extend([
            exe.parent / "daemon" / daemon_name,
            exe.parent / daemon_name,
            exe.parent / "bin" / daemon_name,
        ])
    candidates.append(exe)

    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return exe


def build_regtest_launch_args(executable, data_dir, rpc_port=DEFAULT_RPC_PORT, p2p_port=DEFAULT_P2P_PORT):
    exe = resolve_regtest_executable(executable)
    data_dir = Path(data_dir).expanduser().resolve()
    args = [
        str(exe),
        "-regtest=1",
        f"-datadir={data_dir}",
        "-server=1",

        # Current-safe isolation profile. Bitcoin Core v30 removed -upnp.
        # -networkactive=0 disables all P2P networking; -listen=0 also
        # prevents inbound listening. RPC remains loopback-only below.
        "-listen=0",
        "-networkactive=0",

        "-rpcbind=127.0.0.1",
        "-rpcallowip=127.0.0.1",
        f"-rpcport={int(rpc_port)}",
        "-fallbackfee=0.0002",
    ]
    # If bitcoin-qt is the only executable available, keep the lab UI unobtrusive.
    if exe.name.lower() in {"bitcoin-qt.exe", "bitcoin-qt"}:
        args.extend(["-min=1", "-nosplash=1"])
    return exe, args


def mine_easy_template(
    template,
    payout_address,
    *,
    tag=DEFAULT_TAG,
    extranonce_value=0,
    batch_size=25000,
    max_hashes=5_000_000,
):
    """Find a target-valid candidate for an easy regtest template."""
    if not isinstance(template, dict) or not template.get("available"):
        raise RegtestLabError("A ready regtest block template is required.")

    # Validate the address locally before doing any mining work.
    decoded = decode_payout_address(payout_address, "regtest")
    if not decoded.get("valid"):
        raise RegtestLabError("The regtest payout address is invalid.")

    work = prepare_solo_work(
        template,
        payout_address,
        network="regtest",
        tag=tag,
        extranonce_size=8,
        extranonce_value=int(extranonce_value),
    )

    nonce = 0
    total_hashes = 0
    while total_hashes < int(max_hashes):
        count = min(int(batch_size), int(max_hashes) - total_hashes, (1 << 32) - nonce)
        if count <= 0:
            break
        result = search_nonce_batch(work, nonce, count)
        total_hashes += int(result.get("hashes") or 0)
        if result.get("candidate"):
            bundle = {
                "template": template,
                "work": work,
                "candidate": result["candidate"],
            }
            assembly = assemble_candidate_block(bundle, require_target=True)
            return {
                "work": work,
                "result": result,
                "assembly": assembly,
                "hashes": total_hashes,
            }
        nonce += count
        if nonce >= (1 << 32):
            raise RegtestLabError("Regtest nonce space exhausted unexpectedly.")

    raise RegtestLabError(
        f"No regtest candidate was found within {int(max_hashes):,} hashes. "
        "Refresh the template and try again."
    )


class RegtestLab:
    def __init__(
        self,
        *,
        configured_executable="",
        data_dir=None,
        rpc_port=DEFAULT_RPC_PORT,
        p2p_port=DEFAULT_P2P_PORT,
        event_callback=None,
    ):
        self.configured_executable = str(configured_executable or "")
        self.data_dir = Path(data_dir or default_lab_dir()).expanduser().resolve()
        self.rpc_port = int(rpc_port)
        self.p2p_port = int(p2p_port)
        self.rpc_url = f"http://127.0.0.1:{self.rpc_port}"
        self.wallet_name = DEFAULT_WALLET
        self.event_callback = event_callback
        self._lock = threading.RLock()
        self._job_lock = threading.Lock()
        self._process = None
        self._process_stdout_handle = None
        self._process_stderr_handle = None
        self._stop_requested = threading.Event()
        self._state = unavailable_regtest_state()
        self._state.update({
            "rpc_url": self.rpc_url,
            "rpc_port": self.rpc_port,
            "data_dir": str(self.data_dir),
            "cookie_path": str(self.cookie_path),
            "wallet_name": self.wallet_name,
        })
        self._metadata = self._load_metadata()
        if self._metadata.get("payout_address"):
            self._state["payout_address"] = self._metadata["payout_address"]

    @property
    def cookie_path(self):
        return self.data_dir / "regtest" / ".cookie"

    @property
    def metadata_path(self):
        return self.data_dir / "bitcoin-miner-studio-regtest.json"

    def _emit(self, message):
        if self.event_callback:
            try:
                self.event_callback(str(message))
            except Exception:
                pass

    def _load_metadata(self):
        try:
            if self.metadata_path.exists():
                value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
                return dict(value or {})
        except Exception:
            pass
        return {}

    def _save_metadata(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "wallet_name": self.wallet_name,
            "payout_address": self._state.get("payout_address", ""),
            "rpc_port": self.rpc_port,
        }
        self.metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._metadata = payload

    def state(self):
        with self._lock:
            return dict(self._state)

    @property
    def startup_stdout_path(self):
        return self.data_dir / "regtest-startup.stdout.log"

    @property
    def startup_stderr_path(self):
        return self.data_dir / "regtest-startup.stderr.log"

    def _close_startup_handles(self):
        for name in ("_process_stdout_handle", "_process_stderr_handle"):
            handle = getattr(self, name, None)
            if handle is not None:
                try:
                    handle.flush()
                except Exception:
                    pass
                try:
                    handle.close()
                except Exception:
                    pass
                setattr(self, name, None)

    @staticmethod
    def _tail_text(path, max_chars=6000):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
            return text[-int(max_chars):]
        except Exception:
            return ""

    def _startup_failure_detail(self, returncode):
        stderr = self._tail_text(self.startup_stderr_path)
        stdout = self._tail_text(self.startup_stdout_path)
        debug_log = self._tail_text(self.data_dir / "regtest" / "debug.log", max_chars=8000)
        parts = [f"Regtest Bitcoin Core exited during startup (code {returncode})."]
        if stderr:
            parts.append(f"Bitcoin Core stderr:\n{stderr}")
        elif stdout:
            parts.append(f"Bitcoin Core output:\n{stdout}")
        elif debug_log:
            parts.append(f"Bitcoin Core debug.log tail:\n{debug_log}")
        else:
            parts.append("No Bitcoin Core startup diagnostics were produced.")
        return "\n\n".join(parts)

    def _credentials(self):
        return read_rpc_cookie(self.cookie_path)

    def _rpc(self, method, params=None, timeout=8.0, wallet=False):
        username, password = self._credentials()
        url = self.rpc_url
        if wallet:
            url += "/wallet/" + quote(self.wallet_name, safe="")
        return rpc_call(url, username, password, method, params or [], timeout=timeout)

    def _wallet_loaded(self):
        wallets, _ = self._rpc("listwallets", timeout=6.0)
        return self.wallet_name in list(wallets or [])

    def _ensure_wallet(self):
        if not self._wallet_loaded():
            try:
                self._rpc("createwallet", [self.wallet_name], timeout=15.0)
            except BitcoinCoreRPCError as exc:
                # Existing-but-unloaded wallet.
                if exc.rpc_code in (-4, -35) or "already exists" in str(exc).lower():
                    try:
                        self._rpc("loadwallet", [self.wallet_name], timeout=15.0)
                    except BitcoinCoreRPCError as load_exc:
                        if load_exc.rpc_code not in (-35,) and "already loaded" not in str(load_exc).lower():
                            raise
                else:
                    raise

        address = str(self._state.get("payout_address") or self._metadata.get("payout_address") or "").strip()
        if address:
            try:
                decode_payout_address(address, "regtest")
            except Exception:
                address = ""

        if not address:
            address, _ = self._rpc(
                "getnewaddress",
                ["Bitcoin Miner Studio Regtest", "bech32"],
                timeout=10.0,
                wallet=True,
            )
            address = str(address or "").strip()
            decode_payout_address(address, "regtest")
            with self._lock:
                self._state["payout_address"] = address
            self._save_metadata()

        return address

    def _balances(self):
        try:
            balances, _ = self._rpc("getbalances", timeout=8.0, wallet=True)
            mine = dict((balances or {}).get("mine") or {})
            return (
                float(mine.get("trusted", 0) or 0),
                float(mine.get("immature", 0) or 0),
                float(mine.get("untrusted_pending", 0) or 0),
            )
        except Exception:
            return 0.0, 0.0, 0.0

    def refresh(self):
        if not self.cookie_path.exists():
            state = self.state()
            state.update({
                "running": False,
                "ready": False,
                "busy": False,
                "status": "Stopped",
                "detail": "Regtest Lab is not running. Click Start Lab to launch the isolated node.",
                "operation": "",
                "result_text": "Regtest Lab is stopped. Start Lab before refreshing.",
                "error": "",
            })
            with self._lock:
                self._state = state
            return state

        try:
            chain, latency = self._rpc("getblockchaininfo", timeout=7.0)
            chain = dict(chain or {})
            if str(chain.get("chain") or "") != "regtest":
                raise RegtestLabError("The laboratory RPC endpoint is not a regtest node.")

            address = self._ensure_wallet()
            spendable, immature, untrusted = self._balances()
            state = self.state()
            was_mining = str(state.get("operation") or "").startswith("Mine ")
            state.update({
                "running": True,
                "ready": True,
                "busy": bool(was_mining),
                "status": state.get("status") if was_mining else "Ready",
                "detail": (
                    state.get("detail")
                    if was_mining
                    else "Isolated regtest node ready. Full local mining/submission tests can run safely."
                ),
                "operation": state.get("operation") if was_mining else "",
                "network": "regtest",
                "rpc_url": self.rpc_url,
                "rpc_port": self.rpc_port,
                "data_dir": str(self.data_dir),
                "cookie_path": str(self.cookie_path),
                "payout_address": address,
                "height": int(chain.get("blocks", 0) or 0),
                "bestblockhash": str(chain.get("bestblockhash") or ""),
                "spendable_btc": spendable,
                "immature_btc": immature,
                "untrusted_btc": untrusted,
                "rpc_latency_ms": float(latency or 0.0),
                "error": "",
            })
            with self._lock:
                self._state = state
            return state
        except Exception as exc:
            state = self.state()
            state.update({
                "running": False,
                "ready": False,
                "status": "Stopped" if not state.get("busy") else state.get("status"),
                "detail": str(exc),
                "error": str(exc),
            })
            with self._lock:
                self._state = state
            return state

    def probe_existing(self):
        if not self.cookie_path.exists():
            return self.state()
        return self.refresh()

    def start_node(self, timeout=20.0):
        if not self.configured_executable:
            raise RegtestLabError(
                "Bitcoin Core executable is not configured. Detect/locate Bitcoin Core first."
            )

        # Reconnect if the isolated node is already running.
        if self.cookie_path.exists():
            existing = self.refresh()
            if existing.get("ready"):
                self._emit("Regtest Lab reconnected to an existing isolated node.")
                return existing

        self.data_dir.mkdir(parents=True, exist_ok=True)
        exe, args = build_regtest_launch_args(
            self.configured_executable,
            self.data_dir,
            self.rpc_port,
            self.p2p_port,
        )

        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._close_startup_handles()
            self._process_stdout_handle = self.startup_stdout_path.open("w", encoding="utf-8", errors="replace")
            self._process_stderr_handle = self.startup_stderr_path.open("w", encoding="utf-8", errors="replace")
            self._process = subprocess.Popen(
                args, cwd=str(exe.parent), stdout=self._process_stdout_handle,
                stderr=self._process_stderr_handle, **kwargs,
            )
        except OSError as exc:
            self._close_startup_handles()
            raise RegtestLabError(f"Could not start the isolated regtest node: {exc}") from exc

        with self._lock:
            self._state["executable"] = str(exe)
            self._state["status"] = "Starting"
            self._state["detail"] = "Waiting for the isolated regtest RPC cookie and node startup."

        deadline = time.time() + float(timeout)
        last_error = ""
        while time.time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                returncode = self._process.returncode
                self._close_startup_handles()
                raise RegtestLabError(self._startup_failure_detail(returncode))
            if self.cookie_path.exists():
                state = self.refresh()
                if state.get("ready"):
                    state["executable"] = str(exe)
                    state["busy"] = False
                    state["operation"] = ""
                    state["status"] = "Ready"
                    state["detail"] = "Isolated regtest node ready. Full local mining/submission tests can run safely."
                    state["result_text"] = "Regtest Lab started successfully."
                    with self._lock:
                        self._state = state
                    self._close_startup_handles()
                    self._emit(
                        f"Regtest Lab ready on {self.rpc_url}, height {state.get('height', 0):,}."
                    )
                    return state
                last_error = str(state.get("error") or "")
            time.sleep(0.25)

        self._close_startup_handles()
        returncode = self._process.returncode if self._process is not None and self._process.poll() is not None else "timeout"
        raise RegtestLabError(
            "Regtest node did not become RPC-ready within the startup timeout."
            + (f" Last RPC error: {last_error}" if last_error else "")
            + "\n\n" + self._startup_failure_detail(returncode)
        )

    def stop_node(self, timeout=8.0):
        self._stop_requested.set()
        try:
            if self.cookie_path.exists():
                try:
                    self._rpc("stop", timeout=5.0)
                except Exception:
                    pass
        finally:
            deadline = time.time() + float(timeout)
            while time.time() < deadline:
                if self._process is not None and self._process.poll() is not None:
                    break
                if not self.cookie_path.exists():
                    break
                time.sleep(0.2)

            # Only terminate a process handle that this app instance created.
            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=2.0)
                except Exception:
                    pass

            self._process = None
            self._close_startup_handles()
            state = unavailable_regtest_state("Isolated regtest node stopped.")
            state.update({
                "rpc_url": self.rpc_url,
                "rpc_port": self.rpc_port,
                "data_dir": str(self.data_dir),
                "cookie_path": str(self.cookie_path),
                "wallet_name": self.wallet_name,
                "payout_address": self._metadata.get("payout_address", ""),
                "blocks_mined_session": self._state.get("blocks_mined_session", 0),
                "result_text": "Regtest node stopped.",
            })
            with self._lock:
                self._state = state
            self._emit("Regtest Lab stopped.")
            return state

    def reset_chain(self):
        self.stop_node(timeout=10.0)
        try:
            if self.data_dir.exists():
                shutil.rmtree(self.data_dir)
        except OSError as exc:
            raise RegtestLabError(
                f"Could not remove the isolated regtest data directory: {exc}"
            ) from exc

        self._metadata = {}
        state = unavailable_regtest_state("Regtest chain reset. Start Lab to create a fresh genesis-only chain.")
        state.update({
            "rpc_url": self.rpc_url,
            "rpc_port": self.rpc_port,
            "data_dir": str(self.data_dir),
            "cookie_path": str(self.cookie_path),
            "result_text": "Regtest chain reset.",
        })
        with self._lock:
            self._state = state
        self._emit("Regtest Lab chain reset.")
        return state

    def mine_blocks(self, count=1):
        count = max(1, min(500, int(count)))
        if not self.state().get("ready"):
            self.start_node()

        payout_address = self._ensure_wallet()
        starting_height = int(self.refresh().get("height") or 0)
        with self._lock:
            self._state.update({
                "busy": True,
                "status": "Mining",
                "detail": f"Running full regtest mining pipeline for {count:,} block(s).",
                "operation": "Mine Regtest Blocks",
                "progress_current": 0,
                "progress_total": count,
                "proposal_valid": False,
                "submit_accepted": False,
                "error": "",
            })

        last = {}
        for index in range(count):
            if self._stop_requested.is_set():
                self._stop_requested.clear()
                raise RegtestLabError("Regtest mining stopped.")

            username, password = self._credentials()
            template = fetch_block_template(
                self.rpc_url,
                username,
                password,
                timeout=8.0,
            )

            mined = mine_easy_template(
                template,
                payout_address,
                extranonce_value=(starting_height + index + 1) & 0xFFFFFFFFFFFFFFFF,
            )
            assembly = mined["assembly"]

            proposal = validate_block_proposal(
                self.rpc_url,
                username,
                password,
                assembly["raw_block"],
                timeout=12.0,
            )
            if not proposal.get("valid"):
                raise RegtestLabError(
                    f"Bitcoin Core proposal rejected regtest block: {proposal.get('reason') or 'unknown reason'}"
                )

            submitted = submit_block(
                self.rpc_url,
                username,
                password,
                assembly["raw_block"],
                timeout=12.0,
            )
            if not submitted.get("accepted"):
                raise RegtestLabError(
                    f"Bitcoin Core rejected regtest submitblock: {submitted.get('reason') or 'unknown reason'}"
                )

            height, _ = self._rpc("getblockcount", timeout=6.0)
            confirmed_hash, _ = self._rpc("getblockhash", [int(height)], timeout=6.0)
            if str(confirmed_hash or "").lower() != str(assembly["block_hash"]).lower():
                raise RegtestLabError(
                    "Bitcoin Core accepted a block, but the confirmed chain-tip hash did not match the assembled candidate."
                )

            last = {
                "height": int(height),
                "block_hash": assembly["block_hash"],
                "candidate_hash": assembly["block_hash"],
                "nonce": int(assembly["nonce"]),
                "hashes": int(mined["hashes"]),
                "merkle_root": assembly["merkle_root"],
                "block_size": int(assembly["block_size"]),
                "block_weight": int(assembly["block_weight"]),
            }

            with self._lock:
                self._state.update({
                    "progress_current": index + 1,
                    "height": int(height),
                    "bestblockhash": assembly["block_hash"],
                    "blocks_mined_session": int(self._state.get("blocks_mined_session") or 0) + 1,
                    "last_block_hash": assembly["block_hash"],
                    "last_candidate_hash": assembly["block_hash"],
                    "last_nonce": int(assembly["nonce"]),
                    "last_hashes": int(mined["hashes"]),
                    "last_merkle_root": assembly["merkle_root"],
                    "last_block_size": int(assembly["block_size"]),
                    "last_block_weight": int(assembly["block_weight"]),
                    "proposal_valid": True,
                    "submit_accepted": True,
                    "detail": (
                        f"Accepted regtest block {index + 1:,}/{count:,} "
                        f"at height {int(height):,}."
                    ),
                })
            self._emit(
                f"Regtest block accepted: height {int(height):,}, "
                f"hash {assembly['block_hash']}, nonce {int(assembly['nonce']):,}, "
                f"{int(mined['hashes']):,} hash(es)."
            )

        refreshed = self.refresh()
        with self._lock:
            refreshed.update({
                "busy": False,
                "status": "Ready",
                "operation": "",
                "progress_current": count,
                "progress_total": count,
                "blocks_mined_session": self._state.get("blocks_mined_session", 0),
                "last_block_hash": last.get("block_hash", ""),
                "last_candidate_hash": last.get("candidate_hash", ""),
                "last_nonce": last.get("nonce", 0),
                "last_hashes": last.get("hashes", 0),
                "last_merkle_root": last.get("merkle_root", ""),
                "last_block_size": last.get("block_size", 0),
                "last_block_weight": last.get("block_weight", 0),
                "proposal_valid": True,
                "submit_accepted": True,
                "detail": (
                    f"Full regtest pipeline passed for {count:,} block(s). "
                    f"Current lab height: {int(refreshed.get('height') or 0):,}."
                ),
                "result_text": (
                    "REGTEST MINING LAB PASSED\n\n"
                    f"Blocks mined this run: {count:,}\n"
                    f"Current height: {int(refreshed.get('height') or 0):,}\n"
                    f"Last block: {last.get('block_hash', '—')}\n"
                    f"Last nonce: {int(last.get('nonce') or 0):,}\n"
                    f"Last candidate hashes: {int(last.get('hashes') or 0):,}\n"
                    f"Spendable balance: {float(refreshed.get('spendable_btc') or 0):.8f} BTC\n"
                    f"Immature balance: {float(refreshed.get('immature_btc') or 0):.8f} BTC\n\n"
                    "Pipeline: getblocktemplate → coinbase → merkle root → SHA-256d → "
                    "block assembly → proposal validation → submitblock → chain confirmation."
                ),
                "error": "",
            })
            self._state = refreshed
        return refreshed


class RegtestLabController:
    """Serialize lab operations and expose non-blocking state transitions."""

    def __init__(self, lab, event_callback=None):
        self.lab = lab
        self.event_callback = event_callback
        self._job_lock = threading.Lock()

    def _emit(self, message):
        if self.event_callback:
            try:
                self.event_callback(message)
            except Exception:
                pass

    def state(self):
        return self.lab.state()

    def _run(self, operation, callable_):
        try:
            returned = callable_()
            state = dict(returned or self.lab.state())
            state["busy"] = False
            state["operation"] = ""
            if not state.get("error"):
                if state.get("ready"):
                    state["status"] = "Ready"
                elif operation.startswith("Stop "):
                    state["status"] = "Stopped"
                elif operation.startswith("Reset "):
                    state["status"] = "Stopped"
                state.setdefault("result_text", f"{operation} completed.")
            with self.lab._lock:
                self.lab._state = state
            self._emit(f"Regtest Lab {operation} completed.")
        except Exception as exc:
            state = self.lab.state()
            state.update({
                "busy": False,
                "status": "Error",
                "detail": str(exc),
                "operation": "",
                "result_text": f"ERROR: {exc}",
                "error": str(exc),
            })
            with self.lab._lock:
                self.lab._state = state
            self._emit(f"Regtest Lab {operation} failed: {exc}")
        finally:
            if self._job_lock.locked():
                self._job_lock.release()

    def launch(self, operation, status, detail, callable_):
        if not self._job_lock.acquire(blocking=False):
            active = self.lab.state().get("operation") or "another Regtest Lab operation"
            return {
                "ok": False,
                "error": f"{active} is already running.",
                "regtest": self.lab.state(),
            }

        state = self.lab.state()
        state.update({
            "busy": True,
            "status": status,
            "detail": detail,
            "operation": operation,
            "result_text": f"{operation} started in the background.",
            "error": "",
        })
        with self.lab._lock:
            self.lab._state = state

        thread = threading.Thread(
            target=self._run,
            args=(operation, callable_),
            name="RegtestLabWorker",
            daemon=True,
        )
        thread.start()
        return {
            "ok": True,
            "started": True,
            "regtest": state,
            "result": f"{operation} started in the background.",
        }
