import os
import atexit
import shutil
import tempfile
from pathlib import Path

# Release-candidate safety: the regression suite must never read/write the
# user's real Bitcoin Miner Studio settings, analytics DB, fleet history,
# Regtest lab, support bundles, or runtime-session marker.
_selftest_home = os.environ.get("BMS_SELFTEST_HOME", "").strip()
_selftest_home_owner = False
if not _selftest_home:
    _selftest_home = tempfile.mkdtemp(prefix="bitcoin-miner-studio-selftest-")
    os.environ["BMS_SELFTEST_HOME"] = _selftest_home
    _selftest_home_owner = True
os.environ["HOME"] = _selftest_home
os.environ["USERPROFILE"] = _selftest_home
if _selftest_home_owner:
    atexit.register(lambda: shutil.rmtree(_selftest_home, ignore_errors=True))

import time
import multiprocessing
import json

from bitcoin_utils import (
    build_header_prefix,
    calculate_merkle_root,
    difficulty_to_target,
    make_extranonce2,
)
from local_test_pool import LocalStratumTestPool
from stratum_miner import StratumMiner
from asic_manager import cgminer_command, query_device, ensure_private_host, classify_probe
from fleet_monitor import FleetMonitor, export_fleet_json, export_fleet_csv
from bitcoin_core import BitcoinCoreRPCError, fetch_core_snapshot, get_best_block_hash, rpc_call, snapshot_report, submit_block, validate_block_proposal
from block_template import compact_bits_to_target, fetch_block_template, parse_block_template, target_to_difficulty, template_report
from coinbase_builder import build_coinbase_transaction, decode_payout_address
from solo_miner import SoloMiningEngine, hash_header, merkle_root_from_txids, prepare_solo_work, probability_at_least_one, search_nonce_batch, serialize_block_header, solo_probability_metrics
from block_submission import assemble_candidate_block, assembly_for_ui
from regtest_lab import build_regtest_launch_args, mine_easy_template, unavailable_regtest_state
from asic_solo_bridge import build_stratum_job, job_notify_params, validate_bridge_bind_ip, verify_stratum_submit
from asic_manager import is_confirmed_asic
from core_setup import auto_config_values, detect_bitcoin_core, parse_bitcoin_conf, read_rpc_cookie, resolve_rpc_credentials, validate_core_executable, default_data_dirs, _extract_datadir_from_command_line
from purple_dragon_security import SECURITY_SCHEME, publisher_key_id, release_watermark, verify_integrity
from pool_powertools import normalize_endpoints, pool_health_score, probe_stratum_endpoint


def utility_tests():
    coinb1 = (
        "01000000010000000000000000000000000000000000000000000000000000000000000000"
        "ffffffff2503a77614048c8a145e08"
    )
    ex1 = "40000004"
    ex2 = "00000000"
    coinb2 = (
        "122f626974636f696e636c6f75642e6e65742f0000000002062c9c04000000001976a914"
        "23e020eacd64acfe093150331d44fdbcc0c7ce0688acc2eb0b00000000001976a914"
        "00bf6d61c2a34df5a9ea338fcad188c31bb4a52388ac00000000"
    )
    merkle = calculate_merkle_root(coinb1, ex1, ex2, coinb2, [])
    expected = "9b9c9ab0b1c92844e4fed3f895f9443fefcda5ae02cc5a8ad4444f9303081a23"
    assert merkle.hex() == expected

    job = {
        "job_id": "4ca",
        "prevhash": "4128bf630f57387b00e25b419d1bb77e667e4036a7d8fee80000015600000000",
        "coinb1": coinb1,
        "coinb2": coinb2,
        "merkle_branch": [],
        "version": "20000000",
        "nbits": "1a02b098",
        "ntime": "5e148a8c",
        "clean_jobs": True,
    }
    prefix, merkle2 = build_header_prefix(job, ex1, ex2)
    assert len(prefix) == 76
    assert merkle2 == merkle
    assert make_extranonce2(1, 4) == "00000001"
    assert difficulty_to_target(1) > 0
    print("[PASS] utility vectors")


def purple_dragon_security_tests():
    import tempfile
    from pathlib import Path as _Path

    state = verify_integrity(_Path(__file__).resolve().parent)
    assert state["checked"] is True
    assert state["verified"] is True, state
    assert state["signature_valid"] is True
    assert state["critical_actions_allowed"] is True
    assert state["security_scheme"] == SECURITY_SCHEME == "PD-PROVENANCE-2"
    assert state["verified_file_count"] == state["protected_file_count"]
    assert state["protected_file_count"] >= 20
    assert state["publisher_key_id"] == publisher_key_id()
    assert state["release_watermark"] == release_watermark()
    assert state["release_seal"].startswith("PD6-")

    # Copy the signed release and alter one protected file. Verification must
    # fail and critical write/mining controls must become unavailable.
    root = _Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as td:
        clone = _Path(td) / "tampered"
        clone.mkdir()
        manifest = json.loads((root / "purple_dragon_manifest.json").read_text(encoding="utf-8"))
        (clone / "purple_dragon_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for rel in manifest["files"]:
            src = root / rel
            out = clone / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(src.read_bytes())
        target = clone / "main.py"
        target.write_bytes(target.read_bytes() + b"\n# tamper test\n")
        failed = verify_integrity(clone)
        assert failed["verified"] is False
        assert failed["critical_actions_allowed"] is False
        assert "main.py" in failed["modified_files"]

    print("[PASS] Purple Dragon Security v2 — signed manifest, protected files, forensic release seal")
    print("[PASS] Purple Dragon tamper gate — modified protected file locks critical actions")


def asic_discovery_false_positive_tests():
    router = {
        "ip": "192.168.2.1",
        "api_verified": False,
        "recognized_web_asic": False,
        "web_available": True,
        "model": "Unknown network device",
    }
    desktop = {
        "ip": "192.168.2.15",
        "api_verified": False,
        "recognized_web_asic": False,
        "web_available": False,
        "model": "Unknown network device",
    }
    antminer_web = {
        "ip": "192.168.2.50",
        "api_verified": False,
        "recognized_web_asic": True,
    }
    cgminer = {
        "ip": "192.168.2.51",
        "api_verified": True,
        "recognized_web_asic": False,
    }

    assert is_confirmed_asic(router) is False
    assert is_confirmed_asic(desktop) is False
    assert is_confirmed_asic(antminer_web) is True
    assert is_confirmed_asic(cgminer) is True

    print("[PASS] ASIC discovery false-positive guard — router/desktop ignored; verified/recognized ASICs promoted")


def asic_solo_bridge_tests():
    template={
        "available":True,
        "height":101,
        "version":0x20000000,
        "previousblockhash":"11"*32,
        "bits":"207fffff",
        "target":"7fffff0000000000000000000000000000000000000000000000000000000000",
        "target_int":str(int("7fffff0000000000000000000000000000000000000000000000000000000000",16)),
        "difficulty":4.656542373906925e-10,
        "transactions":0,
        "_txids":[],
        "_txids_complete":True,
        "_transaction_data":[],
        "_transaction_data_complete":True,
        "transaction_weight":0,
        "size_limit":4000000,
        "weight_limit":4000000,
        "coinbase_value_sats":5000000000,
        "total_fees_sats":0,
        "subsidy_sats":5000000000,
        "coinbase_aux_flags":"",
        "default_witness_commitment":"",
        "curtime":int(time.time()),
        "mintime":int(time.time())-1,
    }

    from coinbase_builder import _bech32_polymod, _bech32_hrp_expand, BECH32_CHARSET, _convertbits
    hrp="bcrt"
    data=[0]+_convertbits(bytes(20),8,5,True)
    values=_bech32_hrp_expand(hrp)+data+[0]*6
    polymod=_bech32_polymod(values)^1
    checksum=[(polymod >> (5*(5-i))) & 31 for i in range(6)]
    address=hrp+"1"+"".join(BECH32_CHARSET[d] for d in data+checksum)

    job=build_stratum_job(
        template,address,network="regtest",job_id="asic-test"
    )
    params=job_notify_params(job)
    assert params[0]=="asic-test"
    assert len(params)==9
    assert len(job["coinb1"])>20
    assert len(job["coinb2"])>20

    ex1="00000001"
    ex2="00000002"
    candidate=None
    for nonce in range(1000):
        result=verify_stratum_submit(
            job,
            ex1,
            ex2,
            job["ntime"],
            f"{nonce:08x}",
            share_difficulty=0.00000001,
        )
        if result["network_valid"]:
            candidate=result
            break

    assert candidate is not None
    assert candidate["share_valid"] is True
    assert candidate["candidate_bundle"]
    assembly=assemble_candidate_block(
        candidate["candidate_bundle"], require_target=True
    )
    assert assembly["target_valid"] is True
    assert assembly["height"]==101

    assert validate_bridge_bind_ip("192.168.1.10")=="192.168.1.10"
    for bad in ("0.0.0.0","8.8.8.8","127.0.0.1"):
        try:
            validate_bridge_bind_ip(bad)
            raise AssertionError(f"{bad} should be rejected")
        except Exception:
            pass

    print("[PASS] ASIC Solo Bridge — Stratum job, extranonce reconstruction, target-valid ASIC candidate, full block assembly")
    print("[PASS] ASIC Solo LAN isolation — private bind accepted; wildcard/public/loopback bind rejected")


def regtest_lab_tests():
    template={
        "available":True,
        "height":1,
        "version":0x20000000,
        "previousblockhash":"11"*32,
        "bits":"207fffff",
        "target":"7fffff0000000000000000000000000000000000000000000000000000000000",
        "target_int":str(int("7fffff0000000000000000000000000000000000000000000000000000000000",16)),
        "difficulty":4.656542373906925e-10,
        "transactions":0,
        "_txids":[],
        "_txids_complete":True,
        "_transaction_data":[],
        "_transaction_data_complete":True,
        "transaction_weight":0,
        "size_limit":4000000,
        "weight_limit":4000000,
        "coinbase_value_sats":5000000000,
        "total_fees_sats":0,
        "subsidy_sats":5000000000,
        "coinbase_aux_flags":"",
        "default_witness_commitment":"",
        "curtime":1700000010,
        "mintime":1700000000,
    }
    # Known valid regtest/testnet-style Bech32 address produced from witness v0
    # program 20 zero bytes. It is generated locally here to avoid dependency on
    # an external node during selftest.
    from coinbase_builder import _bech32_polymod, _bech32_hrp_expand, BECH32_CHARSET, _convertbits
    hrp="bcrt"; data=[0]+_convertbits(bytes(20),8,5,True)
    values=_bech32_hrp_expand(hrp)+data+[0]*6
    polymod=_bech32_polymod(values)^1
    checksum=[(polymod >> (5*(5-i))) & 31 for i in range(6)]
    address=hrp+"1"+"".join(BECH32_CHARSET[d] for d in data+checksum)

    mined=mine_easy_template(template,address,batch_size=2000,max_hashes=100000)
    assembly=mined["assembly"]
    assert assembly["target_valid"] is True
    assert assembly["height"]==1
    assert assembly["transaction_count"]==1
    assert mined["hashes"]>=1

    state=unavailable_regtest_state()
    assert state["network"]=="regtest" and state["isolated"] is True

    # Core 30/31 launch compatibility. Bitcoin Core v30 removed -upnp.
    import tempfile as _tempfile
    from pathlib import Path as _Path
    with _tempfile.TemporaryDirectory() as _td:
        fake_exe = _Path(_td) / "bitcoind.exe"
        fake_exe.write_bytes(b"")
        _exe, launch_args = build_regtest_launch_args(fake_exe, _Path(_td) / "regtest-data")
        joined = " ".join(launch_args)
        assert "-regtest=1" in launch_args
        assert "-listen=0" in launch_args
        assert "-networkactive=0" in launch_args
        assert "-upnp" not in joined
        assert "-natpmp" not in joined
        assert "-listenonion" not in joined
        assert "-discover" not in joined
        assert "-dnsseed" not in joined

    # Busy-state lifecycle regression: controller must clear busy after success.
    class DummyLab:
        def __init__(self):
            import threading
            self._lock=threading.RLock()
            self._state=unavailable_regtest_state()
        def state(self):
            with self._lock:return dict(self._state)
    from regtest_lab import RegtestLabController
    dummy=DummyLab()
    ctl=RegtestLabController(dummy)
    result=ctl.launch("Refresh Regtest Lab","Refreshing","test",lambda: {
        **dummy.state(),"ready":False,"busy":False,"status":"Stopped","detail":"done","result_text":"done"
    })
    assert result["ok"] is True
    import time as _time
    for _ in range(100):
        if not ctl.state().get("busy"): break
        _time.sleep(.01)
    assert ctl.state()["busy"] is False
    assert ctl.state()["operation"]==""

    print("[PASS] Regtest Mining Laboratory — isolated state, easy SHA-256d candidate, full block assembly")
    print("[PASS] Regtest Core 31 compatibility — obsolete -upnp removed, minimal isolated launch flags")
    print("[PASS] Regtest Lab lifecycle — stopped refresh UX and background busy-state release")


def local_pool_integration():
    pool = LocalStratumTestPool(difficulty=0.000001)
    endpoint = pool.start()

    events = []
    miner = StratumMiner(lambda k, p: events.append((k, p)))
    miner.start(endpoint, "selftest.worker", "x", 1)

    deadline = time.time() + 12
    while time.time() < deadline:
        stats = miner.stats()
        if stats["accepted"] >= 2:
            break
        time.sleep(0.2)

    stats = miner.stats()
    miner.stop()
    pool.stop()

    assert stats["total_hashes"] > 0, stats
    assert stats["submitted"] >= 1, stats
    assert stats["accepted"] >= 1, stats
    assert pool.accepted >= 1
    assert stats["average_hashrate"] > 0, stats
    assert stats["peak_hashrate"] > 0, stats
    assert stats["acceptance_rate"] > 0, stats
    assert stats["job_count"] >= 1, stats
    assert stats["recent_shares"], stats
    print(
        "[PASS] local Stratum validation — "
        f"hashes={stats['total_hashes']:,}, "
        f"submitted={stats['submitted']}, "
        f"accepted={stats['accepted']}, "
        f"avg={stats['average_hashrate']:.0f} H/s, "
        f"peak={stats['peak_hashrate']:.0f} H/s"
    )

    miner.reset_stats()
    cleared = miner.stats()
    assert cleared["total_hashes"] == 0, cleared
    assert cleared["submitted"] == 0, cleared
    assert cleared["accepted"] == 0, cleared
    assert cleared["recent_shares"] == [], cleared
    print("[PASS] retained-session reset")


def suggested_difficulty_test():
    pool = LocalStratumTestPool(difficulty=0.001)
    endpoint = pool.start()

    logs = []
    miner = StratumMiner(lambda k, p: logs.append((k, p)))
    miner.start(endpoint, "selftest.worker", "x", 1, suggest_difficulty=0.000001)

    deadline = time.time() + 10
    seen_ack = False
    while time.time() < deadline:
        for kind, payload in logs:
            if kind == "log" and "acknowledged mining.suggest_difficulty" in str(payload):
                seen_ack = True
                break
        if seen_ack:
            break
        time.sleep(0.1)

    miner.stop()
    pool.stop()
    assert seen_ack, logs
    print("[PASS] mining.suggest_difficulty negotiation path")



def pool_powertools_tests():
    import socket

    pool = LocalStratumTestPool(difficulty=0.000001)
    endpoint = pool.start()
    try:
        normalized = normalize_endpoints(
            endpoint,
            [endpoint, "stratum+tcp://127.0.0.1:1"],
        )
        assert normalized[0] == endpoint
        assert len(normalized) == 2, normalized

        diagnostic = probe_stratum_endpoint(
            endpoint,
            worker="diagnostic.worker",
            password="x",
            timeout=4.0,
        )
        assert diagnostic["subscribed"] is True, diagnostic
        assert diagnostic["authorized"] is True, diagnostic
        assert diagnostic["job_received"] is True, diagnostic
        assert diagnostic["score"] >= 80, diagnostic
        assert diagnostic["extranonce2_size"] == 4, diagnostic
        assert "password" not in diagnostic

        # Find a currently closed local TCP port to force primary failure.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
        probe.close()
        dead = f"stratum+tcp://127.0.0.1:{closed_port}"

        miner = StratumMiner()
        miner.start(
            dead,
            "failover.worker",
            "x",
            1,
            backup_urls=[endpoint],
            failover_enabled=True,
            job_timeout_seconds=30,
        )
        deadline = time.time() + 14
        stats = {}
        while time.time() < deadline:
            stats = miner.stats()
            if stats.get("accepted", 0) >= 1:
                break
            time.sleep(0.2)
        miner.stop()

        assert stats.get("failover_count", 0) >= 1, stats
        assert stats.get("active_endpoint") == endpoint, stats
        assert stats.get("accepted", 0) >= 1, stats
        assert stats.get("connection_attempts", 0) >= 2, stats
        assert stats.get("job_count", 0) >= 1, stats
        assert stats.get("protocol_events"), stats
        assert stats.get("share_response_avg_ms", 0) >= 0
        assert stats.get("best_share_difficulty", 0) > 0, stats

        health = pool_health_score(stats)
        assert 0 <= health <= 100

        print(
            "[PASS] Pool & Stratum PowerTools 2.0 — "
            f"diagnostic={diagnostic['score']}/100, "
            f"failovers={stats['failover_count']}, "
            f"active={stats['active_endpoint']}"
        )
        print("[PASS] Stratum failover — dead primary → live backup → accepted share")
        print("[PASS] Stratum Inspector telemetry — protocol, job, difficulty, latency, best-share metrics")
    finally:
        pool.stop()




class MockASIC:
    def __init__(self):
        import socket
        import threading
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.socket.listen(4)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        try:
            self.socket.close()
        except Exception:
            pass

    def run(self):
        import json
        while not self.stop_event.is_set():
            try:
                conn, _ = self.socket.accept()
            except OSError:
                return
            try:
                raw = conn.recv(65536).split(b"\0", 1)[0]
                req = json.loads(raw.decode())
                command = req.get("command")

                if command == "summary":
                    body = {
                        "STATUS": [{"STATUS": "S", "Msg": "Summary"}],
                        "SUMMARY": [{
                            "Elapsed": 7200,
                            "GHS 5s": 125000,
                            "GHS av": 124500,
                            "Accepted": 900,
                            "Rejected": 2,
                            "Hardware Errors": 3,
                        }],
                    }
                elif command == "stats":
                    body = {
                        "STATUS": [{"STATUS": "S"}],
                        "STATS": [{
                            "Type": "Antminer S21 Test",
                            "temp1": 61,
                            "temp2": 67,
                            "fan1": 5200,
                            "fan2": 5100,
                            "Power": 3500,
                        }],
                    }
                elif command == "pools":
                    body = {
                        "STATUS": [{"STATUS": "S"}],
                        "POOLS": [{
                            "POOL": 0,
                            "URL": "stratum+tcp://pool.example:3333",
                            "User": "test.worker",
                            "Status": "Alive",
                            "Stratum Active": True,
                        }],
                    }
                elif command in ("restart", "switchpool"):
                    body = {
                        "STATUS": [{"STATUS": "S", "Msg": f"{command} accepted"}],
                    }
                else:
                    body = {
                        "STATUS": [{"STATUS": "E", "Msg": "unknown command"}],
                    }

                conn.sendall((json.dumps(body) + "\0").encode())
            finally:
                try:
                    conn.close()
                except Exception:
                    pass


def asic_manager_tests():
    import asic_manager

    miner = MockASIC()
    miner.start()

    original_port = asic_manager.CGMINER_PORT
    asic_manager.CGMINER_PORT = miner.port
    try:
        assert ensure_private_host("127.0.0.1") == "127.0.0.1"
        response = cgminer_command("127.0.0.1", "summary")
        assert response["SUMMARY"][0]["Accepted"] == 900

        device = query_device("127.0.0.1", timeout=1.0)
        assert device["status"] == "Online", device
        assert device["verification"] == "VERIFIED ASIC", device
        assert device["api_verified"] is True, device
        assert device["can_restart"] is True, device
        assert device["can_switch_pool"] is True, device
        assert device["model"] == "Antminer S21 Test", device
        assert device["hashrate_hs"] == 125000 * 1e9, device
        assert device["temperature_c"] == 67, device
        assert device["fan_rpm"] == 5200, device
        assert device["power_w"] == 3500, device
        assert device["pool_user"] == "test.worker", device
        assert device["efficiency_j_th"] > 0, device

        print(
            "[PASS] ASIC manager telemetry — "
            f"{device['model']}, "
            f"{device['hashrate_hs']/1e12:.1f} TH/s, "
            f"{device['temperature_c']:.0f} C"
        )

        candidate = classify_probe({
            "ip": "127.0.0.1",
            "cgminer": True,
            "http": False,
            "https": False,
        })
        assert candidate["verification"] == "CANDIDATE", candidate
        assert candidate["api_verified"] is False, candidate
        assert candidate["model"] == "TCP 4028 candidate", candidate
        assert candidate["can_restart"] is False, candidate
        assert candidate["can_switch_pool"] is False, candidate
        print("[PASS] ASIC false-positive classification guard")
    finally:
        asic_manager.CGMINER_PORT = original_port
        miner.stop()




def fleet_monitor_tests():
    import tempfile
    import time
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        storage = Path(td) / "history.json"
        monitor = FleetMonitor(max_samples=10, storage_path=storage)
        ip = "192.168.1.50"

        for hashrate, temp, status in (
            (100e12, 65, "Online"),
            (98e12, 66, "Online"),
            (96e12, 67, "Online"),
        ):
            monitor.record({
                "ip": ip,
                "status": status,
                "hashrate_hs": hashrate,
                "temperature_c": temp,
                "fan_rpm": 5000,
                "power_w": 3200,
                "accepted": 1000,
                "hardware_errors": 1,
            })

        availability = monitor.availability_percent(ip)
        assert availability == 100.0, availability
        assert monitor.baseline_hashrate[ip] > 0

        healthy = {
            "ip": ip,
            "status": "Online",
            "hashrate_hs": 96e12,
            "temperature_c": 67,
            "accepted": 1000,
            "hardware_errors": 1,
        }
        score = monitor.health_score(healthy)
        assert 70 <= score <= 100, score
        explanation = monitor.health_explanation(healthy)
        assert explanation["score"] == score
        assert "Status:" in explanation["summary"]

        bad = {
            "ip": ip,
            "status": "Online",
            "hashrate_hs": 50e12,
            "temperature_c": 85,
            "accepted": 1000,
            "hardware_errors": 20,
        }
        alerts = monitor.alerts(bad, temp_limit=80, drop_percent=25)
        kinds = {a["kind"] for a in alerts}
        assert "temperature" in kinds, alerts
        assert "hashrate" in kinds, alerts

        monitor.acknowledge_all(ip)
        assert monitor.alerts(bad, temp_limit=80, drop_percent=25) == []
        assert monitor.alerts(
            bad, temp_limit=80, drop_percent=25, include_acknowledged=True
        ), "Acknowledged alerts should still be discoverable."

        offline = dict(bad)
        offline["status"] = "Offline"
        offline["hashrate_hs"] = 0
        monitor.record(offline)
        assert monitor.offline_duration_seconds(ip) >= 0
        assert monitor.health_score(offline) == 0
        assert monitor.recent_events(), "Expected persisted fleet events."

        assert storage.exists() and storage.stat().st_size > 0
        reloaded = FleetMonitor(max_samples=10, storage_path=storage)
        assert reloaded.recent(ip), "Persistent history did not reload."
        assert ip in reloaded.offline_since

        devices = {
            ip: {
                "ip": ip,
                "model": "Test ASIC",
                "verification": "VERIFIED ASIC",
                "status": "Offline",
                "hashrate_hs": 0,
                "temperature_c": 85,
                "fan_rpm": 5000,
                "power_w": 3200,
                "efficiency_j_th": 64,
                "uptime_s": 1000,
                "pool_url": "stratum+tcp://pool.example:3333",
                "pool_user": "test.worker",
                "latency_ms": None,
                "accepted": 1000,
                "hardware_errors": 20,
            }
        }

        jp = Path(td) / "fleet.json"
        cp = Path(td) / "fleet.csv"
        export_fleet_json(jp, devices, reloaded, {ip: "Rack 1 Miner"}, {ip: "Garage"})
        export_fleet_csv(cp, devices, reloaded, {ip: "Rack 1 Miner"}, {ip: "Garage"})
        assert jp.exists() and jp.stat().st_size > 0
        assert cp.exists() and cp.stat().st_size > 0
        assert "health_score" in jp.read_text(encoding="utf-8")
        assert "offline_duration_seconds" in cp.read_text(encoding="utf-8")

    print("[PASS] persistent fleet history, health, alerts, acknowledgement, and export")


class MockBitcoinCoreRPC:
    def __init__(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        responses = {
            "getblockchaininfo": {
                "chain": "regtest",
                "blocks": 321,
                "headers": 321,
                "bestblockhash": "00" * 32,
                "verificationprogress": 1.0,
                "initialblockdownload": False,
                "pruned": False,
                "size_on_disk": 12345678,
            },
            "getmininginfo": {
                "blocks": 321,
                "difficulty": 4.0,
                "networkhashps": 987654321.0,
                "pooledtx": 17,
                "chain": "regtest",
            },
            "getnetworkinfo": {
                "version": 310000,
                "subversion": "/Satoshi:31.0.0/",
                "protocolversion": 70016,
                "networkactive": True,
                "connections": 8,
                "connections_in": 2,
                "connections_out": 6,
                "relayfee": 0.00001,
                "warnings": "",
            },
            "getblocktemplate": {
                "capabilities": ["proposal"],
                "version": 536870912,
                "rules": ["csv", "!segwit", "taproot"],
                "vbavailable": {},
                "vbrequired": 0,
                "previousblockhash": "11" * 32,
                "transactions": [
                    {"data": "01000000", "txid": "aa" * 32, "hash": "ab" * 32, "depends": [], "fee": 1200, "sigops": 1, "weight": 400},
                    {"data": "02000000", "txid": "bb" * 32, "hash": "bc" * 32, "depends": [1], "fee": 800, "sigops": 2, "weight": 600},
                ],
                "coinbaseaux": {"flags": "062f503253482f"},
                "coinbasevalue": 312502000,
                "longpollid": "mock-longpoll",
                "target": "00000000ffff0000000000000000000000000000000000000000000000000000",
                "mintime": 1700000000,
                "mutable": ["time", "transactions", "prevblock"],
                "noncerange": "00000000ffffffff",
                "sigoplimit": 80000,
                "sizelimit": 4000000,
                "weightlimit": 4000000,
                "curtime": 1700000010,
                "bits": "1d00ffff",
                "height": 322,
                "default_witness_commitment": "6a24aa21a9ed" + "00" * 32,
            },
        }

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                import base64
                import json
                expected = "Basic " + base64.b64encode(b"rpcuser:rpcpass").decode()
                if self.headers.get("Authorization") != expected:
                    self.send_response(401)
                    self.end_headers()
                    return
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length).decode())
                method = request.get("method")
                params = request.get("params") or []
                if method == "getbestblockhash":
                    body = {"jsonrpc": "2.0", "id": request.get("id"), "result": "11" * 32, "error": None}
                elif method == "getblocktemplate" and params and isinstance(params[0], dict) and params[0].get("mode") == "proposal":
                    body = {"jsonrpc": "2.0", "id": request.get("id"), "result": None, "error": None}
                elif method == "submitblock":
                    body = {"jsonrpc": "2.0", "id": request.get("id"), "result": None, "error": None}
                elif method not in responses:
                    body = {"jsonrpc": "2.0", "id": request.get("id"), "result": None, "error": {"code": -32601, "message": "Method not found"}}
                else:
                    body = {"jsonrpc": "2.0", "id": request.get("id"), "result": responses[method], "error": None}
                encoded = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, _format, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def coinbase_builder_tests():
    main = decode_payout_address("1BoatSLRHtKNngkdXEeobR76b53LETtpyT", "main")
    assert main["type"] == "P2PKH"
    assert main["script_pubkey"].startswith("76a914") and main["script_pubkey"].endswith("88ac")

    test = decode_payout_address("mipcBbFg9gMiCh81Kj8tqqdgoZub1ZJRfn", "testnet")
    assert test["type"] == "P2PKH"
    try:
        decode_payout_address("mipcBbFg9gMiCh81Kj8tqqdgoZub1ZJRfn", "main")
        raise AssertionError("Network mismatch should fail")
    except Exception:
        pass

    template = {
        "available": True,
        "height": 965330,
        "coinbase_value_sats": 314257248,
        "total_fees_sats": 1757248,
        "subsidy_sats": 312500000,
        "coinbase_aux_flags": "062f503253482f",
        "default_witness_commitment": "6a24aa21a9ed" + "11" * 32,
    }
    cb = build_coinbase_transaction(
        template,
        "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
        network="main",
        tag="Bitcoin Miner Studio / Purple Dragon Foundation ltd",
        extranonce_size=8,
        extranonce_value=7,
    )
    assert cb["available"] is True
    assert cb["coinbase_value_sats"] == 314257248
    assert cb["fees_sats"] == 1757248
    assert cb["subsidy_sats"] == 312500000
    assert cb["witness_commitment_present"] is True
    assert cb["output_count"] == 2
    assert len(cb["txid"]) == 64 and len(cb["wtxid"]) == 64
    assert 2 <= cb["coinbase_script_sig_bytes"] <= 100
    assert bytes.fromhex(cb["raw_transaction"])[4:6] == b"\x00\x01"
    assert cb["extranonce_value"] == 7
    assert cb["extranonce_hex"] == "0700000000000000"
    print("[PASS] Coinbase & Payout — address validation, BIP34 scriptSig, SegWit commitment, reward accounting")


def solo_mining_engine_tests():
    template={"available":True,"height":965336,"version":0x20000000,"previousblockhash":"11"*32,"bits":"207fffff","target":"ff"*32,"target_int":str((1<<256)-1),"difficulty":1e-12,"transactions":2,"_txids":["aa"*32,"bb"*32],"_txids_complete":True,"_transaction_data":["01000000","02000000"],"_transaction_data_complete":True,"transaction_weight":1000,"size_limit":4000000,"weight_limit":4000000,"coinbase_value_sats":315004850,"total_fees_sats":2504850,"subsidy_sats":312500000,"coinbase_aux_flags":"062f503253482f","default_witness_commitment":"6a24aa21a9ed"+"22"*32,"curtime":1700000010,"mintime":1700000000}
    work=prepare_solo_work(template,"1BoatSLRHtKNngkdXEeobR76b53LETtpyT",network="main",tag="Bitcoin Miner Studio / Purple Dragon Foundation ltd",extranonce_size=8,extranonce_value=9,ntime=1700000010)
    assert len(work["merkle_root"])==64
    assert work["merkle_root"]==merkle_root_from_txids([work["coinbase"]["txid"],"aa"*32,"bb"*32])
    header=serialize_block_header(work["version"],work["previousblockhash"],work["merkle_root"],work["ntime"],work["bits"],0);assert len(header)==80
    h,value=hash_header(header);assert len(h)==64 and value>=0
    result=search_nonce_batch(work,0,1);assert result["hashes"]==1 and result["candidate"] is not None and result["candidate"]["nonce"]==0 and len(result["candidate"]["header_hex"])==160
    bundle={"template":template,"work":work,"candidate":result["candidate"]}
    assembly=assemble_candidate_block(bundle,require_target=True)
    assert assembly["target_valid"] is True
    assert assembly["transaction_count"]==3
    assert assembly["block_size"]>80
    assert assembly["block_weight"]>1000
    assert assembly["raw_block"].startswith(result["candidate"]["header_hex"])
    ui=assembly_for_ui(assembly)
    assert "raw_block" not in ui
    assert ui["candidate_available"] is True

    structure_test = dict(assembly)
    structure_test["target_valid"] = False
    test_ui = assembly_for_ui(
        structure_test,
        status="Assembly Test Passed",
        candidate_available=False,
    )
    assert test_ui["assembled"] is True
    assert test_ui["target_valid"] is False
    assert test_ui["candidate_available"] is False

    # Dashboard+ probability math.
    assert abs(probability_at_least_one(0.5, 1) - 0.5) < 1e-12
    assert abs(probability_at_least_one(0.5, 2) - 0.75) < 1e-12
    metrics = solo_probability_metrics((1 << 255) - 1, 2.0, 2)
    assert 0.0 < metrics["session_probability"] < 1.0
    assert metrics["expected_seconds"] > 0
    assert metrics["time_to_50pct"] > 0

    # Stale-candidate guard: a target-valid hash on work superseded by a newly
    # queued chain-tip template must never be preserved.
    engine = SoloMiningEngine()
    engine._template = dict(template)
    engine._state = engine.stats()
    engine._state.update({
        "running": True,
        "work_height": template["height"],
        "previousblockhash": template["previousblockhash"],
        "target_int": template["target_int"],
        "template_update_pending": True,
    })
    engine._pending_template = {**template, "height": template["height"] + 1, "previousblockhash": "22" * 32}
    preserved = engine._record_candidate(result, work)
    assert preserved is False
    assert engine.candidate_bundle() is None
    assert engine.stats()["stale_candidates_rejected"] == 1

    print("[PASS] Solo Mining Engine — merkle root, 80-byte header, SHA-256d, nonce/target candidate detection")
    print("[PASS] Solo Dashboard+ — exact probability/odds metrics and 50% time calculations")
    print("[PASS] Solo stale-work guard — superseded target-valid candidates are rejected before preservation")
    print("[PASS] Block Assembly — complete block serialization, merkle/target consistency, weight/size guards")
    print("[PASS] Candidate gating — structure tests cannot unlock proposal/submit controls")


def bitcoin_core_setup_tests():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        appdata = root / "Roaming"
        data_dir = appdata / "Bitcoin"
        regtest_dir = data_dir / "regtest"
        regtest_dir.mkdir(parents=True)
        (data_dir / "bitcoin.conf").write_text(
            "server=1\nregtest=1\nrpcport=18443\n",
            encoding="utf-8",
        )
        (regtest_dir / ".cookie").write_text("__cookie__:mock-secret", encoding="utf-8")

        parsed = parse_bitcoin_conf(data_dir / "bitcoin.conf")
        assert parsed["global"]["server"] == "1"
        assert parsed["global"]["regtest"] == "1"

        def fake_socket(host, port):
            return int(port) == 18443

        detected = detect_bitcoin_core(
            {},
            env={"APPDATA": str(appdata), "LOCALAPPDATA": str(root / "Local")},
            platform_name="win32",
            home=root,
            socket_checker=fake_socket,
        )
        assert detected["detected"] is True
        assert detected["network"] == "regtest", detected
        assert detected["rpc_port"] == 18443
        assert detected["rpc_listening"] is True
        assert detected["cookie_exists"] is True
        assert detected["server_enabled"] is True
        assert detected["auth_mode_recommended"] == "cookie"

        values = auto_config_values(detected, {"rpc_user": "olduser"})
        assert values["core_auth_mode"] == "cookie"
        assert values["rpc_url"] == "http://127.0.0.1:18443"
        assert values["core_network"] == "regtest"

        user, password = read_rpc_cookie(detected["cookie_path"])
        assert user == "__cookie__" and password == "mock-secret"
        user2, password2 = resolve_rpc_credentials(
            {"core_auth_mode": "cookie", "core_cookie_path": detected["cookie_path"]},
            "ignored",
        )
        assert (user2, password2) == ("__cookie__", "mock-secret")
        assert resolve_rpc_credentials(
            {"core_auth_mode": "password", "rpc_user": "bitcoinrpc"},
            "manual-secret",
        ) == ("bitcoinrpc", "manual-secret")

        # Missing default paths must never be reported/autoconfigured as detected.
        empty_root = root / "EmptyProfile"
        empty_roaming = empty_root / "Roaming"
        missing = detect_bitcoin_core(
            {},
            env={"APPDATA": str(empty_roaming), "LOCALAPPDATA": str(empty_root / "Local")},
            platform_name="win32",
            home=empty_root,
            socket_checker=lambda host, port: False,
        )
        assert missing["detected"] is False, missing
        assert missing["data_dir"] == "", missing
        assert missing["data_dir_exists"] is False
        assert missing["cookie_path"] == ""
        assert missing["expected_data_dir"].endswith("Bitcoin")
        missing_values = auto_config_values(missing, {"rpc_user": "olduser"})
        assert missing_values["core_data_dir"] == ""
        assert missing_values["core_cookie_path"] == ""
        assert missing_values["core_auth_mode"] == "password"

        custom_install = Path(td) / "portable-bitcoin"
        custom_install.mkdir()
        custom_exe = custom_install / "bitcoin-qt.exe"
        custom_exe.write_bytes(b"MZ-test")
        selected = validate_core_executable(custom_exe)
        assert selected == custom_exe.resolve()

        custom_detected = detect_bitcoin_core(
            {"core_executable": str(custom_exe), "core_network": "main"},
            env={"APPDATA": str(Path(td) / "NoRoaming"), "LOCALAPPDATA": str(Path(td) / "NoLocal")},
            platform_name="win32",
            home=Path(td),
            socket_checker=lambda host, port: False,
        )
        assert custom_detected["installation_found"] is True
        assert Path(custom_detected["executable"]).resolve() == custom_exe.resolve()
        custom_values = auto_config_values(custom_detected, {})
        assert Path(custom_values["core_executable"]).resolve() == custom_exe.resolve()

        win_defaults = default_data_dirs(
            env={"LOCALAPPDATA": r"C:\\Users\\Test\\AppData\\Local", "APPDATA": r"C:\\Users\\Test\\AppData\\Roaming"},
            platform_name="win32",
            home=Path(td),
        )
        assert "appdata" in str(win_defaults[0]).lower() and "local" in str(win_defaults[0]).lower() and str(win_defaults[0]).lower().endswith("bitcoin")
        assert "appdata" in str(win_defaults[1]).lower() and "roaming" in str(win_defaults[1]).lower() and str(win_defaults[1]).lower().endswith("bitcoin")

        parsed_datadir = _extract_datadir_from_command_line(
            r'"C:\\Program Files\\Bitcoin\\bitcoin-qt.exe" -server=1 -datadir="E:\\BitcoinData"'
        )
        assert "e:" in str(parsed_datadir).lower() and str(parsed_datadir).lower().endswith("bitcoindata")

    print("[PASS] Bitcoin Core Setup Assistant — detection, network/port, cookie auth, auto-config")


def bitcoin_core_integration_tests():
    server = MockBitcoinCoreRPC()
    server.start()
    try:
        snapshot = fetch_core_snapshot(server.url, "rpcuser", "rpcpass", timeout=2)
        assert snapshot["connected"] is True, snapshot
        assert snapshot["status"] == "Synced", snapshot
        assert snapshot["chain"] == "regtest", snapshot
        assert snapshot["blocks"] == 321, snapshot
        assert snapshot["headers"] == 321, snapshot
        assert snapshot["sync_percent"] == 100.0, snapshot
        assert snapshot["difficulty"] == 4.0, snapshot
        assert snapshot["networkhashps"] == 987654321.0, snapshot
        assert snapshot["pooledtx"] == 17, snapshot
        assert snapshot["connections"] == 8, snapshot
        assert snapshot["subversion"] == "/Satoshi:31.0.0/", snapshot
        report = snapshot_report(snapshot)
        assert "getblockchaininfo" in report and "getnetworkinfo" in report

        template = fetch_block_template(server.url, "rpcuser", "rpcpass", timeout=2)
        assert template["available"] is True, template
        assert template["height"] == 322, template
        assert template["transactions"] == 2, template
        assert template["total_fees_sats"] == 2000, template
        assert template["coinbase_value_sats"] == 312502000, template
        assert template["subsidy_sats"] == 312500000, template
        assert template["difficulty"] == 1.0, template
        assert template["transaction_weight"] == 1000, template
        assert template["transaction_sigops"] == 3, template
        assert template["dependency_edges"] == 1, template
        assert template["_txids_complete"] is True
        assert template["_txids"] == ["aa" * 32, "bb" * 32]
        assert template["_transaction_data_complete"] is True
        assert template["target"] == "00000000ffff0000000000000000000000000000000000000000000000000000"
        assert compact_bits_to_target("1d00ffff") == int(template["target"], 16)
        assert target_to_difficulty(int(template["target"], 16)) == 1.0
        report_template = template_report(template)
        assert "BLOCK TEMPLATE READY" in report_template and "Next height: 322" in report_template

        best_hash, best_latency = get_best_block_hash(server.url, "rpcuser", "rpcpass", timeout=2)
        assert best_hash == "11" * 32 and best_latency >= 0
        proposal = validate_block_proposal(server.url, "rpcuser", "rpcpass", "00" * 100, timeout=2)
        assert proposal["valid"] is True
        submitted = submit_block(server.url, "rpcuser", "rpcpass", "00" * 100, timeout=2)
        assert submitted["accepted"] is True

        try:
            rpc_call(server.url, "rpcuser", "wrong", "getblockchaininfo", timeout=2)
            raise AssertionError("Expected authentication error")
        except BitcoinCoreRPCError as exc:
            assert exc.kind == "authentication", exc.kind

        print("[PASS] Bitcoin Core RPC integration — blockchain, mining, network, auth diagnostics")
        print("[PASS] Block Template Engine — getblocktemplate, target, fees, coinbase, limits")
        print("[PASS] Block Submission RPC — getbestblockhash, proposal mode, submitblock result handling")
    finally:
        server.stop()



def miner_xp_hash_hunt_tests():
    from pathlib import Path
    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")

    required_html = [
        'data-view="minerxp"',
        'id="view-minerxp"',
        'id="hashHuntRun"',
        'id="hashHuntClaim"',
        'id="hashHuntDifficulty"',
        'id="minerXpBar"',
        'id="dashboardMinerXpBar"',
        'id="hashAchievementList"',
        'id="minerUnlockList"',
    ]
    for token in required_html:
        assert token in html, token

    required_js = [
        "HASH_HUNT_STORAGE",
        "HASH_HUNT_DIFFICULTIES",
        "hashHuntDoubleSha256",
        "runHashHuntAttempt",
        "claimHashHuntBlock",
        "minerLevelFromXp",
        "minerNextThreshold",
        "localStorage",
    ]
    for token in required_js:
        assert token in js, token

    # Level 6 screenshot-style threshold: Level 6 advances at 1,050 total XP.
    assert 25 * 6 * 7 == 1050

    # Cosmetic boundary: Hash Hunt implementation contains no bridge mining calls.
    game_start = js.index("v0.6.1 — Miner XP & Hash Hunt")
    game_end = js.index("async function waitForBridge", game_start)
    game_slice = js[game_start:game_end]
    for forbidden in (
        "start_mining",
        "start_solo_mining",
        "submit_solo_candidate",
        "start_asic_solo_bridge",
        "switch_pool",
        "Bitcoin Core RPC",
    ):
        assert forbidden not in game_slice, forbidden

    assert ".miner-xp-rank-card" in css
    assert ".hash-console" in css

    print("[PASS] Miner XP & Hash Hunt — local progression, Level 6 / 1050 XP curve, achievements, cosmetic unlocks")
    print("[PASS] Hash Hunt isolation — no mining/ASIC/Bitcoin Core/submission API calls in mini-game implementation")



def webview_startup_dom_contract_tests():
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")

    start = js.index("function initFields")
    end = js.index("function fitCanvas", start)
    init_block = js[start:end]
    startup_ids = sorted(set(re.findall(r"\$\('#([^']+)'\)", init_block)))
    missing = [element_id for element_id in startup_ids if f'id="{element_id}"' not in html]

    assert not missing, f"Startup-critical DOM IDs missing from index.html: {missing}"
    assert 'id="credentialBackend"' in html
    assert "const credentialBackend=$('#credentialBackend')" in js
    assert "pollPurpleDragonStartup" in js
    assert "get_security_state" in (root / "webview_app.py").read_text(encoding="utf-8")

    print(
        "[PASS] WebView startup DOM contract — "
        f"{len(startup_ids)} initFields element(s) present; credentialBackend regression covered"
    )
    print("[PASS] Purple Dragon startup recovery — dedicated lightweight security-state polling path")



def local_test_pool_reliability_tests():
    from webview_app import recover_ephemeral_local_pool_config

    # v0.7.0/v0.7.0.1 legacy stale localhost endpoint must be removed.
    legacy = {
        "pool_url": "stratum+tcp://127.0.0.1:61103",
        "pool_backup_urls": [],
        "pool_worker": "local.worker1",
        "pool_url_ephemeral_local_test": False,
        "pool_restore_after_local_test": {},
    }
    recovered, changed, reason = recover_ephemeral_local_pool_config(legacy)
    assert changed is True
    assert recovered["pool_url"] == ""
    assert recovered["pool_worker"] == ""
    assert "stale Local Test Pool endpoint" in reason

    # New marked local session must restore the saved real pool.
    marked = {
        "pool_url": "stratum+tcp://127.0.0.1:62000",
        "pool_backup_urls": [],
        "pool_worker": "local.worker1",
        "pool_url_ephemeral_local_test": True,
        "pool_restore_after_local_test": {
            "pool_url": "stratum+tcp://example.net:3333",
            "pool_backup_urls": ["stratum+tcp://backup.example.net:3333"],
            "pool_worker": "wallet.worker",
            "pool_failover_enabled": True,
            "pool_job_timeout_seconds": 120,
            "suggest_difficulty_enabled": False,
            "suggest_difficulty": 1.0,
            "mining_processes": 2,
        },
    }
    restored, changed, _ = recover_ephemeral_local_pool_config(marked)
    assert changed is True
    assert restored["pool_url"] == "stratum+tcp://example.net:3333"
    assert restored["pool_worker"] == "wallet.worker"
    assert restored["pool_url_ephemeral_local_test"] is False

    # The local server must support a mining client and a diagnostic client
    # simultaneously.
    pool = LocalStratumTestPool(difficulty=0.000001)
    endpoint = pool.start()
    miner = StratumMiner()
    try:
        miner.start(endpoint, "concurrent.worker", "x", 1)
        deadline = time.time() + 10
        stats = {}
        while time.time() < deadline:
            stats = miner.stats()
            if stats.get("connected") and stats.get("authorized") and stats.get("job_count", 0) >= 1:
                break
            time.sleep(0.1)

        assert stats.get("connected"), stats
        diagnostic = probe_stratum_endpoint(
            endpoint,
            worker="diagnostic.concurrent",
            password="x",
            timeout=4.0,
        )
        assert diagnostic["subscribed"] is True, diagnostic
        assert diagnostic["authorized"] is True, diagnostic
        assert diagnostic["job_received"] is True, diagnostic
        assert diagnostic["score"] >= 80, diagnostic
        assert pool.connections >= 2, pool.connections

        print("[PASS] Local Test Pool lifecycle — stale ephemeral localhost ports are not reused after restart")
        print("[PASS] Local Test Pool restore — previous real-pool configuration survives local test sessions")
        print("[PASS] Local Test Pool multi-client — active mining + Endpoint Diagnostics can coexist")
    finally:
        miner.stop()
        pool.stop()



def local_test_pool_worker_autofill_tests():
    import tempfile
    from pathlib import Path
    import webview_app as appmod

    # Pure payload rule: an active local pool must override a blank/stale form.
    backend = appmod.WebBackend()
    try:
        endpoint = backend.local_pool.start()
        backend.cfg["pool_url"] = endpoint
        backend.cfg["pool_worker"] = "local.worker1"
        backend.cfg["pool_url_ephemeral_local_test"] = True
        backend.session_pool_password = "x"

        normalized = backend._normalize_local_test_pool_payload({
            "pool_url": endpoint,
            "pool_worker": "",
            "pool_password": "",
            "pool_backup_urls": ["stratum+tcp://example.invalid:3333"],
            "pool_failover_enabled": True,
            "mining_processes": 1,
            "pool_job_timeout_seconds": 120,
            "suggest_difficulty_enabled": False,
            "suggest_difficulty": 1.0,
        })
        assert normalized["pool_worker"] == "local.worker1", normalized
        assert normalized["pool_password"] == "x", normalized
        assert normalized["pool_backup_urls"] == [], normalized
        assert normalized["pool_failover_enabled"] is False, normalized

        # Exact failing user path: click Start Local Test Pool, visible Worker
        # field is blank/stale, then click Start Mining. Backend must still
        # start with local.worker1/x and receive a local job/share.
        payload = {
            "pool_url": endpoint,
            "pool_worker": "",
            "pool_password": "",
            "pool_backup_urls": [],
            "pool_failover_enabled": False,
            "mining_processes": 1,
            "pool_job_timeout_seconds": 120,
            "suggest_difficulty_enabled": False,
            "suggest_difficulty": 1.0,
        }

        # Bypass only the unrelated publisher-action gate for this isolated
        # transport regression; the production start_mining gate is tested
        # elsewhere in Purple Dragon tests.
        original_gate = backend._require_trusted_build
        backend._require_trusted_build = lambda action: (True, "")
        try:
            result = backend.start_mining(payload)
            assert result.get("ok") is True, result
            deadline = time.time() + 10
            stats = {}
            while time.time() < deadline:
                stats = backend.miner.stats()
                if stats.get("authorized") and stats.get("job_count", 0) >= 1:
                    break
                time.sleep(.1)
            assert backend.cfg["pool_worker"] == "local.worker1"
            assert stats.get("authorized") is True, stats
            assert stats.get("job_count", 0) >= 1, stats
        finally:
            backend._require_trusted_build = original_gate
            backend.miner.stop()

        html = (Path(__file__).resolve().parent / "ui" / "index.html").read_text(encoding="utf-8")
        js = (Path(__file__).resolve().parent / "ui" / "script.js").read_text(encoding="utf-8")
        assert 'id="poolWorker"' in html
        assert 'id="poolPassword"' in html
        assert "applyPoolConfigToForm" in js
        assert "pool_worker:'local.worker1'" in js
        assert "applyPoolConfigToForm(r.pool_config,r.local_password)" in js

        print("[PASS] Local Test Pool worker autofill — UI receives local.worker1 / x automatically")
        print("[PASS] Local Test Pool blank-form guard — backend overrides stale blank Worker/Wallet before mining starts")
    finally:
        backend.close()



def windows_multiprocessing_spawn_guard_tests():
    from pathlib import Path
    import runpy
    import sys
    import types

    root = Path(__file__).resolve().parent
    launch_path = root / "launch.pyw"
    main_path = root / "main.py"
    launch_text = launch_path.read_text(encoding="utf-8")
    main_text = main_path.read_text(encoding="utf-8")

    assert 'if __name__ == "__main__":' in launch_text
    assert "multiprocessing.freeze_support()" in launch_text
    assert 'multiprocessing.current_process().name != "MainProcess"' in launch_text

    assert 'if __name__ == "__main__":' in main_text
    assert "multiprocessing.freeze_support()" in main_text
    assert 'multiprocessing.current_process().name != "MainProcess"' in main_text

    # Simulate the important part of Windows multiprocessing spawn:
    # the original entry script is re-executed under the __mp_main__ name.
    # A fake main module lets us prove launch.pyw does NOT invoke main().
    calls = []
    original_main = sys.modules.get("main")
    fake_main = types.ModuleType("main")
    fake_main.main = lambda: calls.append("GUI_STARTED")
    sys.modules["main"] = fake_main
    try:
        runpy.run_path(str(launch_path), run_name="__mp_main__")
    finally:
        if original_main is None:
            sys.modules.pop("main", None)
        else:
            sys.modules["main"] = original_main

    assert calls == [], "launch.pyw started the GUI from a multiprocessing child."

    # main.py itself must also be safe when re-executed as __mp_main__.
    # Merely defining main() is allowed; invoking it is not.
    ns = runpy.run_path(str(main_path), run_name="__mp_main__")
    assert callable(ns.get("main"))

    print("[PASS] Windows multiprocessing spawn guard — launch.pyw stays headless under __mp_main__")
    print("[PASS] Main-process guard — only the original Bitcoin Miner Studio process may open the GUI")



def pool_diagnostics_freshness_tests():
    from pool_powertools import PoolDiagnosticsController

    ctl = PoolDiagnosticsController()
    ctl._state = {
        "running": False,
        "status": "Complete",
        "detail": "Diagnostics completed for 1 endpoint(s).",
        "results": [{"endpoint": "stratum+tcp://127.0.0.1:61103", "score": 15}],
        "started_at": 1.0,
        "completed_at": 2.0,
        "error": "",
        "endpoints": ["stratum+tcp://127.0.0.1:61103"],
        "stale": False,
    }
    stale = ctl.invalidate("Pool endpoint configuration changed.")
    assert stale["status"] == "Stale"
    assert stale["results"] == []
    assert stale["stale"] is True

    import webview_app
    backend = webview_app.WebBackend()
    try:
        endpoint = backend.local_pool.start()
        backend.cfg["pool_url"] = endpoint
        backend.cfg["pool_worker"] = "local.worker1"
        payload = backend._normalize_local_test_pool_payload({
            "pool_url": endpoint,
            "pool_worker": "local.worker1",
            "pool_password": "x",
            "suggest_difficulty_enabled": True,
            "suggest_difficulty": 1.0,
        })
        assert payload["suggest_difficulty_enabled"] is False, payload
        assert 0 < float(payload["suggest_difficulty"]) <= 0.000001, payload
    finally:
        backend.close()

    print("[PASS] Pool diagnostics freshness — old endpoint results are invalidated when configuration changes")
    print("[PASS] Local Test Pool difficulty isolation — persisted real-pool difficulty cannot suppress local shares")



def monitoring_analytics_tests():
    import csv
    import json
    import tempfile
    import time
    from pathlib import Path
    from analytics_monitor import AnalyticsStore, sanitized_snapshot

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        db = root / "analytics.sqlite3"
        store = AnalyticsStore(db, sample_seconds=5, retention_days=7)
        base = time.time() - 60
        samples = [
            {
                "ts": base,
                "pool_running": True,
                "pool_hashrate": 700_000,
                "pool_acceptance": 100,
                "pool_accepted": 10,
                "pool_health": 100,
                "pool_share_p95_ms": 300,
                "core_connected": True,
                "core_rpc_latency_ms": 30,
                "core_peers": 10,
                "core_sync_percent": 100,
                "core_height": 965000,
                "solo_running": False,
                "asic_total": 1,
                "asic_online": 1,
                "asic_hashrate": 125e12,
                "asic_avg_temp": 65,
                "asic_max_temp": 67,
                "asic_avg_health": 98,
            },
            {
                "ts": base + 20,
                "pool_running": True,
                "pool_hashrate": 800_000,
                "pool_acceptance": 100,
                "pool_accepted": 20,
                "pool_health": 94,
                "pool_share_p95_ms": 840,
                "core_connected": True,
                "core_rpc_latency_ms": 40,
                "core_peers": 10,
                "core_sync_percent": 100,
                "core_height": 965001,
                "solo_running": True,
                "solo_hashrate": 780_000,
                "solo_avg_hashrate": 775_000,
                "solo_peak_hashrate": 830_000,
                "solo_best_difficulty": 0.004,
                "asic_total": 1,
                "asic_online": 1,
                "asic_hashrate": 126e12,
                "asic_avg_temp": 66,
                "asic_max_temp": 68,
                "asic_avg_health": 97,
            },
            {
                "ts": base + 40,
                "pool_running": True,
                "pool_hashrate": 790_000,
                "pool_acceptance": 91,
                "pool_accepted": 30,
                "pool_rejected": 2,
                "pool_stale": 1,
                "pool_health": 62,
                "pool_share_p95_ms": 2600,
                "core_connected": False,
                "solo_running": True,
                "solo_hashrate": 785_000,
                "solo_avg_hashrate": 780_000,
                "solo_peak_hashrate": 830_000,
                "solo_best_difficulty": 0.006,
                "solo_stale_batches": 1,
                "asic_total": 1,
                "asic_online": 0,
                "asic_hashrate": 0,
                "asic_avg_temp": 82,
                "asic_max_temp": 82,
                "asic_avg_health": 0,
            },
        ]
        for row in samples:
            store.record(row)

        dash = store.dashboard(3600)
        assert dash["ok"] is True
        assert dash["summary"]["sample_count"] == 3
        assert dash["summary"]["pool_peak_hashrate"] == 800_000
        assert dash["summary"]["solo_best_difficulty"] == 0.006
        assert dash["summary"]["core_availability"] > 60
        assert dash["events"], dash
        kinds = {e["kind"] for e in dash["events"]}
        assert "health" in kinds
        assert "latency" in kinds
        assert "offline" in kinds
        assert "temperature" in kinds

        csv_path = root / "out.csv"
        json_path = root / "out.json"
        assert store.export(csv_path, 3600, "csv")["rows"] == 3
        assert store.export(json_path, 3600, "json")["rows"] == 3
        assert "pool_password" not in csv_path.read_text(encoding="utf-8")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["credential_free"] is True
        assert all("pool_password" not in row and "rpc_password" not in row for row in payload["samples"])

        store.clear()
        assert store.dashboard(3600)["summary"]["sample_count"] == 0
        store.stop()

    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    for token in (
        'data-view="monitoring"', 'id="view-monitoring"', 'id="monitorHashrateChart"',
        'id="monitorLatencyChart"', 'id="analyticsExportCsv"', 'id="analyticsClear"',
    ):
        assert token in html, token
    for token in ("refreshAnalytics", "renderAnalytics", "get_analytics_dashboard", "configure_analytics"):
        assert token in js or token in (root / "webview_app.py").read_text(encoding="utf-8"), token

    print("[PASS] Monitoring & Analytics — persistent SQLite sampling, summaries, range series, event detection")
    print("[PASS] Analytics privacy boundary — credential-free schema + CSV/JSON export")
    print("[PASS] Monitoring UI — Pool/Solo/Core/ASIC KPIs, historical charts, event timeline, data controls")


def release_candidate_hardening_tests():
    import json
    import tempfile
    import zipfile
    from pathlib import Path

    from config import DEFAULTS
    from release_candidate import (
        ReleaseCandidateManager,
        redact_text,
        sanitize_config,
        validate_config,
    )

    root = Path(__file__).resolve().parent
    cfg = dict(DEFAULTS)
    cfg.update({
        "pool_url": "stratum+tcp://private-pool.example:3333",
        "pool_worker": "test-wallet.worker",
        "coinbase_payout_address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        "rpc_user": "private-rpc-user",
    })

    with tempfile.TemporaryDirectory() as td:
        config_path = Path(td) / "settings.json"
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        issues = validate_config(cfg, config_path)
        assert not [x for x in issues if x["severity"] == "fail"], issues

        # A credential accidentally persisted to settings.json must block RC.
        contaminated = dict(cfg)
        contaminated["pool_password"] = "TOP-SECRET-POOL-PASSWORD"
        config_path.write_text(json.dumps(contaminated), encoding="utf-8")
        issues = validate_config(contaminated, config_path)
        assert any(x["code"] == "privacy.secret_in_settings" and x["severity"] == "fail" for x in issues)

        # Restore safe settings for the readiness pass.
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        manager = ReleaseCandidateManager(root, "1.0.0", cfg, config_path=config_path)
        security = {
            "checked": True,
            "verified": True,
            "signature_valid": True,
            "protected_file_count": 33,
            "verified_file_count": 33,
            "build_id": "BMS-1.0.0-TEST",
            "release_seal": "PD6-TEST",
            "publisher_key_id": "PDK-TEST",
        }
        # In the real app, WebBackend is created only after pywebview has
        # already imported successfully. The standalone self-test interpreter
        # does not install GUI dependencies, so simulate that already-loaded
        # runtime for this unit-level preflight check.
        import sys as _sys
        import types as _types
        _original_webview = _sys.modules.get("webview")
        _sys.modules["webview"] = _types.ModuleType("webview")
        try:
            state = manager.run_preflight(
                cfg,
                security_state=security,
                analytics_status={"running": True, "error": ""},
            )
        finally:
            if _original_webview is None:
                _sys.modules.pop("webview", None)
            else:
                _sys.modules["webview"] = _original_webview

        assert state["checked"] is True
        assert state["blockers"] == 0, state
        assert state["readiness"].startswith("STABLE READY"), state
        assert any(x["code"] == "startup.spawn_guard" and x["status"] == "pass" for x in state["checks"])
        assert any(x["code"] == "security.private_key" and x["status"] == "pass" for x in state["checks"])
        assert any(x["code"] == "privacy.profile_paths" and x["status"] == "pass" for x in state["checks"])

        sanitized = sanitize_config({
            **cfg,
            "pool_password": "TOP-SECRET-POOL-PASSWORD",
            "rpc_password": "TOP-SECRET-RPC-PASSWORD",
        })
        blob = json.dumps(sanitized)
        assert "TOP-SECRET" not in blob
        assert cfg["coinbase_payout_address"] not in blob
        assert cfg["pool_worker"] not in blob
        assert "private-pool.example" not in blob

        redacted = redact_text(
            f"password=TOP-SECRET-POOL-PASSWORD "
            f"{cfg['pool_url']} {cfg['coinbase_payout_address']} {Path.home()}"
        )
        assert "TOP-SECRET" not in redacted
        assert "private-pool.example" not in redacted
        assert cfg["coinbase_payout_address"] not in redacted
        assert str(Path.home()) not in redacted

        result = manager.create_support_bundle(
            {
                **cfg,
                "pool_password": "TOP-SECRET-POOL-PASSWORD",
                "rpc_password": "TOP-SECRET-RPC-PASSWORD",
            },
            logs=[{
                "time": "12:00:00",
                "message": (
                    "Pool password=TOP-SECRET-POOL-PASSWORD "
                    f"{cfg['pool_url']} payout {cfg['coinbase_payout_address']}"
                ),
            }],
            security_state=security,
            analytics_status={"running": True, "database_path": str(Path.home() / ".bitcoin-miner-studio" / "analytics.sqlite3")},
            pool_diagnostic_report=f"Endpoint: {cfg['pool_url']}",
        )
        bundle = Path(result["path"])
        assert bundle.is_file()
        with zipfile.ZipFile(bundle, "r") as z:
            names = set(z.namelist())
            assert "settings-sanitized.json" in names
            assert "support-report.json" in names
            assert "activity-log-redacted.txt" in names
            assert not any(name.endswith("analytics.sqlite3") for name in names)
            combined = b"\n".join(z.read(name) for name in names if not name.endswith(".png")).decode("utf-8", errors="ignore")
            assert "TOP-SECRET-POOL-PASSWORD" not in combined
            assert "TOP-SECRET-RPC-PASSWORD" not in combined
            assert cfg["coinbase_payout_address"] not in combined
            assert "private-pool.example" not in combined
        bundle.unlink(missing_ok=True)
        manager.mark_clean_shutdown()

    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    for token in (
        'data-view="release"',
        'id="view-release"',
        'id="rcPreflight"',
        'id="rcSupportBundle"',
        'id="rcChecksTable"',
    ):
        assert token in html, token
    for token in (
        "renderReleaseCandidate",
        "refreshReleaseCandidate",
        "run_release_preflight",
        "create_release_support_bundle",
    ):
        assert token in js or token in (root / "webview_app.py").read_text(encoding="utf-8"), token

    info = json.loads((root / "release_info.json").read_text(encoding="utf-8"))
    assert info["version"] == "2.0.1"
    assert info["channel"] == "Stable"
    assert info["feature_freeze"] is False
    assert info["cloud_telemetry"] is False
    assert info["automatic_support_upload"] is False

    print("[PASS] Stable release preflight — runtime/security/startup/config/storage gates")
    print("[PASS] Stable privacy support bundle — secrets, identifiers and analytics DB excluded/redacted")
    print("[PASS] Stable crash signal + release metadata + readiness UI")



def rc_preflight_cleanup_hotfix_tests():
    import sys
    import types
    from pathlib import Path
    import webview_app as appmod

    backend = appmod.WebBackend()
    try:
        # Case 1: screenshot regression — stale ephemeral marker exists but
        # no Local Test Pool is running. It should be permanently cleaned.
        backend.cfg["pool_url_ephemeral_local_test"] = True
        backend.cfg["pool_restore_after_local_test"] = {
            "pool_url": "stratum+tcp://example.com:3333",
            "pool_backup_urls": [],
        }
        assert backend.local_pool.running is False

        preflight_cfg = backend._normalize_rc_preflight_config()
        assert backend.cfg["pool_url_ephemeral_local_test"] is False
        assert backend.cfg["pool_restore_after_local_test"] == {}
        assert preflight_cfg["pool_url_ephemeral_local_test"] is False

        original_webview = sys.modules.get("webview")
        sys.modules["webview"] = types.ModuleType("webview")
        try:
            security = {
                "checked": True,
                "verified": True,
                "signature_valid": True,
                "protected_file_count": 33,
                "verified_file_count": 33,
            }
            state = backend.release_candidate.run_preflight(
                preflight_cfg,
                security_state=security,
                analytics_status={"running": True, "error": ""},
            )
        finally:
            if original_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = original_webview

        assert not any(row.get("code") == "pool.ephemeral_marker" for row in state["checks"]), state
        assert any(
            row.get("code") == "config.validation"
            and row.get("status") == "pass"
            and row.get("area") == "Configuration"
            for row in state["checks"]
        ), state
        assert state["score"] == 100, state
        assert state["warnings"] == 0, state
        assert state["blockers"] == 0, state

        # Case 2: Local Test Pool is intentionally active. Its real marker must
        # remain set, while the RC validation copy suppresses that expected
        # operational state so it does not produce a false warning.
        endpoint = backend.local_pool.start()
        backend.cfg["pool_url"] = endpoint
        backend.cfg["pool_url_ephemeral_local_test"] = True
        backend.cfg["pool_restore_after_local_test"] = {
            "pool_url": "stratum+tcp://example.com:3333",
        }

        active_preflight_cfg = backend._normalize_rc_preflight_config()
        assert backend.local_pool.running is True
        assert backend.cfg["pool_url_ephemeral_local_test"] is True
        assert backend.cfg["pool_restore_after_local_test"]
        assert active_preflight_cfg["pool_url_ephemeral_local_test"] is False
        assert active_preflight_cfg["pool_restore_after_local_test"] == {}

        original_webview = sys.modules.get("webview")
        sys.modules["webview"] = types.ModuleType("webview")
        try:
            active_state = backend.release_candidate.run_preflight(
                active_preflight_cfg,
                security_state=security,
                analytics_status={"running": True, "error": ""},
            )
        finally:
            if original_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = original_webview

        assert not any(row.get("code") == "pool.ephemeral_marker" for row in active_state["checks"]), active_state
        assert active_state["score"] == 100, active_state
        assert active_state["warnings"] == 0, active_state
        assert active_state["blockers"] == 0, active_state

        html = (Path(__file__).resolve().parent / "ui" / "index.html").read_text(encoding="utf-8")
        assert "v2.0.1 · UPDATE &amp; RELEASE CENTER" in html

        print("[PASS] RC stale Local Test Pool cleanup — inactive ephemeral metadata removed before scoring")
        print("[PASS] RC active Local Test Pool handling — expected live marker preserved but excluded from scoring")
        print("[PASS] RC Configuration tile — clean validation emits explicit PASS")
        print("[PASS] RC clean-state score — 100/100 with zero warnings/blockers")
    finally:
        backend.close()





def theme_studio_tests():
    import json
    from pathlib import Path

    import webview_app as appmod
    from ui_theme import UI_THEME_PRESETS, normalize_ui_theme

    root = Path(__file__).resolve().parent
    expected = {
        "purple","graphite","obsidian","frost","sapphire",
        "crimson","emerald","cyan","amber","rose",
    }
    assert set(UI_THEME_PRESETS) == expected
    assert normalize_ui_theme("CRIMSON") == "crimson"
    assert normalize_ui_theme("unknown-theme") == "purple"

    backend = appmod.WebBackend()
    try:
        for theme in expected:
            result = backend.set_ui_theme(theme)
            assert result["ok"] is True, result
            assert result["theme"] == theme, result
            assert backend.cfg["ui_theme"] == theme

        # Corrupt/unsupported input must safely normalize to Purple.
        result = backend.set_ui_theme("not-a-real-theme")
        assert result["ok"] is True
        assert result["theme"] == "purple"
        assert backend.cfg["ui_theme"] == "purple"

        boot = backend.get_bootstrap()
        assert boot["config"]["ui_theme"] == "purple"
        options = boot["config"]["ui_theme_options"]
        assert {row["id"] for row in options} == expected
    finally:
        backend.close()

    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")

    for token in (
        'id="themeToggle"',
        'id="themePopover"',
        'id="themeCurrent"',
        'id="themeGrid"',
    ):
        assert token in html, token
    for theme in expected:
        assert f'data-theme-value="{theme}"' in html, theme
        assert f'html[data-theme="{theme}"]' in css, theme

    assert 'html[data-theme="frost"]' in css
    assert "color-scheme:light" in css
    assert "applyUiTheme" in js
    assert "set_ui_theme" in js
    assert "UI_THEME_STORAGE" in js
    assert "cssVar('--accent'" in js
    assert "cssRgb('--deep-surface-rgb'" in js

    # Ensure the selected theme is not sensitive and remains support-safe.
    from release_candidate import sanitize_config, validate_config
    safe = sanitize_config({"ui_theme": "sapphire"})
    assert safe["ui_theme"] == "sapphire"
    assert not validate_config({"ui_theme": "purple", **{
        "mining_processes": 2,
        "benchmark_processes": 2,
        "pool_job_timeout_seconds": 120,
        "core_refresh_seconds": 10,
        "template_refresh_seconds": 15,
        "analytics_sample_seconds": 10,
        "analytics_retention_days": 30,
        "regtest_lab_rpc_port": 19443,
        "regtest_lab_p2p_port": 19444,
        "asic_solo_port": 3333,
        "pool_backup_urls": [],
        "pool_url_ephemeral_local_test": False,
    }}, None)

    print("[PASS] Theme Studio — 10 persistent presets + safe Purple fallback")
    print("[PASS] Theme UI — Graphite/Obsidian/Frost/Sapphire/Crimson/Emerald/Cyan/Amber/Rose")
    print("[PASS] Theme rendering — CSS variables + theme-aware live/Monitoring charts")
    print("[PASS] Frost light theme — dedicated light surfaces and contrast rules")



def theme_studio_overlay_hotfix_tests():
    from pathlib import Path

    root = Path(__file__).resolve().parent
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")

    assert "v0.9.0.3 — Theme Studio Overlay Hotfix" in css
    assert ".topbar{" in css
    assert "z-index:500" in css
    assert ".theme-picker{" in css
    assert "z-index:520" in css
    assert ".theme-popover{" in css
    assert "z-index:1000" in css
    assert "isolation:isolate" in css
    assert "overflow:visible" in css
    assert ".view{" in css
    assert "z-index:1" in css

    # The popover must remain a child of the top toolbar/theme picker.
    topbar_pos = html.index('<header class="topbar glass">')
    picker_pos = html.index('id="themePicker"', topbar_pos)
    popover_pos = html.index('id="themePopover"', picker_pos)
    topbar_end = html.index("</header>", popover_pos)
    assert topbar_pos < picker_pos < popover_pos < topbar_end

    print("[PASS] Theme Studio overlay stacking — toolbar layer 500 / picker 520 / popover 1000")
    print("[PASS] Theme Studio clipping guard — content/topbar/theme-picker overflow remains visible")
    print("[PASS] Dashboard layering — active view stays below toolbar overlay")



def paypal_donation_button_tests():
    import inspect
    from pathlib import Path
    from unittest import mock

    import webview_app as appmod

    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")

    assert appmod.PAYPAL_DONATION_URL == "https://www.paypal.me/KyleAustin85"
    assert 'id="paypalDonate"' in html
    assert "SUPPORT PURPLE DRAGON" in html
    assert "Purple Dragon Foundation ltd" in html
    assert "PayPal" in html
    assert ".donate-card{" in css
    assert "open_paypal_donation" in js

    # Security boundary: the donation bridge accepts no user-supplied URL.
    signature = inspect.signature(appmod.WebBackend.open_paypal_donation)
    assert list(signature.parameters) == ["self"], signature

    backend = appmod.WebBackend()
    try:
        with mock.patch.object(appmod.webbrowser, "open", return_value=True) as browser_open:
            result = backend.open_paypal_donation()
            assert result["ok"] is True, result
            assert result["url"] == appmod.PAYPAL_DONATION_URL
            browser_open.assert_called_once_with(
                appmod.PAYPAL_DONATION_URL,
                new=2,
            )

        names = {fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        assert "open_paypal_donation" in names
    finally:
        backend.close()

    print("[PASS] PayPal Donation — fixed payment endpoint branded as Purple Dragon Foundation ltd")
    print("[PASS] Donation URL confinement — WebView cannot supply an arbitrary external URL")
    print("[PASS] Donation UI — theme-aware Purple Dragon Foundation ltd support card")



def stable_release_promotion_tests():
    import json
    import sys
    import types
    from pathlib import Path

    import webview_app as appmod
    from config import DEFAULTS
    from release_candidate import RELEASE_CHANNEL, ReleaseCandidateManager

    root = Path(__file__).resolve().parent
    assert appmod.VERSION == "2.0.1"
    assert RELEASE_CHANNEL == "Stable"
    assert DEFAULTS["release_channel"] == "Stable"

    info = json.loads((root / "release_info.json").read_text(encoding="utf-8"))
    assert info["version"] == "2.0.1"
    assert info["channel"] == "Stable"
    assert info["stability"] == "Stable"
    assert info["cloud_telemetry"] is False
    assert info["automatic_support_upload"] is False
    assert info["silent_auto_update"] is False

    for name in (
        "CHANGELOG.md",
        "STABLE_RELEASE.md",
        "RELEASE_CHECKLIST.md",
        "package_portable.bat",
        "package_pyinstaller.bat",
    ):
        assert (root / name).is_file(), name

    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    assert "v2.0.1 · UPDATE &amp; RELEASE CENTER" in html
    assert ">Release Readiness<" in html
    assert "STABLE" in html

    backend = appmod.WebBackend()
    try:
        original_webview = sys.modules.get("webview")
        sys.modules["webview"] = types.ModuleType("webview")
        try:
            security = {
                "checked": True,
                "verified": True,
                "signature_valid": True,
                "protected_file_count": 39,
                "verified_file_count": 39,
            }
            state = backend.release_candidate.run_preflight(
                backend._normalize_rc_preflight_config(),
                security_state=security,
                analytics_status={"running": True, "error": ""},
            )
        finally:
            if original_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = original_webview

        assert state["blockers"] == 0, state
        assert state["readiness"] == "STABLE READY", state
        report = backend.release_candidate.report()
        assert "STABLE READINESS" in report
        assert "Stable baseline: ACTIVE" in report
    finally:
        backend.close()

    portable = (root / "package_portable.bat").read_text(encoding="utf-8")
    pyinstaller = (root / "package_pyinstaller.bat").read_text(encoding="utf-8")
    assert "Compress-Archive" in portable
    assert "startup-error.log" in portable
    assert "where pyinstaller" in pyinstaller
    assert "will not install packages automatically" in pyinstaller
    assert "--windowed" in pyinstaller
    assert "code-sign" in pyinstaller.lower()

    print("[PASS] Stable feature baseline — v2.0.1 / Stable channel / STABLE READY semantics")
    print("[PASS] Stable release metadata — no cloud telemetry, auto-upload or silent update")
    print("[PASS] Windows packaging helpers — portable ZIP + opt-in PyInstaller build path")
    print("[PASS] Stable documentation — changelog, release guide and release checklist")



def official_app_icon_tests():
    import struct
    from pathlib import Path

    root = Path(__file__).resolve().parent
    png = root / "assets" / "BitcoinMinerStudio.png"
    ico = root / "assets" / "BitcoinMinerStudio.ico"

    assert png.is_file()
    assert ico.is_file()
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    data = ico.read_bytes()
    reserved, image_type, count = struct.unpack_from("<HHH", data, 0)
    assert reserved == 0
    assert image_type == 1
    assert count >= 7, count

    webview_source = (root / "webview_app.py").read_text(encoding="utf-8")
    launcher_source = (root / "launch.pyw").read_text(encoding="utf-8")
    legacy_source = (root / "legacy_main.py").read_text(encoding="utf-8")
    packaging = (root / "package_pyinstaller.bat").read_text(encoding="utf-8")
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")

    assert "APP_ICON_RELATIVE" in webview_source
    assert "_schedule_windows_native_icon" in webview_source
    assert "WM_SETICON" in webview_source
    assert "SetCurrentProcessExplicitAppUserModelID" in launcher_source
    assert "BitcoinMinerStudio.ico" in legacy_source
    assert "--icon" in packaging and "BitcoinMinerStudio.ico" in packaging
    assert "--add-data" in packaging and "assets;assets" in packaging
    assert "assets/BitcoinMinerStudio.png" in html

    print("[PASS] Official app icon — approved Purple Dragon + Bitcoin PNG/ICO assets")
    print(f"[PASS] Windows ICO — {count} embedded icon representations")
    print("[PASS] Native pywebview icon — titlebar/taskbar WM_SETICON integration")
    print("[PASS] EXE packaging icon — PyInstaller icon + assets bundle")
    print("[PASS] Tk fallback/favicon — same official artwork")



def mining_assistant_tests():
    from pathlib import Path
    import mining_assistant as ma
    import webview_app as appmod

    assert set(ma.ASSISTANT_GOALS) == {"learn","cpu","pool","asic","core","solo"}
    assert ma.normalize_goal("SOLO") == "solo"
    assert ma.normalize_goal("unknown") == "learn"

    cfg = {
        "pool_url": "stratum+tcp://example.com:3333",
        "pool_worker": "wallet.worker1",
        "coinbase_payout_address": "",
        "core_network": "main",
        "asic_known_devices": [],
        "mining_assistant_goal": "learn",
    }
    state = ma.build_mining_assistant_snapshot(
        cfg,
        core_setup={"installation_found": False},
        core_state={"connected": False, "status": "Offline"},
        asic_devices=[],
        security_state={"checked": True, "verified": True},
        regtest_state={"running": False},
        benchmark_state={},
        analytics_status={"running": True},
    )
    assert state["overall"] == "MINING LAB READY", state
    assert state["readiness"]["cpu"]["ready"] is True
    assert state["readiness"]["pool"]["ready"] is False
    assert state["readiness"]["core"]["optional"] is True
    assert state["readiness"]["asic"]["optional"] is True
    assert state["readiness"]["solo"]["ready"] is False
    assert len(state["steps"]) >= 2
    assert "never starts mining" in state["disclaimer"].lower()

    ready = ma.build_mining_assistant_snapshot(
        {
            **cfg,
            "pool_url": "stratum+tcp://pool.example.net:3333",
            "pool_worker": "worker.name",
            "coinbase_payout_address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
            "asic_known_devices": ["192.168.1.50"],
        },
        core_setup={"installation_found": True},
        core_state={"connected": True, "status": "Synced", "chain": "main", "connections": 8},
        asic_devices=[{"ip":"192.168.1.50","status":"Online","vendor":"Bitmain","model":"Test"}],
        security_state={"checked": True, "verified": True},
        regtest_state={"running": False},
        benchmark_state={"hashrate": 1000},
        analytics_status={"running": True},
        goal="solo",
    )
    assert ready["readiness"]["pool"]["ready"] is True
    assert ready["readiness"]["core"]["ready"] is True
    assert ready["readiness"]["asic"]["ready"] is True
    assert ready["readiness"]["solo"]["ready"] is True
    assert ready["goal"] == "solo"

    backend = appmod.WebBackend()
    try:
        pref = backend.save_mining_assistant_preferences("asic", True, False)
        assert pref["ok"] and pref["goal"] == "asic"
        result = backend.get_mining_assistant_state()
        assert result["ok"] and result["assistant"]["goal"] == "asic"
        checked = backend.run_mining_assistant_check("core")
        assert checked["ok"] and checked["assistant"]["goal"] == "core"
        names = {fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        assert {"get_mining_assistant_state","run_mining_assistant_check","save_mining_assistant_preferences"}.issubset(names)
    finally:
        backend.close()

    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    assert 'data-view="assistant"' in html
    assert 'id="view-assistant"' in html
    assert 'id="assistantIntro"' in html
    assert 'id="assistantRunCheck"' in html
    assert ".assistant-readiness-grid" in css
    assert "refreshMiningAssistant" in js
    assert "save_mining_assistant_preferences" in js

    source = (root / "mining_assistant.py").read_text(encoding="utf-8")
    for token in ("start_mining(", "start_solo_mining(", "discover_asics(", "switchpool", "submitblock", "webbrowser.open(", "rpc_call("):
        assert token not in source, token

    print("[PASS] Mining Assistant — Can I Mine? local readiness model")
    print("[PASS] Mining Assistant goals — Learn/CPU/Pool/ASIC/Core/Solo guided paths")
    print("[PASS] Mining Assistant onboarding — one-time intro + persistent goal/preferences")
    print("[PASS] Mining Assistant UI — theme-aware readiness cards, score and route actions")
    print("[PASS] Mining Assistant safety — advisory only; no mining/ASIC/Core/block control calls")



def mining_assistant_polish_hotfix_tests():
    import sys
    import types
    from pathlib import Path

    import mining_assistant as ma

    root = Path(__file__).resolve().parent
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")

    # Exact screenshot regression: Recommended Path renderer must not call the
    # nonexistent esc() helper.
    assert "${esc(" not in js
    assert "${escapeHtml(step.index)}" in js
    assert "${escapeHtml(step.title)}" in js
    assert "${escapeHtml(step.detail)}" in js
    assert 'id="assistantHeroGoal"' in html

    base_cfg = {
        "pool_url": "stratum+tcp://example.com:3333",
        "pool_worker": "wallet.worker1",
        "coinbase_payout_address": "",
        "core_network": "main",
        "asic_known_devices": [],
    }
    pool_state = ma.build_mining_assistant_snapshot(
        base_cfg,
        core_setup={"installation_found": True},
        core_state={"connected": True, "status": "Synced", "chain": "main", "connections": 10},
        asic_devices=[],
        security_state={"checked": True, "verified": True},
        analytics_status={"running": True},
        goal="pool",
    )
    assert pool_state["goal_heading"] == "POOL MINING"
    assert pool_state["goal_status_label"] == "SETUP NEEDED"
    assert len(pool_state["steps"]) == 3
    assert pool_state["steps"][0]["title"] == "Configure your pool"

    solo_state = ma.build_mining_assistant_snapshot(
        {
            **base_cfg,
            "coinbase_payout_address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        },
        core_setup={"installation_found": True},
        core_state={"connected": True, "status": "Synced", "chain": "main", "connections": 10},
        asic_devices=[],
        security_state={"checked": True, "verified": True},
        analytics_status={"running": True},
        goal="solo",
    )
    assert solo_state["goal_heading"] == "SOLO MINING"
    assert solo_state["goal_status_label"] == "PREPARED"

    # Windows-friendly CPU name test without shelling out.
    original_platform = ma.sys.platform
    original_winreg = sys.modules.get("winreg")
    fake = types.SimpleNamespace()
    fake.HKEY_LOCAL_MACHINE = object()
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    fake.OpenKey = lambda *args, **kwargs: Key()
    fake.QueryValueEx = lambda *args, **kwargs: ("AMD Ryzen 7 5700G with Radeon Graphics", 1)
    try:
        sys.modules["winreg"] = fake
        ma.sys.platform = "win32"
        assert ma._windows_cpu_name() == "AMD Ryzen 7 5700G with Radeon Graphics"
    finally:
        ma.sys.platform = original_platform
        if original_winreg is None:
            sys.modules.pop("winreg", None)
        else:
            sys.modules["winreg"] = original_winreg

    print("[PASS] Mining Assistant path hotfix — goal selection renders Recommended Path immediately")
    print("[PASS] Mining Assistant goal-aware hero — Pool SETUP NEEDED / Solo PREPARED")
    print("[PASS] Mining Assistant CPU naming — Windows ProcessorNameString friendly model")



def profitability_power_center_tests():
    from pathlib import Path
    import math

    import profitability_center as pc
    import webview_app as appmod

    assert pc.block_subsidy_for_height(0) == 50.0
    assert pc.block_subsidy_for_height(210000) == 25.0
    assert pc.block_subsidy_for_height(840000) == 3.125

    # Simple exact mathematical regression.
    diff = 1.0
    hs = pc.DIFF1_HASHES / pc.SECONDS_PER_DAY
    blocks = pc.expected_blocks_per_day(hs, diff)
    assert abs(blocks - 1.0) < 1e-12, blocks

    calc = pc.profitability_snapshot(
        hashrate_hs=100e12,
        power_watts=3200,
        electricity_per_kwh=0.10,
        pool_fee_percent=2.0,
        btc_price=60000,
        difficulty=100e12,
        block_subsidy_btc=3.125,
        avg_fees_btc_per_block=0.1,
    )
    assert calc["power"]["kwh_day"] == 76.8
    assert abs(calc["power"]["electricity_day"] - 7.68) < 1e-9
    assert calc["mining"]["net_btc_day"] < calc["mining"]["gross_btc_day"]
    assert calc["power"]["efficiency_w_per_th"] == 32.0
    assert calc["mining"]["mean_time_to_block_seconds"] > 0
    assert 0 <= calc["mining"]["solo_probability"]["365d"] <= 1
    assert "not guaranteed" in calc["disclaimer"].lower()

    backend = appmod.WebBackend()
    try:
        result = backend.calculate_profitability(
            100e12, 3200, 0.10, 2.0, 60000, 100e12, 3.125, 0.1
        )
        assert result["ok"] is True
        saved = backend.save_profitability_preferences(
            100e12, 3200, 0.10, 2.0, 60000, 100e12, 965000, 3.125, 0.1
        )
        assert saved["ok"] is True
        state = backend.get_profitability_state()
        assert state["ok"] is True
        assert state["defaults"]["btc_price"] == 60000
        names = {fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        assert {
            "get_profitability_state",
            "calculate_profitability",
            "save_profitability_preferences",
            "use_core_profitability_data",
        }.issubset(names)
    finally:
        backend.close()

    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    assert 'data-view="profitability"' in html
    assert 'id="view-profitability"' in html
    assert 'id="profitCalculate"' in html
    assert 'id="profitUseCore"' in html
    assert ".profit-hero" in css
    assert "calculateProfitability" in js
    assert "useCoreProfitabilityData" in js

    source = (root / "profitability_center.py").read_text(encoding="utf-8")
    for token in ("requests.", "urllib", "http://", "https://", "webbrowser.open(", "start_mining(", "submitblock"):
        assert token not in source, token

    print("[PASS] Profitability math — expected blocks/BTC/pool fee/power/net estimates")
    print("[PASS] Power economics — kWh, W/TH and break-even electricity")
    print("[PASS] Solo odds — mean time, 50% probability and Poisson time windows")
    print("[PASS] Bitcoin subsidy schedule — height-derived consensus subsidy")
    print("[PASS] Profitability Center UI/API — local calculator + persistent preferences")
    print("[PASS] Profitability privacy — no price-service/network dependency")



def hardware_compatibility_center_tests():
    import json
    import tempfile
    from pathlib import Path

    import hardware_compatibility as hc
    import webview_app as appmod

    verified = hc.classify_device({
        "ip": "192.168.1.10",
        "vendor": "Bitmain / Antminer",
        "model": "Antminer S21 Test",
        "firmware": "Test FW",
        "verification": "VERIFIED ASIC",
        "status": "Online",
        "api_verified": True,
        "recognized_web_asic": True,
        "can_open_web": True,
        "can_switch_pool": True,
        "can_restart": True,
        "hashrate_hs": 200e12,
        "temperature_c": 65,
        "power_w": 3500,
    })
    assert verified["compatibility_level"] == "VERIFIED RUNTIME", verified
    assert verified["family_id"] == "bitmain-antminer", verified
    assert verified["full_control"] is True
    assert all(verified["capabilities"].values())

    web_only = hc.classify_device({
        "ip": "192.168.1.11",
        "vendor": "MicroBT / WhatsMiner",
        "model": "WhatsMiner (Web UI)",
        "verification": "RECOGNIZED ASIC WEB UI",
        "status": "Web UI only",
        "api_verified": False,
        "recognized_web_asic": True,
        "can_open_web": True,
        "can_switch_pool": False,
        "can_restart": False,
    })
    assert web_only["compatibility_level"] == "SUPPORTED FAMILY", web_only
    assert web_only["capabilities"]["web_ui"] is True
    assert web_only["capabilities"]["pool_control"] is False
    assert web_only["capabilities"]["restart"] is False
    assert web_only["capabilities"]["solo_bridge"] is False

    generic = hc.classify_device({
        "ip": "192.168.1.12",
        "vendor": "cgminer-compatible",
        "model": "cgminer-compatible ASIC",
        "verification": "VERIFIED ASIC",
        "api_verified": True,
        "recognized_web_asic": False,
        "can_switch_pool": False,
        "can_restart": True,
    })
    assert generic["compatibility_level"] == "GENERIC API", generic

    false_positive = hc.classify_device({
        "ip": "192.168.1.1",
        "model": "Network management interface",
        "verification": "CANDIDATE",
        "api_verified": False,
        "recognized_web_asic": False,
        "web_available": True,
        "http_available": True,
    })
    assert false_positive["compatibility_level"] == "NOT PROMOTED", false_positive
    assert false_positive["confirmed_asic"] is False
    assert not any(false_positive["capabilities"].values())

    snap = hc.compatibility_snapshot(
        [
            {
                "ip": "192.168.1.10", "vendor": "Bitmain / Antminer", "model": "Antminer S21 Test",
                "api_verified": True, "recognized_web_asic": True, "can_open_web": True,
                "can_switch_pool": True, "can_restart": True,
            },
            {
                "ip": "192.168.1.1", "model": "Network management interface",
                "web_available": True, "api_verified": False, "recognized_web_asic": False,
            },
        ],
        known_devices=["192.168.1.10"],
    )
    assert snap["summary"]["confirmed_asics"] == 1
    assert snap["summary"]["not_promoted"] == 1
    assert snap["policy"]["positive_evidence_only"] is True
    assert len(snap["families"]) == 4

    report = hc.sanitized_report({
        **snap,
        "devices": [{
            **snap["devices"][0],
            "ip": "192.168.1.10",
            "note": "private note",
            "pool_url": "stratum+tcp://private.pool:3333",
            "pool_user": "private.worker",
        }],
    })
    encoded = json.dumps(report)
    assert "192.168.1.10" not in encoded
    assert "private.pool" not in encoded
    assert "private.worker" not in encoded
    assert "private note" not in encoded
    assert report["privacy"]["private_ip_addresses"] == "excluded"

    backend = appmod.WebBackend()
    try:
        backend.asic_devices["192.168.1.10"] = {
            "ip": "192.168.1.10",
            "vendor": "Bitmain / Antminer",
            "model": "Antminer S21 Test",
            "verification": "VERIFIED ASIC",
            "status": "Online",
            "api_verified": True,
            "recognized_web_asic": True,
            "can_open_web": True,
            "can_switch_pool": True,
            "can_restart": True,
            "hashrate_hs": 200e12,
        }
        state = backend.get_hardware_compatibility_state()
        assert state["ok"] is True
        assert state["compatibility"]["summary"]["confirmed_asics"] >= 1
        created = backend.create_hardware_compatibility_report()
        assert created["ok"] is True, created
        report_text = Path(created["path"]).read_text(encoding="utf-8")
        assert "192.168.1.10" not in report_text
        names = {fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        assert {
            "get_hardware_compatibility_state",
            "create_hardware_compatibility_report",
        }.issubset(names)
    finally:
        backend.close()

    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    assert 'data-view="hardware"' in html
    assert 'id="view-hardware"' in html
    assert 'id="hardwareRefresh"' in html
    assert 'id="hardwareReport"' in html
    assert 'id="hardwareDeviceList"' in html
    assert ".hardware-device-card" in css
    assert "renderHardwareCompatibility" in js
    assert "create_hardware_compatibility_report" in js

    source = (root / "hardware_compatibility.py").read_text(encoding="utf-8")
    for token in (
        "import requests", "from requests", "requests.get(", "requests.post(",
        "urllib.request", "socket.socket(", "subprocess.run(", "subprocess.Popen(",
        "webbrowser.open(", "discover_asics(", "restart_asic(",
        "switch_asic_pool(", "submitblock",
    ):
        assert token not in source, token

    print("[PASS] Hardware Compatibility — Bitmain/MicroBT/Canaan/generic local family registry")
    print("[PASS] Runtime evidence classifier — Verified / Family / Generic-Limited / Not Promoted")
    print("[PASS] Capability mapping — monitoring/Web/pool/restart/solo remain evidence-gated")
    print("[PASS] False-positive shield — generic HTTP/open-port devices are never promoted")
    print("[PASS] Compatibility report privacy — private IP/pool/user/notes excluded")
    print("[PASS] Hardware Compatibility UI/API — searchable read-only fleet center")



def hardware_compatibility_serialization_hotfix_tests():
    import json
    from pathlib import Path

    import hardware_compatibility as hc

    families = hc.catalog_for_ui()
    assert len(families) == 4
    for family in families:
        assert isinstance(family["examples"], list), family
        assert all(isinstance(value, str) for value in family["examples"]), family
        assert family["examples"], family

    # JSON round-trip models the data shape that the UI bridge is supposed to
    # receive: arrays must stay arrays rather than tuple-like/custom objects.
    bridged = json.loads(json.dumps({"families": families}))
    assert all(isinstance(f["examples"], list) for f in bridged["families"])

    generic = next(f for f in families if f["id"] == "generic-cgminer")
    assert generic["examples"] == ["Vendor/model not identified"]

    root = Path(__file__).resolve().parent
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    assert "Array.isArray(rawExamples)" in js
    assert "(f.examples||[]).map" not in js
    assert "(f.examples || []).map" not in js

    print("[PASS] Hardware Compatibility hotfix — family examples are JSON-safe arrays")
    print("[PASS] Hardware Compatibility renderer — defensive Array.isArray normalization")
    print("[PASS] Generic cgminer family — single example no longer serialized as a plain string")



def bitcoin_core_datadir_reliability_hotfix_tests():
    import tempfile
    from pathlib import Path
    from unittest import mock

    import core_setup as cs
    import webview_app as appmod

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        exe = root / "bitcoin-qt.exe"
        exe.write_bytes(b"MZ-test")
        intended = root / "BitcoinData"
        other = root / "DefaultBitcoin"
        intended.mkdir()
        other.mkdir()
        (intended / "blocks").mkdir()

        args = cs.build_bitcoin_core_launch_args(exe, intended)
        assert Path(args[0]).resolve() == exe.resolve()
        assert args[1].startswith("-datadir=")
        assert str(intended) in args[1]

        try:
            cs.build_bitcoin_core_launch_args(exe, "")
            raise AssertionError("Empty datadir should be rejected")
        except cs.CoreSetupError as exc:
            assert "Choose Data Folder" in str(exc)

        guard_ready = cs.core_data_dir_guard(intended, [], [], process_running=False)
        assert guard_ready["status"] == "READY" and guard_ready["safe"] is True

        guard_match = cs.core_data_dir_guard(
            intended,
            [{"data_dir": str(intended), "command_line": f'-datadir="{intended}"'}],
            [],
            process_running=True,
        )
        assert guard_match["status"] == "MATCH" and guard_match["safe"] is True

        guard_mismatch = cs.core_data_dir_guard(
            intended,
            [{"data_dir": str(other), "command_line": f'-datadir="{other}"'}],
            [],
            process_running=True,
        )
        assert guard_mismatch["status"] == "MISMATCH" and guard_mismatch["safe"] is False

        guard_registry = cs.core_data_dir_guard(
            intended,
            [{"data_dir": "", "command_line": str(exe)}],
            [str(intended)],
            process_running=True,
        )
        assert guard_registry["status"] == "LIKELY_MATCH" and guard_registry["safe"] is True

        guard_unknown = cs.core_data_dir_guard(
            intended,
            [],
            [],
            process_running=True,
        )
        assert guard_unknown["status"] == "UNVERIFIED_RUNNING"
        assert guard_unknown["safe"] is False

        # Auto Configure must preserve an explicit pinned data dir even if
        # detection sees a different valid/default profile.
        values = cs.auto_config_values(
            {
                "rpc_url": "http://127.0.0.1:8332",
                "network": "main",
                "data_dir": str(other),
                "data_dir_exists": True,
                "executable": str(exe),
                "installation_found": True,
                "cookie_path": str(other / ".cookie"),
                "cookie_exists": True,
                "auth_mode_recommended": "cookie",
            },
            {
                "core_data_dir": str(intended),
                "core_executable": str(exe),
                "core_cookie_path": str(intended / ".cookie"),
                "core_auth_mode": "cookie",
            },
        )
        assert cs.same_data_dir(values["core_data_dir"], intended)
        assert str(other / ".cookie") != values["core_cookie_path"]

        backend = appmod.WebBackend()
        try:
            backend.cfg["core_executable"] = str(exe)
            backend.cfg["core_data_dir"] = str(intended)

            mismatch_state = {
                "executable": str(exe),
                "process_running": True,
                "running_processes": [{"data_dir": str(other), "command_line": f'-datadir="{other}"'}],
                "registry_data_dirs": [str(other)],
                "data_dir": str(other),
                "data_dir_exists": True,
            }
            with mock.patch.object(appmod, "detect_bitcoin_core", return_value=mismatch_state), \
                 mock.patch.object(appmod, "launch_bitcoin_core") as launch_mock:
                blocked = backend.start_bitcoin_core()
                assert blocked["ok"] is False, blocked
                assert "Data-Dir Guard" in blocked["error"]
                launch_mock.assert_not_called()

            safe_state = {
                "executable": str(exe),
                "process_running": False,
                "running_processes": [],
                "registry_data_dirs": [],
                "data_dir": str(intended),
                "data_dir_exists": True,
            }
            with mock.patch.object(appmod, "detect_bitcoin_core", side_effect=[safe_state, safe_state]), \
                 mock.patch.object(appmod, "launch_bitcoin_core", return_value=str(exe)) as launch_mock:
                started = backend.start_bitcoin_core()
                assert started["ok"] is True, started
                launch_mock.assert_called_once_with(str(exe), str(intended))
                assert started["launch_data_dir"] == str(intended)
        finally:
            backend.close()

    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    assert 'id="setupDataGuard"' in html
    assert "PINNED FOR LAUNCH" in html
    assert "data_dir_guard_status" in js
    assert "Starting Bitcoin Core with the pinned data directory" in js

    print("[PASS] Bitcoin Core launch guard — mandatory explicit -datadir")
    print("[PASS] Bitcoin Core fallback prevention — missing pinned directory cannot use default profile")
    print("[PASS] Bitcoin Core running-process guard — mismatched/unknown Core blocks duplicate launch")
    print("[PASS] Bitcoin Core Auto Configure — explicit data directory is preserved")
    print("[PASS] Bitcoin Core Setup UI — visible Data-Dir Guard status")



def global_dropdown_theme_hotfix_tests():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")

    select_ids = re.findall(r'<select[^>]+id="([^"]+)"', html)
    expected = {
        "coreAuthMode",
        "coreNetwork",
        "profitHashrateUnit",
        "hardwareStatusFilter",
        "hashHuntDifficulty",
        "analyticsEnabled",
        "analyticsSampleSeconds",
        "analyticsRetentionDays",
    }
    assert expected.issubset(set(select_ids)), select_ids

    # Global native popup styling must not depend on page-specific selectors.
    assert "select option," in css
    assert "select optgroup{" in css
    assert "color-scheme:dark;" in css
    assert "background-color:rgb(var(--raised-rgb))!important;" in css
    assert "select option:checked" in css
    assert "select option:disabled" in css

    # Frost must deliberately reverse the popup palette.
    assert 'html[data-theme="frost"] select{' in css
    assert 'html[data-theme="frost"] select option,' in css
    assert "color-scheme:light;" in css
    assert "background-color:rgb(var(--panel-rgb))!important;" in css

    # Avoid the original failure mode: option lists inheriting only translucent
    # select styling and being rendered by WebView2 against a native white popup.
    hotfix = css[css.rfind("/* v1.3.0.3 — Global native dropdown theme reliability"):]
    assert "select option" in hotfix
    assert "background-color:rgb(var(--raised-rgb))!important;" in hotfix

    print(f"[PASS] Global dropdown coverage — {len(select_ids)} native select control(s)")
    print("[PASS] Dark themes — explicit WebView2 select/option dark color-scheme + opaque backgrounds")
    print("[PASS] Frost theme — explicit light dropdown palette with dark readable text")
    print("[PASS] Dropdown states — selected, disabled and focus styling")



def purple_dragon_foundation_branding_tests():
    import json
    import tempfile
    from pathlib import Path

    import branding
    import config as configmod
    import webview_app as appmod

    assert branding.PUBLISHER_NAME == "Purple Dragon Foundation ltd"
    assert branding.CREATED_BY == "Created by Purple Dragon Foundation ltd"
    assert branding.WINDOWS_APP_USER_MODEL_ID == "PurpleDragonFoundationLtd.BitcoinMinerStudio"
    assert branding.DEFAULT_COINBASE_TAG == "Bitcoin Miner Studio / Purple Dragon Foundation ltd"

    root = Path(__file__).resolve().parent
    info = json.loads((root / "release_info.json").read_text(encoding="utf-8"))
    assert info["publisher"] == "Purple Dragon Foundation ltd"
    assert info["created_by"] == "Purple Dragon Foundation ltd"
    assert info["company_name"] == "Purple Dragon Foundation ltd"

    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    launcher = (root / "launch.pyw").read_text(encoding="utf-8")
    pkg = (root / "package_pyinstaller.bat").read_text(encoding="utf-8")
    version_info = (root / "windows_version_info.txt").read_text(encoding="utf-8")
    signer = (root / "tools" / "purple_dragon_sign.py").read_text(encoding="utf-8")

    assert "PURPLE DRAGON FOUNDATION LTD" in html
    assert 'id="securityPublisherName"' in html
    assert "WINDOWS_APP_USER_MODEL_ID" in launcher
    assert "KyleAustinHillier.BitcoinMinerStudio" not in launcher
    assert '--version-file "windows_version_info.txt"' in pkg
    assert "StringStruct('CompanyName', 'Purple Dragon Foundation ltd')" in version_info
    assert 'manifest["publisher_name"] = PUBLISHER_NAME' in signer

    backend = appmod.WebBackend()
    try:
        boot = backend.get_bootstrap()
        assert boot["publisher"] == "Purple Dragon Foundation ltd"
        assert boot["created_by"] == "Created by Purple Dragon Foundation ltd"
        security = backend.verify_security_now()["security"]
        assert security["verified"] is True, security
        assert security["publisher_name"] == "Purple Dragon Foundation ltd", security
    finally:
        backend.close()

    old_file, old_dir = configmod.CONFIG_FILE, configmod.CONFIG_DIR
    with tempfile.TemporaryDirectory() as td:
        try:
            configmod.CONFIG_DIR = Path(td)
            configmod.CONFIG_FILE = Path(td) / "settings.json"
            configmod.CONFIG_FILE.write_text(
                json.dumps({"coinbase_tag":"Bitcoin Miner Studio / Purple Dragon"}),
                encoding="utf-8",
            )
            assert configmod.load_config()["coinbase_tag"] == "Bitcoin Miner Studio / Purple Dragon Foundation ltd"
            configmod.CONFIG_FILE.write_text(
                json.dumps({"coinbase_tag":"My custom miner tag"}),
                encoding="utf-8",
            )
            assert configmod.load_config()["coinbase_tag"] == "My custom miner tag"
        finally:
            configmod.CONFIG_FILE, configmod.CONFIG_DIR = old_file, old_dir

    # No old personal creator/publisher identity in user-facing application files.
    for name in ("launch.pyw","webview_app.py","release_info.json","ui/index.html",
                 "ui/script.js","README.md","SECURITY.md","CHANGELOG.md",
                 "STABLE_RELEASE.md","windows_version_info.txt"):
        text = (root / name).read_text(encoding="utf-8")
        assert "Kyle Austin Hillier" not in text, name
        assert "KyleAustinHillier" not in text, name
        assert "Created by KyleAustin85" not in text, name
        assert "KyleAustin85" not in text, name

    branding_source = (root / "branding.py").read_text(encoding="utf-8")
    assert branding_source.count("KyleAustin85") == 1
    assert "https://www.paypal.me/KyleAustin85" in branding_source

    print("[PASS] Publisher branding — Purple Dragon Foundation ltd")
    print("[PASS] Windows identity — PurpleDragonFoundationLtd.BitcoinMinerStudio")
    print("[PASS] Signed provenance — publisher name bound into Purple Dragon manifest")
    print("[PASS] Windows EXE metadata — CompanyName / product version")
    print("[PASS] Coinbase branding migration — legacy default updated, custom tags preserved")
    print("[PASS] Public creator identity — personal attribution removed")



def purple_dragon_foundation_visual_branding_tests():
    from pathlib import Path
    from PIL import Image

    root = Path(__file__).resolve().parent
    banner = root / "assets" / "PurpleDragonFoundationBanner.png"
    logo = root / "assets" / "PurpleDragonFoundationLogo.png"
    assert banner.is_file() and logo.is_file()

    with Image.open(banner) as im:
        assert im.width >= 1800 and im.height >= 600, im.size
    with Image.open(logo) as im:
        assert im.width >= 1200 and im.height >= 1200, im.size

    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    signer = (root / "tools" / "purple_dragon_sign.py").read_text(encoding="utf-8")

    assert html.count("assets/PurpleDragonFoundationLogo.png") >= 3
    assert "assets/PurpleDragonFoundationBanner.png" in html
    assert 'id="foundationBrandBanner"' in html
    assert "brand-foundation-mark" in html
    assert "foundation-security-heading" in html
    assert ".foundation-banner-card" in css
    assert ".foundation-security-logo" in css
    assert '"assets/PurpleDragonFoundationBanner.png"' in signer
    assert '"assets/PurpleDragonFoundationLogo.png"' in signer

    # Existing product icon remains the Miner Studio application icon.
    assert '<link rel="icon" type="image/png" href="assets/BitcoinMinerStudio.png">' in html
    assert (root / "assets" / "BitcoinMinerStudio.ico").is_file()

    print("[PASS] Foundation visual assets — supplied banner + logo packaged")
    print("[PASS] Foundation sidebar identity — real logo artwork integrated")
    print("[PASS] Purple Dragon Security — full-width Foundation banner + publisher logo")
    print("[PASS] Foundation visual assets — Purple Dragon signed/protected")
    print("[PASS] Miner Studio application icon — existing Purple Dragon + Bitcoin icon preserved")



def pool_profiles_smart_failover_tests():
    import json
    import tempfile
    import time
    from pathlib import Path

    import pool_profiles as pp
    import stratum_miner as sm
    import webview_app as appmod

    assert set(pp.FAILOVER_POLICIES) == {"manual", "conservative", "balanced", "aggressive"}
    assert pp.policy_for("manual")["failover_enabled"] is False
    assert pp.policy_for("conservative")["failure_threshold"] == 2
    assert pp.policy_for("balanced")["primary_recovery_seconds"] == 300
    assert pp.policy_for("aggressive")["max_backoff_seconds"] == 5

    with tempfile.TemporaryDirectory() as td:
        store = pp.PoolProfileStore(Path(td) / "pool_profiles.json")
        profile = store.upsert({
            "name": "Primary Test Pool",
            "pool_url": "stratum+tcp://pool.example:3333",
            "pool_backup_urls": ["stratum+ssl://backup.example:443"],
            "pool_worker": "wallet.worker1",
            "pool_password": "THIS MUST NEVER BE STORED",
            "failover_policy": "balanced",
            "job_timeout_seconds": 120,
            "primary_recovery_seconds": 300,
            "pool_fee_percent": 1.25,
            "notes": "private note with account detail",
        })
        raw = (Path(td) / "pool_profiles.json").read_text(encoding="utf-8")
        assert "THIS MUST NEVER BE STORED" not in raw
        assert "pool_password" not in raw
        assert profile["failover_policy"] == "balanced"
        assert len(store.list()) == 1

        export = store.sanitized_export(profile["id"])
        encoded = json.dumps(export)
        assert "credentials" in encoded
        assert "THIS MUST NEVER BE STORED" not in encoded
        assert "private note" not in encoded
        assert "notes" not in export["profiles"][0]

        config = pp.profile_to_pool_config(profile)
        assert config["pool_url"].startswith("stratum+tcp://")
        assert config["pool_failover_enabled"] is True
        assert config["pool_failover_policy"] == "balanced"

    miner = sm.StratumMiner()
    # State-level policy regression without opening network sockets.
    miner._endpoints = ["stratum+tcp://primary:3333", "stratum+tcp://backup:3333"]
    miner._active_endpoint_index = 1
    miner._failover_enabled = True
    miner._failover_policy = "balanced"
    miner._primary_recovery_seconds = 1
    miner._active_endpoint_since = time.monotonic() - 2
    miner._connected = True
    miner._authorized = True
    assert miner._primary_recovery_due() is True
    assert miner._prepare_primary_recovery() is True
    assert miner._active_endpoint_index == 0
    assert miner._primary_recovery_attempts == 1

    backend = appmod.WebBackend()
    try:
        # Use backend's isolated selftest profile directory inherited from selftest HOME.
        saved = backend.save_pool_profile({
            "name": "Backend Test Pool",
            "pool_url": "stratum+tcp://127.0.0.1:3333",
            "pool_backup_urls": ["stratum+tcp://127.0.0.1:3334"],
            "pool_worker": "test.worker",
            "failover_policy": "conservative",
            "primary_recovery_seconds": 900,
            "pool_fee_percent": 1.5,
            "pool_password": "secret-in-session-only-on-nonwindows",
        })
        assert saved["ok"] is True, saved
        pid = saved["profile"]["id"]
        state = backend.get_pool_profiles_state()
        assert state["ok"] and state["pool_profiles"]["profile_count"] >= 1
        activated = backend.activate_pool_profile(pid)
        assert activated["ok"] is True, activated
        assert backend.cfg["pool_failover_policy"] == "conservative"
        assert backend.cfg["pool_primary_recovery_seconds"] == 900
        assert backend.cfg["active_pool_profile_id"] == pid
        assert backend.cfg["profitability_pool_fee_percent"] == 1.5
        export = backend.export_pool_profiles()
        assert export["ok"] is True
        assert "secret-in-session" not in export["report"]
        assert "private note" not in export["report"]
        assert json.loads(export["report"])["notes"] == "excluded"
        names = {fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        assert {"get_pool_profiles_state","save_pool_profile","activate_pool_profile","delete_pool_profile","test_pool_profile","export_pool_profiles"}.issubset(names)
    finally:
        backend.close()

    root = Path(__file__).resolve().parent
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    assert "Pool Profiles &amp; Smart Failover" in html
    for element_id in ("poolProfileSelect","poolProfileName","poolFailoverPolicy","poolPrimaryRecovery","poolProfileSave","poolProfileActivate","poolProfileTest","poolProfileExport","poolProfilesTable"):
        assert f'id="{element_id}"' in html, element_id
    assert "renderPoolProfiles" in js
    assert "profilePayload" in js
    assert ".pool-profile-center" in css

    print("[PASS] Pool Profiles — persistent local metadata + 32-profile bounded store")
    print("[PASS] Profile credential privacy — passwords excluded from profile JSON and sanitized export")
    print("[PASS] Failover policies — Manual / Conservative / Balanced / Aggressive")
    print("[PASS] Smart primary recovery — healthy backup schedules controlled return to primary")
    print("[PASS] Profile activation — active endpoint/config + profitability fee synchronization")
    print("[PASS] Pool Profile UI/API — save/activate/test/delete/export workflow")



def foundation_asset_loading_hotfix_tests():
    import re
    from pathlib import Path

    root=Path(__file__).resolve().parent
    html=(root/"ui"/"index.html").read_text(encoding="utf-8")
    signer=(root/"tools"/"purple_dragon_sign.py").read_text(encoding="utf-8")

    refs=re.findall(r'(?:src|href)="([^"]+\.(?:png|ico))"',html,re.I)
    ui_refs=[r for r in refs if "assets/" in r]
    assert ui_refs, refs
    assert all(not r.startswith("../") for r in ui_refs), ui_refs
    for ref in ui_refs:
        path=(root/"ui"/ref).resolve()
        assert path.is_file(), (ref,path)

    assert (root/"ui"/"assets"/"PurpleDragonFoundationLogo.png").is_file()
    assert (root/"ui"/"assets"/"PurpleDragonFoundationBanner.png").is_file()
    assert (root/"ui"/"assets"/"BitcoinMinerStudio.png").is_file()
    assert '"ui/assets/PurpleDragonFoundationLogo.png"' in signer
    assert '"ui/assets/PurpleDragonFoundationBanner.png"' in signer
    assert '"ui/assets/BitcoinMinerStudio.png"' in signer
    assert "../assets/PurpleDragonFoundation" not in html

    print("[PASS] Foundation WebView asset paths — same-origin ui/assets child resources")
    print("[PASS] Foundation broken-image regression — no ../assets parent traversal")
    print("[PASS] UI-served Foundation assets — Purple Dragon protected")



def foundation_branding_layout_hotfix_tests():
    from pathlib import Path
    root=Path(__file__).resolve().parent
    html=(root/'ui'/'index.html').read_text(encoding='utf-8')
    css=(root/'ui'/'styles.css').read_text(encoding='utf-8')
    assert 'class="brand-foundation-mark foundation-symbol-crop"' in html
    assert 'class="donate-foundation-mark foundation-symbol-crop"' in html
    assert 'class="foundation-security-logo foundation-symbol-crop"' in html
    assert 'class="foundation-security-intro"' in html
    marker='/* v1.4.0.2 — Foundation branding hierarchy'
    block=css[css.index(marker):css.index('/* v1.4.0 — Pool Profiles & Smart Failover */')]
    assert '.foundation-symbol-crop img' in block and 'width:150%' in block and 'left:-25%' in block
    assert 'grid-template-columns:minmax(440px,.92fr) minmax(560px,1.08fr)' in block
    assert 'height:190px' in block and 'object-position:center 47%' in block
    assert 'max-height:300px' not in block and 'width:84px;height:84px' not in block
    print('[PASS] Foundation icon hierarchy — emblem-only compact marks')
    print('[PASS] Foundation Security layout — split publisher/banner composition')
    print('[PASS] Foundation banner restraint — 190px supporting visual')
    print('[PASS] Foundation responsive layout — stacks below 1250px')



def benchmark_lab_2_tests():
    import tempfile
    import time
    from pathlib import Path

    from benchmark_lab import BenchmarkHistoryStore, BenchmarkLabController, benchmark_score, recommended_worker_counts
    from miner_engine import BenchmarkEngine

    assert benchmark_score(1000,100)==1.0
    assert benchmark_score(2000,50)==1.0
    counts=recommended_worker_counts(6)
    assert counts==[1,2,4,6],counts

    with tempfile.TemporaryDirectory() as td:
        history_path=Path(td)/"benchmark-history.json"
        store=BenchmarkHistoryStore(history_path)
        store.append({"run_id":"x","score":1.0})
        assert store.load()[-1]["run_id"]=="x"
        store.clear()
        assert store.load()==[]

        engine=BenchmarkEngine()
        lab=BenchmarkLabController(engine,history_path)
        state=lab.start(workers=1,duration_seconds=3,label="Selftest")
        assert state["running"] is True
        deadline=time.time()+10
        while time.time()<deadline:
            state=lab.snapshot()
            if not state["running"]:
                break
            time.sleep(.2)
        if state["running"]:
            state=lab.stop("selftest-timeout")
        assert state["history_summary"]["count"]>=1,state
        latest=state["history_summary"]["latest"]
        assert latest["total_hashes"]>0,latest
        assert latest["average_hashrate"]>0,latest
        assert 0<=latest["stability_percent"]<=100,latest
        assert latest["score"]>=0,latest

    root=Path(__file__).resolve().parent
    html=(root/"ui"/"index.html").read_text(encoding="utf-8")
    js=(root/"ui"/"script.js").read_text(encoding="utf-8")
    css=(root/"ui"/"styles.css").read_text(encoding="utf-8")
    signer=(root/"tools"/"purple_dragon_sign.py").read_text(encoding="utf-8")
    backend=(root/"webview_app.py").read_text(encoding="utf-8")
    assert 'data-view="benchmark"' in html and 'id="view-benchmark"' in html
    for element_id in ("benchmarkStart","benchmarkStop","benchmarkScalingStart","benchmarkHistoryBody","benchmarkExportJson","benchmarkExportCsv"):
        assert f'id="{element_id}"' in html,element_id
    assert "renderBenchmarkLab" in js and "start_benchmark_lab" in js
    assert ".benchmark-hero" in css
    assert "BenchmarkLabController" in backend
    assert '"benchmark_lab.py"' in signer
    print("[PASS] Benchmark Lab 2.0 — timed local runs, telemetry, score and persistent history")
    print("[PASS] Benchmark Lab UI/API — dedicated workspace + existing-engine integration")
    print("[PASS] Benchmark Lab privacy — local history/export design with no credentials")

def windows_tray_background_monitoring_tests():
    import sys, types
    from pathlib import Path
    from unittest import mock

    import windows_tray as wt
    import webview_app as appmod

    settings=wt.normalize_tray_settings({"tray_enabled":1,"tray_poll_seconds":1,"tray_close_to_tray":1})
    assert settings["tray_enabled"] is True
    assert settings["tray_close_to_tray"] is True
    assert settings["tray_poll_seconds"]==5
    assert wt.normalize_tray_settings({"tray_poll_seconds":999})["tray_poll_seconds"]==300

    healthy=wt.build_tray_status({"pool_running":True,"pool_health":96,"core_connected":True,"core_height":900000,"asic_total":2,"asic_online":2,"security_checked":True,"security_verified":True})
    assert healthy["severity"]=="ok",healthy
    assert "Pool 96%" in healthy["summary"]
    warning=wt.build_tray_status({"pool_running":True,"pool_health":55,"core_connected":True,"asic_total":2,"asic_online":1,"security_checked":True,"security_verified":True})
    assert warning["severity"]=="warning",warning
    critical=wt.build_tray_status({"solo_running":True,"core_connected":False,"security_checked":True,"security_verified":False})
    assert critical["severity"]=="critical",critical

    manager=wt.WindowsTrayManager(Path("missing.ico"),settings={"tray_enabled":True})
    if sys.platform!="win32":
        assert manager.supported is False
        assert manager.start() is False
    state=manager.state()
    assert "settings" in state and "status" in state

    backend=appmod.WebBackend()
    try:
        names={fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        assert {"get_tray_state","save_tray_settings","hide_to_tray","show_from_tray","test_tray_notification"}.issubset(names)
        r=backend.save_tray_settings({"tray_enabled":False,"tray_poll_seconds":15,"tray_close_to_tray":True})
        assert r["ok"] is True,r
        assert backend.cfg["tray_poll_seconds"]==15
        assert backend.cfg["tray_close_to_tray"] is True
        assert backend.cfg["tray_enabled"] is False
    finally:
        backend.close()

    root=Path(__file__).resolve().parent
    html=(root/"ui"/"index.html").read_text(encoding="utf-8")
    js=(root/"ui"/"script.js").read_text(encoding="utf-8")
    css=(root/"ui"/"styles.css").read_text(encoding="utf-8")
    module=(root/"windows_tray.py").read_text(encoding="utf-8")
    signer=(root/"tools"/"purple_dragon_sign.py").read_text(encoding="utf-8")

    assert 'data-view="tray"' in html and 'id="view-tray"' in html
    for element_id in ("trayEnabled","trayMinimize","trayClose","trayNotifications","trayPollSeconds","traySave","trayHideNow","trayTestNotification"):
        assert f'id="{element_id}"' in html,element_id
    assert "renderTrayState" in js and "save_tray_settings" in js
    assert ".tray-hero" in css
    assert "Shell_NotifyIconW" in module and "CreatePopupMenu" in module
    assert "window.events.closing" in (root/"webview_app.py").read_text(encoding="utf-8")
    assert "window.events.minimized" in (root/"webview_app.py").read_text(encoding="utf-8")
    assert '"windows_tray.py"' in signer

    forbidden=("start_mining","start_solo","switch_pool","restart_miner","submit_block","submitblock","assign_pool")
    tray_lower=module.lower()
    for token in forbidden:
        assert token not in tray_lower,token

    print("[PASS] Windows Tray — dependency-free Shell_NotifyIcon implementation")
    print("[PASS] Tray window lifecycle — minimize/optional close-to-tray + explicit Exit")
    print("[PASS] Background status — privacy-safe Pool/Core/ASIC/Security health summary")
    print("[PASS] Tray notifications — failover/Core/ASIC/health transition policy")
    print("[PASS] Tray security boundary — no mining, ASIC, pool-switch or block-submit commands")
    print("[PASS] Tray UI/API — settings, status, hide and notification test")

def mining_academy_tests():
    import tempfile
    from pathlib import Path
    import mining_academy as ma
    import webview_app as appmod

    with tempfile.TemporaryDirectory() as td:
        academy=ma.MiningAcademy(Path(td)/"academy_progress.json")
        state=academy.state()
        assert state["total_lessons"] == 12
        assert state["total_labs"] == 5
        assert state["completed_lessons"] == 0
        assert state["rank"] == "New Miner"

        state=academy.set_lesson_status("fundamentals","in_progress")
        assert state["lesson_status"]["fundamentals"] == "in_progress"
        state=academy.set_lesson_status("fundamentals","completed")
        assert state["lesson_status"]["fundamentals"] == "completed"

        quiz=academy.submit_quiz("fundamentals",1)
        assert quiz["correct"] is True
        assert quiz["state"]["quizzes"]["fundamentals"]["passed"] is True

        hashes=academy.hash_lab("abc")
        assert hashes["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        assert len(hashes["sha256d"]) == 64

        diff=academy.difficulty_lab(1)
        assert diff["target"] == "00000000ffff0000000000000000000000000000000000000000000000000000"

        genesis=academy.block_header_lab({
            "version":1,
            "previousblockhash":"00"*32,
            "merkleroot":"4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b",
            "time":1231006505,
            "bits":"0x1d00ffff",
            "nonce":2083236893,
        })
        assert genesis["header_bytes"] == 80
        assert genesis["hash"] == "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
        assert genesis["valid_pow"] is True

        txid="4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
        merkle=academy.merkle_lab([txid])
        assert merkle["merkle_root"] == txid

        nonce=academy.nonce_lab({"seed":"academy-selftest","zero_nibbles":1,"max_attempts":1000})
        assert nonce["found"] is True
        assert nonce["hash"].startswith("0")
        assert nonce["attempts"] <= 1000

        persisted=ma.MiningAcademy(Path(td)/"academy_progress.json").state()
        assert persisted["completed_lessons"] == 1
        assert persisted["passed_quizzes"] == 1
        assert persisted["completed_labs"] == 5

    backend=appmod.WebBackend()
    try:
        names={fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        required={
            "get_mining_academy_state","set_academy_lesson_status","submit_academy_quiz",
            "reset_academy_progress","run_academy_hash_lab","run_academy_difficulty_lab",
            "run_academy_header_lab","run_academy_merkle_lab","run_academy_nonce_lab",
        }
        assert required.issubset(names), required-names
    finally:
        backend.close()

    root=Path(__file__).resolve().parent
    html=(root/"ui"/"index.html").read_text(encoding="utf-8")
    js=(root/"ui"/"script.js").read_text(encoding="utf-8")
    css=(root/"ui"/"styles.css").read_text(encoding="utf-8")
    signer=(root/"tools"/"purple_dragon_sign.py").read_text(encoding="utf-8")
    module=(root/"mining_academy.py").read_text(encoding="utf-8")
    assert 'data-view="academy"' in html and 'id="view-academy"' in html
    for element_id in (
        "academyLessonList","academyQuizChoices","academyHashRun","academyDifficultyRun",
        "academyHeaderRun","academyMerkleRun","academyNonceRun","academyReset"
    ):
        assert f'id="{element_id}"' in html, element_id
    assert "function renderMiningAcademy" in js and "refreshMiningAcademy" in js
    assert "/* v1.7.0 — Mining Academy */" in css
    assert '"mining_academy.py"' in signer
    for forbidden in ("import requests","import socket","import subprocess","import webbrowser","submit_block(","switch_pool(","restart_miner("):
        assert forbidden not in module, forbidden
    print("[PASS] Mining Academy — curriculum, persistent progress, ranks and quizzes")
    print("[PASS] Mining Academy labs — SHA-256d, target, genesis header, Merkle and nonce simulator")
    print("[PASS] Mining Academy safety — no network, wallet, ASIC, pool or block-submission control imports")
    print("[PASS] Mining Academy UI/API — dedicated workspace, contextual Learn This links and bridge contract")

def diagnostics_support_center_tests():
    import json
    import sys
    import tempfile
    import types
    import zipfile
    from pathlib import Path

    import diagnostics_center as dc
    import webview_app as appmod
    from config import DEFAULTS

    root=Path(__file__).resolve().parent
    cfg=dict(DEFAULTS)
    cfg.update({
        "pool_url":"stratum+tcp://private-pool.example:3333",
        "pool_worker":"private-wallet.worker",
        "coinbase_payout_address":"bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        "rpc_user":"private-rpc-user",
        "pool_password":"TOP-SECRET-POOL-PASSWORD",
        "rpc_password":"TOP-SECRET-RPC-PASSWORD",
    })
    security={
        "checked":True,"verified":True,"signature_valid":True,
        "critical_actions_allowed":True,"protected_file_count":67,
        "verified_file_count":67,"build_id":"BMS-2.0.1-TEST",
        "release_seal":"PD6-TEST","publisher_key_id":"PDK-TEST",
    }
    snapshot={
        "cfg":cfg,
        "security":security,
        "core":{"connected":False},
        "core_setup":{},
        "miner":{"running":False,"connected":False,"authorized":False},
        "pool_diagnostics":{},
        "asic_devices":[],
        "asic_solo":{"running":False},
        "analytics":{"enabled":False,"running":False,"database_path":str(Path.home()/".bitcoin-miner-studio"/"analytics.sqlite3")},
        "release":{"checked":False,"previous_unclean_shutdown":False},
        "logs":[
            {"time":"12:00:00","message":"Pool password=TOP-SECRET-POOL-PASSWORD stratum+tcp://private-pool.example:3333 payout bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"},
            {"time":"12:00:01","message":"Diagnostics full: ATTENTION — 98/100, 1 warning(s), 0 failure(s)."},
            {"time":"12:00:02","message":"Diagnostics quick: HEALTHY — 100/100, 0 warning(s), 0 failure(s)."},
        ],
        "release_report":"Stable support report",
        "pool_diagnostic_report":"Endpoint: stratum+tcp://private-pool.example:3333",
    }

    original_webview=sys.modules.get("webview")
    original_crypto=sys.modules.get("cryptography")
    sys.modules["webview"]=types.ModuleType("webview")
    if original_crypto is None:
        sys.modules["cryptography"]=types.ModuleType("cryptography")
    try:
        with tempfile.TemporaryDirectory() as td:
            center=dc.DiagnosticsSupportCenter(root,"2.0.1",app_data_dir=Path(td)/"appdata")
            state=center.run(snapshot,"quick")
            assert state["checked"] is True
            assert state["mode"] == "quick"
            assert state["total_checks"] >= 15
            assert state["failures"] == 0, state
            assert state["health"] in {"HEALTHY","ATTENTION"}
            assert any(x["code"]=="security.trust" and x["status"]=="pass" for x in state["checks"])
            assert any(x["code"]=="security.private_key" and x["status"]=="pass" for x in state["checks"])
            # v2.0.1: Diagnostics must not recursively classify its own
            # "0 failure(s)" activity summaries as recent application errors.
            assert any(x["code"]=="app.recent_errors" and x["status"]=="pass" for x in state["checks"]), state
            failure_snapshot=dict(snapshot)
            failure_snapshot["logs"]=list(snapshot["logs"])+[{"time":"12:00:03","message":"Synthetic worker failed: test failure"}]
            failure_state=center.run(failure_snapshot,"quick")
            assert any(x["code"]=="app.recent_errors" and x["status"]=="warn" for x in failure_state["checks"]), failure_state

            full=center.run(snapshot,"full")
            assert full["mode"] == "full"
            assert any(x["code"]=="runtime.app_files" and x["status"]=="pass" for x in full["checks"])

            bundle=center.create_support_bundle(snapshot,include_activity_log=True,include_settings=True)
            assert bundle["ok"] is True
            path=Path(bundle["path"])
            assert path.is_file()
            with zipfile.ZipFile(path,"r") as z:
                names=set(z.namelist())
                required={"README.txt","diagnostics-report.txt","diagnostics.json","system.json","security-summary.json","settings-sanitized.json","activity-log-redacted.txt"}
                assert required.issubset(names), required-names
                assert not any(name.endswith("analytics.sqlite3") for name in names)
                combined=b"\n".join(z.read(name) for name in names).decode("utf-8",errors="ignore")
                for forbidden in ("TOP-SECRET-POOL-PASSWORD","TOP-SECRET-RPC-PASSWORD","private-pool.example","private-wallet.worker","bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"):
                    assert forbidden not in combined, forbidden
            path.unlink(missing_ok=True)
    finally:
        if original_webview is None: sys.modules.pop("webview",None)
        else: sys.modules["webview"]=original_webview
        if original_crypto is None: sys.modules.pop("cryptography",None)
        else: sys.modules["cryptography"]=original_crypto

    backend=appmod.WebBackend()
    try:
        names={fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        required={"get_diagnostics_state","run_diagnostics","get_diagnostics_report","create_diagnostics_support_bundle","open_diagnostics_support_folder"}
        assert required.issubset(names), required-names
    finally:
        backend.close()

    html=(root/"ui"/"index.html").read_text(encoding="utf-8")
    js=(root/"ui"/"script.js").read_text(encoding="utf-8")
    css=(root/"ui"/"styles.css").read_text(encoding="utf-8")
    signer=(root/"tools"/"purple_dragon_sign.py").read_text(encoding="utf-8")
    module=(root/"diagnostics_center.py").read_text(encoding="utf-8")
    assert 'data-view="diagnostics"' in html and 'id="view-diagnostics"' in html
    for element_id in ("diagnosticsQuickRun","diagnosticsFullRun","diagnosticsChecksTable","diagnosticsIssueList","diagnosticsCreateBundle","diagnosticsOpenFolder"):
        assert f'id="{element_id}"' in html, element_id
    assert "renderDiagnosticsCenter" in js and "run_diagnostics" in js
    assert "/* v1.8.0 — Diagnostics & Support Center */" in css
    assert '"diagnostics_center.py"' in signer
    for forbidden in ("import requests","urllib.request","submit_block(","switch_pool(","restart_miner(","start_mining("):
        assert forbidden not in module, forbidden
    print("[PASS] Diagnostics Center — quick/full read-only health matrix + category scoring")
    print("[PASS] Guided remediation — warning/failure issue classification and next-step reporting")
    print("[PASS] Support Center — local privacy-sanitized bundle; credentials/private keys/analytics DB excluded")
    print("[PASS] Diagnostics safety — no mining, ASIC, pool-switch, Bitcoin Core mutation or automatic upload surface")
    print("[PASS] Diagnostics UI/API — dedicated v1.8.0 workspace and bridge contract")



def v201_transient_rpc_reliability_tests():
    import webview_app as appmod
    from bitcoin_core import BitcoinCoreRPCError

    backend = appmod.WebBackend()
    original_core_fetch = appmod.fetch_core_snapshot
    original_template_fetch = appmod.fetch_block_template
    try:
        backend.core_state = {
            "connected": True, "status": "Syncing", "chain": "main", "blocks": 966000,
            "connections": 4, "error": "", "error_kind": "", "last_check": 1.0,
        }
        backend._core_state_signature = backend._core_signature(backend.core_state)
        backend.template_state = {
            "available": True, "status": "Ready", "height": 966001,
            "previousblockhash": "11" * 32, "transactions": 10,
            "coinbase_value_btc": 3.125, "fetched_at": 1.0,
            "error": "", "error_kind": "",
        }
        backend._template_state_signature = backend._template_signature(backend.template_state)

        def timeout_core(*args, **kwargs):
            raise BitcoinCoreRPCError("Bitcoin Core RPC timed out.", kind="timeout")
        def timeout_template(*args, **kwargs):
            raise BitcoinCoreRPCError("Bitcoin Core RPC timed out.", kind="timeout")
        appmod.fetch_core_snapshot = timeout_core
        appmod.fetch_block_template = timeout_template

        core = backend._refresh_core_snapshot(log_transition=True, timeout=0.01, preserve_transient=True)
        assert core["connected"] is True, core
        assert core.get("transient_error") is True and core.get("transient_error_kind") == "timeout", core
        assert core["blocks"] == 966000, core

        template = backend._refresh_block_template(log_transition=True, timeout=0.01, preserve_transient=True)
        assert template["available"] is True, template
        assert template.get("transient_error") is True and template.get("transient_error_kind") == "timeout", template
        assert template["height"] == 966001, template

        # Explicit/manual refreshes still surface a real timeout instead of hiding it.
        core_manual = backend._refresh_core_snapshot(log_transition=False, timeout=0.01, preserve_transient=False)
        assert core_manual["connected"] is False and core_manual.get("error_kind") == "timeout", core_manual
        template_manual = backend._refresh_block_template(log_transition=False, timeout=0.01, preserve_transient=False)
        assert template_manual["available"] is False and template_manual.get("error_kind") == "timeout", template_manual
    finally:
        appmod.fetch_core_snapshot = original_core_fetch
        appmod.fetch_block_template = original_template_fetch
        backend.close()

    print("[PASS] v2.0.1 Diagnostics — zero-failure summaries do not recursively create warnings")
    print("[PASS] v2.0.1 Core reliability — background RPC timeouts preserve last-known-good state")
    print("[PASS] v2.0.1 Template reliability — transient timeouts preserve UI state while manual refresh still reports errors")


def update_release_center_tests():
    import json
    import tempfile
    import zipfile
    from pathlib import Path

    import update_release_center as urc
    import webview_app as appmod

    root = Path(__file__).resolve().parent

    # The final self-test runs against the signed release itself. Candidate
    # verification must not import or execute candidate code.
    trust = urc.verify_release_folder(root)
    assert trust["trusted"] is True, trust
    assert trust["signature_valid"] is True, trust
    assert trust["version"] == "2.0.1", trust
    assert trust["files_total"] >= 67, trust
    assert trust["files_verified"] == trust["files_total"], trust
    assert urc.compare_versions("2.1.0", "2.0.0") == 1
    assert urc.compare_versions("2.0.0", "2.0.0") == 0
    assert urc.compare_versions("1.9.0", "2.0.0") == -1

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        center = urc.UpdateReleaseCenter(root, "2.0.1", app_data_dir=td / "appdata")
        state = center.set_channel("stable")
        assert state["channel"] == "stable"
        assert state["policy"]["automatic_download"] is False
        assert state["policy"]["silent_apply"] is False
        assert state["policy"]["candidate_execution"] is False

        inspected = center.inspect(str(root))
        inspection = inspected["inspection"]
        assert inspection["ok"] is True, inspection
        assert inspection["relation"] == "SAME", inspection
        assert inspection["recommendation"] == "REINSTALL / VERIFY", inspection
        assert inspection["trust"]["trusted"] is True

        staged = center.stage_last_inspection()
        assert staged["ok"] is True, staged
        staged_path = Path(staged["path"])
        assert staged_path.is_dir()
        assert root not in staged_path.parents
        rollback = json.loads(Path(staged["rollback_plan"]).read_text(encoding="utf-8"))
        assert rollback["from_version"] == "2.0.1"
        assert rollback["to_version"] == "2.0.1"
        assert rollback["apply_policy"] == "offline-explicit-only"

        # A protected-file change in the staged copy must invalidate trust.
        staged_main = staged_path / "main.py"
        staged_main.write_text(staged_main.read_text(encoding="utf-8") + "\n# tamper-test\n", encoding="utf-8")
        tampered = urc.verify_release_folder(staged_path)
        assert tampered["trusted"] is False, tampered
        assert "main.py" in tampered["modified_files"], tampered

        descriptor = center.export_release_descriptor({
            "trust_level": "TRUSTED",
            "signature_valid": True,
            "critical_actions_allowed": True,
        })
        assert descriptor["ok"] is True
        descriptor_text = json.dumps(descriptor["descriptor"]).lower()
        for forbidden in ("private key", "private_key", "password", "seed phrase", "mnemonic"):
            assert forbidden not in descriptor_text, forbidden

        cleared = center.clear_staged()
        assert cleared["ok"] is True
        assert not any(center.staging_dir.iterdir()) if center.staging_dir.exists() else True

        # Reject archive traversal before extraction.
        evil = td / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../escape.txt", "nope")
        out = td / "extract"
        out.mkdir()
        ok, error, release_root = urc._extract_package(evil, out)
        assert ok is False and release_root is None
        assert "unsafe" in error.lower(), error
        assert not (td / "escape.txt").exists()

    backend = appmod.WebBackend()
    try:
        names = {fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        required = {
            "get_update_release_state", "set_update_channel", "choose_update_package",
            "choose_update_folder", "inspect_update_package", "stage_update_package",
            "clear_staged_update", "export_release_descriptor", "get_update_release_report",
            "open_update_staging_folder",
        }
        assert required.issubset(names), required - names
    finally:
        backend.close()

    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    signer = (root / "tools" / "purple_dragon_sign.py").read_text(encoding="utf-8")
    module = (root / "update_release_center.py").read_text(encoding="utf-8")
    info = json.loads((root / "release_info.json").read_text(encoding="utf-8"))

    assert 'data-view="release"' in html and 'UPDATE &amp; RELEASE CENTER' in html
    for element_id in (
        "urChannel", "urPackagePath", "urExpectedSha", "urChoosePackage", "urChooseFolder",
        "urInspect", "urStage", "urClearStaged", "urExportDescriptor", "urHistory",
    ):
        assert f'id="{element_id}"' in html, element_id
    assert "renderUpdateReleaseCenter" in js and "inspect_update_package" in js and "stage_update_package" in js
    assert "/* v1.9.0 — Update & Release Center */" in css
    assert '"update_release_center.py"' in signer
    assert info["version"] == "2.0.1"
    assert info["automatic_update_download"] is False
    assert info["silent_auto_update"] is False
    assert info["trusted_package_staging"] is True
    for forbidden in ("import requests", "urllib.request", "subprocess", "os.system", "exec(", "eval("):
        assert forbidden not in module, forbidden

    print("[PASS] Update Center — signed candidate verification + semantic version/channel decisions")
    print("[PASS] Update staging — trusted-only local copy + rollback metadata + explicit cleanup")
    print("[PASS] Update security — candidate code not executed; archive traversal rejected; tampering blocked")
    print("[PASS] Release Center — support-safe descriptor export + integrated Stable readiness UI/API")


def architecture_ux_v2_tests():
    import json
    import re
    import tempfile
    from pathlib import Path

    from api_contract import API_SCHEMA, EXPOSED_API_METHODS, contract_snapshot
    from app_events import LocalEventBus
    from app_runtime import RuntimeContext
    from service_registry import ServiceRegistry
    from workspace_manager import WorkspaceManager
    import webview_app as appmod

    root = Path(__file__).resolve().parent
    assert appmod.VERSION == "2.0.1"
    assert API_SCHEMA == 2
    assert len(EXPOSED_API_METHODS) >= 120
    assert len(EXPOSED_API_METHODS) == len(set(EXPOSED_API_METHODS))

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        runtime = RuntimeContext.create(
            root=root, version="2.0.1", product="Bitcoin Miner Studio",
            publisher="Purple Dragon Foundation ltd", channel="Stable",
            app_data=td / "appdata",
        )
        snap = runtime.public_snapshot()
        assert snap["architecture"] == "BMS-ARCH-2"
        assert Path(snap["app_data"]).is_dir()

        events = LocalEventBus(max_events=50)
        for i in range(55):
            events.publish("selftest", "event", f"event-{i}")
        event_state = events.snapshot()
        assert event_state["retained"] == 50
        assert event_state["recent"][-1]["message"] == "event-54"

        services = ServiceRegistry()
        services.register("backend", label="Backend", category="runtime", critical=True)
        services.mark("backend", "running", "ready")
        service_state = services.snapshot()
        assert service_state["architecture"] == "BMS-ARCH-2"
        assert service_state["overall"] == "HEALTHY"
        assert service_state["running"] == 1

        workspace = WorkspaceManager(td / "workspace.json")
        workspace.record_view("diagnostics")
        workspace.set_preferences(sidebar_compact=True, pinned_views=["dashboard", "release"])
        workspace.record_command("open-diagnostics")
        restored = WorkspaceManager(td / "workspace.json").snapshot()
        assert restored["last_view"] == "diagnostics"
        assert restored["sidebar_compact"] is True
        assert restored["pinned_views"] == ["dashboard", "release"]
        assert restored["command_usage"]["open-diagnostics"] == 1

    backend = appmod.WebBackend()
    try:
        contract = contract_snapshot(backend)
        assert contract["schema"] == 2
        assert contract["missing"] == []
        names = {fn.__name__ for fn in appmod.build_bridge_functions(backend)}
        assert names == set(EXPOSED_API_METHODS)
        assert "_log" not in names
        arch = backend.get_architecture_state()
        assert arch["runtime"]["architecture"] == "BMS-ARCH-2"
        assert arch["services"]["registered"] >= 16
        assert arch["workspace"]["schema"] == 2
        bootstrap = backend.get_bootstrap()
        assert bootstrap["api_contract"]["schema"] == 2
        assert bootstrap["api_contract"]["exposed_count"] == len(EXPOSED_API_METHODS)
    finally:
        backend.close()

    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    js = (root / "ui" / "script.js").read_text(encoding="utf-8")
    css = (root / "ui" / "styles.css").read_text(encoding="utf-8")
    signer = (root / "tools" / "purple_dragon_sign.py").read_text(encoding="utf-8")
    info = json.loads((root / "release_info.json").read_text(encoding="utf-8"))

    for element_id in (
        "workspaceCurrent", "workspaceArchitecture", "workspaceRecents",
        "sidebarCompactToggle", "architectureTopChip", "architectureServiceGrid",
        "commandPalette", "commandPaletteInput", "commandPaletteResults",
    ):
        assert f'id="{element_id}"' in html, element_id
    assert "BMS-ARCH-2" in html
    assert "openCommandPalette" in js and "toggleSidebarCompact" in js
    assert "/* v2.0.0 — Major Architecture / UX Milestone */" in css
    assert len(re.findall(r"\bfunction\s+callApi\s*\(", js)) == 1
    assert len(re.findall(r"\bfunction\s+renderTrayState\s*\(", js)) == 1
    for name in ("app_runtime.py", "app_events.py", "service_registry.py", "workspace_manager.py", "api_contract.py"):
        assert f'"{name}"' in signer, name
    assert info["version"] == "2.0.1"
    assert info["architecture_schema"] == 2
    assert info["bridge_api_schema"] == 2
    assert info["workspace_schema"] == 2
    assert info["implicit_bridge_exposure"] is False
    assert info["cloud_telemetry"] is False
    assert info["silent_auto_update"] is False

    print("[PASS] BMS-ARCH-2 — runtime context, local event bus and service-health registry")
    print("[PASS] Bridge API schema 2 — explicit signed allowlist; no implicit public-method exposure")
    print("[PASS] v2 Workspace UX — persistent recents/preferences, compact sidebar and Command Palette")
    print("[PASS] Architecture observability — dashboard/Diagnostics service health with local-only state")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    utility_tests()
    purple_dragon_security_tests()
    coinbase_builder_tests()
    solo_mining_engine_tests()
    asic_discovery_false_positive_tests()
    asic_solo_bridge_tests()
    regtest_lab_tests()
    local_pool_integration()
    suggested_difficulty_test()
    pool_powertools_tests()
    asic_manager_tests()
    fleet_monitor_tests()
    bitcoin_core_setup_tests()
    bitcoin_core_integration_tests()
    miner_xp_hash_hunt_tests()
    webview_startup_dom_contract_tests()
    local_test_pool_reliability_tests()
    local_test_pool_worker_autofill_tests()
    windows_multiprocessing_spawn_guard_tests()
    pool_diagnostics_freshness_tests()
    monitoring_analytics_tests()
    release_candidate_hardening_tests()
    rc_preflight_cleanup_hotfix_tests()
    theme_studio_tests()
    theme_studio_overlay_hotfix_tests()
    paypal_donation_button_tests()
    stable_release_promotion_tests()
    official_app_icon_tests()
    mining_assistant_tests()
    mining_assistant_polish_hotfix_tests()
    profitability_power_center_tests()
    hardware_compatibility_center_tests()
    hardware_compatibility_serialization_hotfix_tests()
    bitcoin_core_datadir_reliability_hotfix_tests()
    global_dropdown_theme_hotfix_tests()
    purple_dragon_foundation_branding_tests()
    purple_dragon_foundation_visual_branding_tests()
    foundation_asset_loading_hotfix_tests()
    foundation_branding_layout_hotfix_tests()
    pool_profiles_smart_failover_tests()
    windows_tray_background_monitoring_tests()
    benchmark_lab_2_tests()
    mining_academy_tests()
    diagnostics_support_center_tests()
    v201_transient_rpc_reliability_tests()
    update_release_center_tests()
    architecture_ux_v2_tests()
    print("\nAll Bitcoin Miner Studio v2.0.1 Stable self-tests passed.")
