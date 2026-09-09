"""Bitcoin Miner Studio v0.4.7 Solo Mining Dashboard+ & Reliability engine.

Visible/local SHA-256d candidate-header search using a Bitcoin Core
getblocktemplate snapshot and a public coinbase payout address. This release
preserves target-valid candidate bundles for guarded block assembly and submission.
"""
import copy
import hashlib
import math
import threading
import time
from coinbase_builder import build_coinbase_transaction
from branding import DEFAULT_COINBASE_TAG

DIFFICULTY_1_TARGET = int("00000000ffff0000000000000000000000000000000000000000000000000000", 16)
UINT256_MAX = (1 << 256) - 1
NONCE_SPACE = 1 << 32

def probability_at_least_one(success_per_hash, hashes):
    """Probability of >=1 success after N independent hashes, computed stably."""
    p = max(0.0, min(1.0, float(success_per_hash or 0.0)))
    n = max(0.0, float(hashes or 0.0))
    if p <= 0.0 or n <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return max(0.0, min(1.0, -math.expm1(n * math.log1p(-p))))

def solo_probability_metrics(target_int, average_hashrate, total_hashes):
    """Return exact per-hash/session/window probability metrics for the target."""
    target = max(0, min(UINT256_MAX, int(target_int or 0)))
    rate = max(0.0, float(average_hashrate or 0.0))
    hashes = max(0, int(total_hashes or 0))
    success_per_hash = min(1.0, float(target + 1) / float(1 << 256)) if target >= 0 else 0.0

    expected_hashes = (1.0 / success_per_hash) if success_per_hash > 0 else 0.0
    expected_seconds = (expected_hashes / rate) if rate > 0 and expected_hashes > 0 else 0.0

    if 0.0 < success_per_hash < 1.0:
        hashes_50 = math.log(0.5) / math.log1p(-success_per_hash)
    elif success_per_hash >= 1.0:
        hashes_50 = 1.0
    else:
        hashes_50 = 0.0

    return {
        "success_per_hash": success_per_hash,
        "odds_one_in": expected_hashes,
        "expected_hashes": expected_hashes,
        "expected_seconds": expected_seconds,
        "hashes_to_50pct": hashes_50,
        "time_to_50pct": (hashes_50 / rate) if rate > 0 and hashes_50 > 0 else 0.0,
        "session_probability": probability_at_least_one(success_per_hash, hashes),
        "probability_1h": probability_at_least_one(success_per_hash, rate * 3600.0),
        "probability_24h": probability_at_least_one(success_per_hash, rate * 86400.0),
        "probability_7d": probability_at_least_one(success_per_hash, rate * 604800.0),
    }

class SoloMiningError(ValueError):
    pass

def _hash256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()

def _valid_hash_hex(value, label):
    value = str(value or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise SoloMiningError(f"{label} must be a 32-byte hexadecimal hash.")
    return value

def merkle_root_from_txids(txids):
    txids = list(txids or [])
    if not txids:
        raise SoloMiningError("At least one transaction ID is required for a merkle root.")
    level = [bytes.fromhex(_valid_hash_hex(txid, "Transaction ID"))[::-1] for txid in txids]
    while len(level) > 1:
        if len(level) & 1:
            level.append(level[-1])
        level = [_hash256(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0][::-1].hex()

def serialize_block_header(version, previous_block_hash, merkle_root, ntime, bits, nonce):
    previous_block_hash = _valid_hash_hex(previous_block_hash, "Previous block hash")
    merkle_root = _valid_hash_hex(merkle_root, "Merkle root")
    version = int(version) & 0xFFFFFFFF
    ntime = int(ntime) & 0xFFFFFFFF
    nonce = int(nonce)
    if not 0 <= nonce <= 0xFFFFFFFF:
        raise SoloMiningError("Nonce must be between 0 and 0xffffffff.")
    try:
        bits_int = int(str(bits), 16) if isinstance(bits, str) else int(bits)
    except (TypeError, ValueError) as exc:
        raise SoloMiningError("Compact bits is invalid.") from exc
    if not 0 <= bits_int <= 0xFFFFFFFF:
        raise SoloMiningError("Compact bits must fit in 32 bits.")
    return (version.to_bytes(4,"little") + bytes.fromhex(previous_block_hash)[::-1]
            + bytes.fromhex(merkle_root)[::-1] + ntime.to_bytes(4,"little")
            + bits_int.to_bytes(4,"little") + nonce.to_bytes(4,"little"))

def hash_header(header):
    header = bytes(header)
    if len(header) != 80:
        raise SoloMiningError("A Bitcoin block header must be exactly 80 bytes.")
    digest = _hash256(header)
    return digest[::-1].hex(), int.from_bytes(digest, "little")

def prepare_solo_work(template, payout_address, *, network="main", tag=DEFAULT_COINBASE_TAG, extranonce_size=8, extranonce_value=0, ntime=None):
    if not isinstance(template, dict) or not template.get("available"):
        raise SoloMiningError("A ready getblocktemplate is required before solo mining.")
    txids = list(template.get("_txids") or [])
    tx_count = int(template.get("transactions") or 0)
    if tx_count and (not template.get("_txids_complete") or len(txids) != tx_count):
        raise SoloMiningError("Current template has no complete internal txid set. Refresh Template in v0.4.4 and try again.")
    coinbase = build_coinbase_transaction(template, payout_address, network=network, tag=tag,
                                           extranonce_size=extranonce_size, extranonce_value=extranonce_value)
    merkle_root = merkle_root_from_txids([coinbase["txid"]] + txids)
    try: target_int = int(str(template.get("target_int") or "0"))
    except ValueError as exc: raise SoloMiningError("Template target is invalid.") from exc
    if target_int <= 0 or target_int > UINT256_MAX:
        raise SoloMiningError("Template target is outside the valid 256-bit range.")
    minimum_time = int(template.get("mintime") or 0); template_time = int(template.get("curtime") or 0)
    ntime = max(minimum_time, template_time, int(time.time())) if ntime is None else max(minimum_time, int(ntime))
    prefix = serialize_block_header(template.get("version"), template.get("previousblockhash"), merkle_root,
                                    ntime, template.get("bits"), 0)[:76]
    return {"height":int(template.get("height") or 0),"version":int(template.get("version") or 0),
            "previousblockhash":str(template.get("previousblockhash") or ""),"merkle_root":merkle_root,
            "ntime":int(ntime),"bits":str(template.get("bits") or ""),"target":str(template.get("target") or ""),
            "target_int":target_int,"difficulty":float(template.get("difficulty") or 0.0),"transactions":tx_count,
            "coinbase":coinbase,"header_prefix":prefix,"extranonce":int(extranonce_value)}

def search_nonce_batch(work, start_nonce, count):
    start_nonce=int(start_nonce); count=max(0,int(count))
    if not 0 <= start_nonce < NONCE_SPACE: raise SoloMiningError("Start nonce is outside the 32-bit nonce range.")
    count=min(count,NONCE_SPACE-start_nonce)
    if count<=0: return {"hashes":0,"best_hash":"","best_hash_int":UINT256_MAX,"best_nonce":start_nonce,"candidate":None}
    prefix=bytes(work["header_prefix"])
    if len(prefix)!=76: raise SoloMiningError("Prepared header prefix must be 76 bytes.")
    first=hashlib.sha256(); first.update(prefix); target=int(work["target_int"])
    best_int=UINT256_MAX; best_hash=""; best_nonce=start_nonce
    for nonce in range(start_nonce,start_nonce+count):
        h1=first.copy(); h1.update(nonce.to_bytes(4,"little")); digest=hashlib.sha256(h1.digest()).digest()
        value=int.from_bytes(digest,"little")
        if value<best_int:
            best_int=value; best_hash=digest[::-1].hex(); best_nonce=nonce
        if value<=target:
            header=prefix+nonce.to_bytes(4,"little")
            return {"hashes":nonce-start_nonce+1,"best_hash":best_hash,"best_hash_int":best_int,"best_nonce":best_nonce,
                    "candidate":{"hash":digest[::-1].hex(),"hash_int":value,"nonce":nonce,"header_hex":header.hex()}}
    return {"hashes":count,"best_hash":best_hash,"best_hash_int":best_int,"best_nonce":best_nonce,"candidate":None}

def unavailable_solo_state(message="Build a payout and start the local solo-mining engine when ready."):
    return {
        "running": False,
        "status": "Idle",
        "detail": message,
        "hashrate": 0.0,
        "average_hashrate": 0.0,
        "peak_hashrate": 0.0,
        "total_hashes": 0,
        "uptime": 0.0,
        "work_height": 0,
        "previousblockhash": "",
        "merkle_root": "",
        "target": "",
        "target_int": "",
        "network_difficulty": 0.0,
        "transactions": 0,
        "nonce": 0,
        "extranonce": 0,
        "extranonce_rolls": 0,
        "best_hash": "",
        "best_hash_int": "",
        "best_nonce": 0,
        "best_difficulty": 0.0,
        "target_ratio": 0.0,
        "expected_hashes": 0.0,
        "expected_seconds": 0.0,
        "hashes_to_50pct": 0.0,
        "time_to_50pct": 0.0,
        "success_per_hash": 0.0,
        "odds_one_in": 0.0,
        "session_probability": 0.0,
        "probability_1h": 0.0,
        "probability_24h": 0.0,
        "probability_7d": 0.0,
        "candidate_found": False,
        "candidate_hash": "",
        "candidate_nonce": 0,
        "candidate_header": "",
        "candidate_found_at": 0.0,
        "coinbase_txid": "",
        "coinbase_raw": "",
        "auto_new_template": True,
        "batch_size": 0,
        "extranonce_roll_hashes": 0,
        "template_update_pending": False,
        "template_switches": 0,
        "last_template_switch_at": 0.0,
        "work_age_seconds": 0.0,
        "stale_batches_discarded": 0,
        "stale_hashes_discarded": 0,
        "stale_candidates_rejected": 0,
        "hashrate_history": [],
        "best_history": [],
        "submit_enabled": False,
        "error": "",
    }


class SoloMiningEngine:
    """Responsive one-lane reference CPU miner using cooperative batch yields."""
    def __init__(self,event_callback=None):
        self._lock=threading.RLock(); self._stop=threading.Event(); self._thread=None; self._event_callback=event_callback
        self._state=unavailable_solo_state(); self._settings={}; self._template=None; self._pending_template=None
        self._candidate_bundle=None
        self._hashrate_history=[]; self._best_history=[]
        self._work_started_at=0.0; self._last_history_at=0.0
        self._started_at=0.0; self._last_rate_at=0.0; self._last_rate_hashes=0
    @property
    def running(self):
        with self._lock: return bool(self._state.get("running"))
    def _emit(self,kind,payload):
        if self._event_callback:
            try:self._event_callback(kind,payload)
            except Exception:pass
    def work_identity(self):
        with self._lock:return (int(self._state.get("work_height") or 0),str(self._state.get("previousblockhash") or ""))
    def update_template(self,template):
        if not isinstance(template,dict) or not template.get("available"):return False
        with self._lock:
            if not self._state.get("running"):return False
            current=(int(self._state.get("work_height") or 0),str(self._state.get("previousblockhash") or ""))
            incoming=(int(template.get("height") or 0),str(template.get("previousblockhash") or ""))
            if incoming==current:return False
            self._pending_template=dict(template)
            self._state["template_update_pending"]=True
            self._state["detail"]=f"New block template at height {incoming[0]:,}; current batch will be discarded and work will switch."
        self._emit("work_switch",{"height":incoming[0]});return True
    def start(self,template,payout_address,*,network="main",tag=DEFAULT_COINBASE_TAG,extranonce_size=8,batch_size=20000,extranonce_roll_hashes=2000000,auto_new_template=True):
        if self.running:raise SoloMiningError("Solo mining is already running.")
        batch_size=max(500,min(250000,int(batch_size))); extranonce_roll_hashes=max(batch_size,min(50000000,int(extranonce_roll_hashes)))
        initial=prepare_solo_work(template,payout_address,network=network,tag=tag,extranonce_size=extranonce_size,extranonce_value=0)
        with self._lock:
            self._settings={"payout_address":str(payout_address),"network":str(network),"tag":str(tag),"extranonce_size":int(extranonce_size),
                            "batch_size":batch_size,"extranonce_roll_hashes":extranonce_roll_hashes,"auto_new_template":bool(auto_new_template)}
            self._template=dict(template);self._pending_template=None;self._candidate_bundle=None
            self._hashrate_history=[];self._best_history=[]
            self._stop.clear();self._started_at=time.time();self._work_started_at=self._started_at
            self._last_rate_at=self._started_at;self._last_history_at=self._started_at;self._last_rate_hashes=0
            self._state=unavailable_solo_state();self._state.update({
                "running":True,"status":"Running",
                "detail":"Searching current-template SHA-256d headers with stale-work protection enabled.",
                "work_height":initial["height"],"previousblockhash":initial["previousblockhash"],"merkle_root":initial["merkle_root"],
                "target":initial["target"],"target_int":str(initial["target_int"]),
                "network_difficulty":initial["difficulty"],"transactions":initial["transactions"],
                "coinbase_txid":initial["coinbase"]["txid"],"coinbase_raw":initial["coinbase"]["raw_transaction"],
                "auto_new_template":bool(auto_new_template),"batch_size":batch_size,
                "extranonce_roll_hashes":extranonce_roll_hashes
            })
        self._thread=threading.Thread(target=self._run,name="SoloMiningEngine",daemon=True);self._thread.start();self._emit("started",{"height":initial["height"]});return self.stats()
    def stop(self,reason="Stopped by user."):
        self._stop.set();thread=self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():thread.join(timeout=2.0)
        with self._lock:
            if self._state.get("status")!="Candidate Found":self._state["status"]="Stopped";self._state["detail"]=reason
            self._state["running"]=False
        self._emit("stopped",{"reason":reason});return self.stats()
    def reset_stats(self):
        with self._lock:
            running=bool(self._state.get("running"))
            cur=dict(self._state)
            candidate=bool(cur.get("candidate_found"))
            keep_keys=(
                "work_height","previousblockhash","merkle_root","target","target_int",
                "network_difficulty","transactions","nonce","extranonce","coinbase_txid",
                "coinbase_raw","auto_new_template","batch_size","extranonce_roll_hashes",
                "candidate_found","candidate_hash","candidate_nonce","candidate_header",
                "candidate_found_at","submit_enabled"
            )
            keep={k:cur.get(k) for k in keep_keys}
            self._started_at=time.time()
            self._last_rate_at=self._started_at
            self._last_rate_hashes=0
            self._last_history_at=self._started_at
            self._hashrate_history=[]
            self._best_history=[]
            fresh=unavailable_solo_state()
            fresh.update(keep)
            fresh["running"]=running
            if candidate:
                fresh["status"]="Candidate Found"
                fresh["detail"]="Statistics reset; the target-valid candidate remains preserved for guarded submission."
            else:
                fresh["status"]="Running" if running else "Idle"
                fresh["detail"]="Solo mining statistics reset; candidate search continues." if running else "Solo mining statistics reset."
            self._state=fresh
        return self.stats()

    def _build_work(self,template,extranonce):
        st=dict(self._settings);return prepare_solo_work(template,st["payout_address"],network=st["network"],tag=st["tag"],extranonce_size=st["extranonce_size"],extranonce_value=extranonce)
    def _set_work_state(self,work,nonce,extranonce):
        with self._lock:self._state.update({"work_height":work["height"],"previousblockhash":work["previousblockhash"],"merkle_root":work["merkle_root"],"target":work["target"],"target_int":str(work["target_int"]),"network_difficulty":work["difficulty"],"transactions":work["transactions"],"nonce":int(nonce),"extranonce":int(extranonce),"coinbase_txid":work["coinbase"]["txid"],"coinbase_raw":work["coinbase"]["raw_transaction"]})
    def _update_rates(self):
        now=time.time()
        with self._lock:
            hashes=int(self._state.get("total_hashes") or 0)
            elapsed=max(.000001,now-self._started_at) if self._started_at else 0.0
            self._state["uptime"]=elapsed
            self._state["work_age_seconds"]=max(0.0,now-self._work_started_at) if self._work_started_at else 0.0
            self._state["average_hashrate"]=hashes/elapsed if elapsed else 0.0
            since=now-self._last_rate_at if self._last_rate_at else 0.0
            if since>=.25:
                rate=(hashes-self._last_rate_hashes)/max(since,.000001)
                self._state["hashrate"]=rate
                self._state["peak_hashrate"]=max(float(self._state.get("peak_hashrate") or 0),rate)
                self._last_rate_at=now
                self._last_rate_hashes=hashes

            avg=float(self._state.get("average_hashrate") or 0)
            try:
                target_int=int(str(self._state.get("target_int") or self._template.get("target_int") or "0"))
            except Exception:
                target_int=0
            metrics=solo_probability_metrics(target_int,avg,hashes)
            self._state.update(metrics)

            if now-self._last_history_at>=1.0:
                self._hashrate_history.append({
                    "t": round(elapsed,3),
                    "h": float(self._state.get("hashrate") or 0.0),
                })
                self._hashrate_history=self._hashrate_history[-90:]
                self._last_history_at=now
            self._state["hashrate_history"]=copy.deepcopy(self._hashrate_history)
            self._state["best_history"]=copy.deepcopy(self._best_history)

    def _record_batch(self,result,next_nonce):
        with self._lock:
            self._state["total_hashes"]=int(self._state.get("total_hashes") or 0)+int(result["hashes"])
            self._state["nonce"]=int(next_nonce)&0xffffffff
            best_int=int(result.get("best_hash_int") or UINT256_MAX)
            prev=self._state.get("best_hash_int")
            prev=int(prev) if str(prev or "").isdigit() else UINT256_MAX
            if result.get("best_hash") and best_int<prev:
                target=int(self._template.get("target_int") or 0)
                difficulty=float(DIFFICULTY_1_TARGET/best_int) if best_int>0 else math.inf
                ratio=float(target/best_int) if best_int>0 and target>0 else 0.0
                self._state["best_hash"]=result["best_hash"]
                self._state["best_hash_int"]=str(best_int)
                self._state["best_nonce"]=int(result.get("best_nonce") or 0)
                self._state["best_difficulty"]=difficulty
                self._state["target_ratio"]=ratio
                self._best_history.append({
                    "time": time.time(),
                    "height": int(self._state.get("work_height") or 0),
                    "hash": result["best_hash"],
                    "nonce": int(result.get("best_nonce") or 0),
                    "difficulty": difficulty,
                    "target_ratio": ratio,
                })
                self._best_history=self._best_history[-8:]
                self._state["best_history"]=copy.deepcopy(self._best_history)

    def _record_stale_batch(self,result,next_nonce):
        with self._lock:
            count=int(result.get("hashes") or 0)
            self._state["total_hashes"]=int(self._state.get("total_hashes") or 0)+count
            self._state["nonce"]=int(next_nonce)&0xffffffff
            self._state["stale_batches_discarded"]=int(self._state.get("stale_batches_discarded") or 0)+1
            self._state["stale_hashes_discarded"]=int(self._state.get("stale_hashes_discarded") or 0)+count

    def _record_candidate(self,result,work):
        c=result["candidate"]
        with self._lock:
            if self._pending_template is not None or self._state.get("template_update_pending"):
                self._state["stale_candidates_rejected"]=int(self._state.get("stale_candidates_rejected") or 0)+1
                self._state["detail"]="A candidate was found on superseded work and was rejected before preservation."
                return False
            self._candidate_bundle={"template":copy.deepcopy(self._template),"work":copy.deepcopy(work),"candidate":copy.deepcopy(c)}
            self._state.update({
                "running":False,"status":"Candidate Found",
                "detail":"A target-valid header was found and preserved for guarded block assembly, proposal validation, and submission.",
                "candidate_found":True,"candidate_hash":c["hash"],"candidate_nonce":int(c["nonce"]),
                "candidate_header":c["header_hex"],"candidate_found_at":time.time(),
                "best_hash":c["hash"],"best_hash_int":str(c["hash_int"]),"best_nonce":int(c["nonce"]),
                "best_difficulty":float(DIFFICULTY_1_TARGET/c["hash_int"]) if c["hash_int"]>0 else math.inf,
                "target_ratio":float(work["target_int"]/c["hash_int"]) if c["hash_int"]>0 else math.inf,
                "coinbase_txid":work["coinbase"]["txid"],"coinbase_raw":work["coinbase"]["raw_transaction"],
                "submit_enabled":True
            })
        self._stop.set()
        self._emit("candidate",{"height":work["height"],"hash":c["hash"],"nonce":c["nonce"]})
        return True

    def _run(self):
        extranonce=0;nonce=0;hashed_for_extra=0
        try:
            template=dict(self._template)
            work=self._build_work(template,extranonce)
            self._set_work_state(work,nonce,extranonce)
            while not self._stop.is_set():
                pending=None
                with self._lock:
                    if self._pending_template is not None:
                        pending=dict(self._pending_template)
                        self._pending_template=None
                if pending is not None:
                    template=pending
                    with self._lock:
                        self._template=dict(template)
                        self._state["template_update_pending"]=False
                        self._state["template_switches"]=int(self._state.get("template_switches") or 0)+1
                        self._state["last_template_switch_at"]=time.time()
                    self._work_started_at=time.time()
                    extranonce=0;nonce=0;hashed_for_extra=0
                    work=self._build_work(template,extranonce)
                    self._set_work_state(work,nonce,extranonce)
                    self._emit("work_switched",{"height":work["height"]})

                batch=int(self._settings["batch_size"])
                roll=int(self._settings["extranonce_roll_hashes"])
                count=min(batch,max(1,roll-hashed_for_extra),NONCE_SPACE-nonce)
                result=search_nonce_batch(work,nonce,count)
                next_nonce=nonce+int(result["hashes"])

                # A new chain-tip template may arrive while search_nonce_batch is
                # executing. Never preserve or score a result from superseded work.
                with self._lock:
                    superseded=self._pending_template is not None or bool(self._state.get("template_update_pending"))
                if superseded:
                    if result.get("candidate"):
                        with self._lock:
                            self._state["stale_candidates_rejected"]=int(self._state.get("stale_candidates_rejected") or 0)+1
                    self._record_stale_batch(result,next_nonce)
                    self._update_rates()
                    continue

                self._record_batch(result,next_nonce)
                self._update_rates()
                if result.get("candidate"):
                    if self._record_candidate(result,work):
                        break
                    continue

                nonce=next_nonce
                hashed_for_extra+=int(result["hashes"])
                if nonce>=NONCE_SPACE or hashed_for_extra>=roll:
                    extranonce=(extranonce+1)%(1<<(8*int(self._settings["extranonce_size"])))
                    nonce=0;hashed_for_extra=0
                    with self._lock:
                        self._state["extranonce_rolls"]=int(self._state.get("extranonce_rolls") or 0)+1
                        self._state["extranonce"]=extranonce
                    work=self._build_work(template,extranonce)
                    self._set_work_state(work,nonce,extranonce)
                time.sleep(.001)
        except Exception as exc:
            with self._lock:
                self._state["running"]=False
                self._state["status"]="Error"
                self._state["detail"]=str(exc)
                self._state["error"]=str(exc)
            self._emit("error",str(exc))
        finally:
            self._update_rates()
            with self._lock:
                if self._state.get("running"):
                    self._state["running"]=False

    def candidate_bundle(self):
        with self._lock:
            return copy.deepcopy(self._candidate_bundle)

    def clear_candidate(self):
        with self._lock:
            self._candidate_bundle=None
            self._state["candidate_found"]=False
            self._state["candidate_hash"]=""
            self._state["candidate_nonce"]=0
            self._state["candidate_header"]=""
            self._state["candidate_found_at"]=0.0
            self._state["submit_enabled"]=False
        return self.stats()

    def stats(self):
        self._update_rates()
        with self._lock:
            state=dict(self._state)
            state["hashrate_history"]=copy.deepcopy(self._hashrate_history)
            state["best_history"]=copy.deepcopy(self._best_history)
            return state

def solo_mining_report(state):
    state=dict(state or {})
    if state.get("candidate_found"):
        return (
            "SOLO MINING CANDIDATE FOUND\n\n"
            f"Height: {int(state.get('work_height') or 0):,}\n"
            f"Hash: {state.get('candidate_hash')}\n"
            f"Nonce: {int(state.get('candidate_nonce') or 0):,}\n"
            f"Extranonce: {int(state.get('extranonce') or 0):,}\n"
            f"Header: {state.get('candidate_header')}\n\n"
            "Candidate is preserved for guarded block assembly, Bitcoin Core proposal validation, and controlled submission."
        )
    return (
        "SOLO MINING ENGINE\n\n"
        f"Status: {state.get('status','Idle')}\n"
        f"Work height: {int(state.get('work_height') or 0):,}\n"
        f"Hashrate: {float(state.get('hashrate') or 0):,.0f} H/s\n"
        f"Average: {float(state.get('average_hashrate') or 0):,.0f} H/s\n"
        f"Total hashes: {int(state.get('total_hashes') or 0):,}\n"
        f"Best difficulty: {float(state.get('best_difficulty') or 0):.8g}\n"
        f"Target ratio: {float(state.get('target_ratio') or 0):.8g}\n"
        f"Session success probability: {float(state.get('session_probability') or 0):.8g}\n"
        f"Expected time: {float(state.get('expected_seconds') or 0):.8g} sec\n"
        f"Template switches: {int(state.get('template_switches') or 0):,}\n"
        f"Stale batches discarded: {int(state.get('stale_batches_discarded') or 0):,}\n"
        f"Stale candidates rejected: {int(state.get('stale_candidates_rejected') or 0):,}\n\n"
        "Current-template stale-work guards are active while automatic template switching is enabled."
    )

