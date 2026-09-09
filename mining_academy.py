"""Bitcoin Miner Studio v1.7.0 — Mining Academy.

Local-only educational curriculum, progress tracking, quizzes and deterministic
Bitcoin mining labs. The module has no wallet, pool, ASIC, RPC or block-submit
capabilities and is safe to use while live mining services are configured.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import threading
import time
from pathlib import Path

SCHEMA = 1
MAX_NONCE_ATTEMPTS = 250_000
DIFF1_BITS = 0x1D00FFFF


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256d(data: bytes) -> bytes:
    return sha256(sha256(data))


def compact_to_target(bits: int) -> int:
    bits = int(bits) & 0xFFFFFFFF
    exponent = bits >> 24
    mantissa = bits & 0x007FFFFF
    if bits & 0x00800000:
        raise ValueError("Negative compact targets are not valid in Mining Academy.")
    if exponent <= 3:
        target = mantissa >> (8 * (3 - exponent))
    else:
        target = mantissa << (8 * (exponent - 3))
    if target <= 0 or target >= 1 << 256:
        raise ValueError("Compact target is outside the 256-bit Proof-of-Work range.")
    return target


DIFF1_TARGET = compact_to_target(DIFF1_BITS)


def difficulty_to_target(difficulty: float) -> int:
    difficulty = float(difficulty)
    if not math.isfinite(difficulty) or difficulty <= 0:
        raise ValueError("Difficulty must be a finite number greater than zero.")
    target = max(1, int(DIFF1_TARGET / difficulty))
    return min((1 << 256) - 1, target)


def _hex32(value: str, field: str) -> str:
    value = str(value or "").strip().lower()
    if value.startswith("0x"):
        value = value[2:]
    if len(value) != 64:
        raise ValueError(f"{field} must contain exactly 64 hexadecimal characters.")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal.") from exc
    return value


def _parse_bits(value) -> int:
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw.startswith("0x"):
            return int(raw, 16)
        if any(ch in "abcdef" for ch in raw):
            return int(raw, 16)
        return int(raw)
    return int(value)


LESSONS = [
    {
        "id": "fundamentals",
        "track": "Fundamentals",
        "level": "Beginner",
        "title": "What Bitcoin Mining Does",
        "summary": "Connect transactions, blocks, Proof of Work and miner incentives into one mental model.",
        "objectives": ["Explain why miners build candidate blocks", "Distinguish validation from hashing", "Describe why Proof of Work makes history costly to rewrite"],
        "sections": [
            {"heading": "The job", "text": "A miner builds a candidate block from valid transactions, commits to that block with a header, and repeatedly hashes header variants while searching for a value at or below the network target."},
            {"heading": "Consensus boundary", "text": "Mining does not let a miner invent arbitrary valid transactions or rewards. Every full node independently validates the block against Bitcoin consensus rules."},
        ],
        "quiz": {"question": "What makes a mined Bitcoin block acceptable to a validating node?", "choices": ["Only a high hashrate", "Consensus-valid data plus sufficient Proof of Work", "A pool account", "A large transaction fee"], "answer": 1, "explanation": "A block must satisfy consensus rules and its header hash must meet the current Proof-of-Work target."},
    },
    {
        "id": "sha256d",
        "track": "Cryptography",
        "level": "Beginner",
        "title": "SHA-256 and SHA-256d",
        "summary": "See how Bitcoin applies SHA-256 twice and why tiny input changes produce unrelated-looking outputs.",
        "objectives": ["Recognize a 256-bit hash", "Explain the avalanche effect", "Identify SHA-256d as double SHA-256"],
        "sections": [
            {"heading": "Hash functions", "text": "SHA-256 maps arbitrary bytes to a fixed 256-bit digest. Bitcoin mining uses SHA-256d: SHA-256(SHA-256(data))."},
            {"heading": "Avalanche effect", "text": "Changing even one input bit unpredictably changes many output bits. Miners therefore cannot steer a hash toward the target; they search by trying header variations."},
        ],
        "quiz": {"question": "What does SHA-256d mean?", "choices": ["SHA-256 with 256 threads", "SHA-256 performed twice", "A 512-bit hash", "A pool share format"], "answer": 1, "explanation": "SHA-256d is the SHA-256 digest of a SHA-256 digest."},
    },
    {
        "id": "block-header",
        "track": "Block Mining",
        "level": "Intermediate",
        "title": "The 80-Byte Block Header",
        "summary": "Understand version, previous block hash, Merkle root, time, nBits and nonce.",
        "objectives": ["Name all six header fields", "Understand header serialization", "Connect nBits to the target"],
        "sections": [
            {"heading": "Header commitment", "text": "The 80-byte header commits to the previous block, the transaction set through the Merkle root, timestamp, encoded target and nonce."},
            {"heading": "Search space", "text": "Changing the nonce changes the header hash. Real miners also vary coinbase data, which changes the Merkle root and opens additional search space."},
        ],
        "quiz": {"question": "Which block-header field commits to the block's transactions?", "choices": ["Version", "Merkle root", "Timestamp", "Nonce"], "answer": 1, "explanation": "The Merkle root commits to the transaction set included in the candidate block."},
    },
    {
        "id": "difficulty-target",
        "track": "Proof of Work",
        "level": "Intermediate",
        "title": "Difficulty, nBits and Target",
        "summary": "Learn why a lower target means a harder Proof-of-Work search.",
        "objectives": ["Compare a hash numerically with a target", "Explain inverse difficulty/target behavior", "Decode compact nBits conceptually"],
        "sections": [
            {"heading": "Target rule", "text": "A Proof-of-Work hash is valid when its 256-bit numeric value is less than or equal to the target."},
            {"heading": "Difficulty", "text": "Difficulty is inversely related to the target. Increasing difficulty reduces the target and makes successful hashes rarer."},
        ],
        "quiz": {"question": "What happens when the Proof-of-Work target becomes smaller?", "choices": ["Mining becomes easier", "Mining becomes harder", "Blocks become larger", "Fees become zero"], "answer": 1, "explanation": "A smaller numeric target leaves fewer acceptable hash values, so the search is harder."},
    },
    {
        "id": "merkle-trees",
        "track": "Block Mining",
        "level": "Intermediate",
        "title": "Merkle Trees",
        "summary": "Follow transaction IDs upward into the Merkle root stored in the block header.",
        "objectives": ["Pair transaction hashes", "Explain duplicate-last behavior", "Describe how one transaction changes the root"],
        "sections": [
            {"heading": "Tree construction", "text": "Transaction hashes are paired and hashed repeatedly until one root remains. When a level has an odd number of hashes, Bitcoin duplicates the final hash for that pairing step."},
            {"heading": "Commitment", "text": "Changing any transaction changes its branch and therefore changes the final Merkle root committed by the block header."},
        ],
        "quiz": {"question": "If a Merkle-tree level contains an odd number of hashes, what does Bitcoin do?", "choices": ["Drops the last hash", "Duplicates the final hash", "Adds a zero hash", "Rejects the block"], "answer": 1, "explanation": "The final hash at that level is duplicated so it can be paired."},
    },
    {
        "id": "coinbase",
        "track": "Block Mining",
        "level": "Intermediate",
        "title": "Coinbase Transactions",
        "summary": "Understand the special first transaction that creates the block subsidy and collects transaction fees.",
        "objectives": ["Distinguish coinbase from ordinary transactions", "Explain extranonce search space", "Connect coinbase changes to the Merkle root"],
        "sections": [
            {"heading": "Special transaction", "text": "The first transaction in a block is the coinbase transaction. It has no normal previous output and creates the allowed subsidy plus collected transaction fees."},
            {"heading": "Extranonce", "text": "Pools and miners commonly vary coinbase data such as an extranonce. That changes the coinbase TXID, Merkle root and ultimately the header hash search space."},
        ],
        "quiz": {"question": "Why can changing an extranonce give a miner fresh header work?", "choices": ["It changes Bitcoin's supply cap", "It changes the coinbase TXID and Merkle root", "It lowers network difficulty", "It changes the previous block"], "answer": 1, "explanation": "Changing coinbase data changes its TXID, which changes the Merkle root committed in the header."},
    },
    {
        "id": "bitcoin-core-rpc",
        "track": "Bitcoin Core",
        "level": "Intermediate",
        "title": "Bitcoin Core RPC for Mining",
        "summary": "Map read-only node information and block-template RPCs to Miner Studio's mining pipeline.",
        "objectives": ["Recognize getblockchaininfo", "Explain getblocktemplate", "Separate read-only learning from state-changing actions"],
        "sections": [
            {"heading": "Read-only context", "text": "Commands such as getblockchaininfo, getnetworkinfo and getmempoolinfo expose node state without changing wallets or mining configuration."},
            {"heading": "Template pipeline", "text": "getblocktemplate supplies consensus-sensitive candidate-block data. Miner Studio's live submission path remains outside Mining Academy and behind its existing guards."},
        ],
        "quiz": {"question": "Which RPC is central to obtaining candidate-block template data?", "choices": ["getnetworkinfo", "getblocktemplate", "getwalletinfo", "stop"], "answer": 1, "explanation": "getblocktemplate provides the data miners need to construct a candidate block."},
    },
    {
        "id": "solo-mining",
        "track": "Mining Modes",
        "level": "Intermediate",
        "title": "Solo Mining",
        "summary": "Understand independent block discovery, variance and why expected value differs from predictable payout.",
        "objectives": ["Explain solo variance", "Connect network share to expected discovery rate", "Separate learning benchmarks from mainnet competitiveness"],
        "sections": [
            {"heading": "Independent search", "text": "A solo miner searches for a network-valid block rather than submitting lower-difficulty shares to a pool. Rewards arrive only when that miner actually finds an accepted block."},
            {"heading": "Variance", "text": "Block discovery is probabilistic. A small miner can wait far longer or shorter than the statistical average; expected time is not a schedule."},
        ],
        "quiz": {"question": "Why are solo-mining payouts highly variable?", "choices": ["Bitcoin Core randomly disables miners", "Only full network-target block discoveries pay the solo miner", "Pool fees change every nonce", "SHA-256 output is predictable"], "answer": 1, "explanation": "Solo miners do not receive frequent lower-difficulty share payouts; they must discover an accepted block."},
    },
    {
        "id": "stratum",
        "track": "Pool Mining",
        "level": "Advanced",
        "title": "Stratum Jobs and Shares",
        "summary": "Trace subscribe, authorize, notify and submit flow without touching live pool credentials.",
        "objectives": ["Distinguish share difficulty from network difficulty", "Recognize a mining job lifecycle", "Explain stale and rejected shares"],
        "sections": [
            {"heading": "Job flow", "text": "A Stratum pool distributes work and a share target. Miners submit proofs that satisfy the pool's share difficulty even when those proofs do not satisfy the much harder network target."},
            {"heading": "Accounting", "text": "Accepted shares provide evidence of contributed work. Stale or invalid shares may be rejected because the job changed or the submitted work did not satisfy protocol requirements."},
        ],
        "quiz": {"question": "Does every pool-accepted share satisfy Bitcoin's network block target?", "choices": ["Yes", "No", "Only on weekends", "Only with Bitcoin Core closed"], "answer": 1, "explanation": "Pools use an easier share target for accounting. Very rarely, a share also satisfies the network target and becomes a block candidate."},
    },
    {
        "id": "asic-mining",
        "track": "Hardware",
        "level": "Advanced",
        "title": "ASIC Mining and Efficiency",
        "summary": "Interpret TH/s, watts, W/TH, thermals, hardware errors and throttling.",
        "objectives": ["Explain W/TH", "Separate CPU lab results from ASIC performance", "Recognize thermal throttling indicators"],
        "sections": [
            {"heading": "Specialized hardware", "text": "Modern Bitcoin mainnet mining is dominated by SHA-256 ASICs. They execute the mining hash pipeline vastly more efficiently than general-purpose CPUs."},
            {"heading": "Efficiency", "text": "W/TH is a power-efficiency metric: watts consumed per terahash per second. Lower values indicate less electrical power for the same hashrate."},
        ],
        "quiz": {"question": "What does a lower W/TH value generally indicate?", "choices": ["Worse efficiency", "Better power efficiency", "Higher pool fees", "Lower network difficulty"], "answer": 1, "explanation": "Lower watts per terahash means less power is required for a given hashrate."},
    },
    {
        "id": "economics",
        "track": "Economics",
        "level": "Advanced",
        "title": "Mining Economics",
        "summary": "Connect hashrate, power, electricity, fees, difficulty and BTC price to estimated outcomes.",
        "objectives": ["Compute energy cost conceptually", "Recognize assumptions in profitability estimates", "Distinguish expected revenue from guarantees"],
        "sections": [
            {"heading": "Cost side", "text": "Electrical energy is power multiplied by time. Electricity price, infrastructure overhead, uptime and hardware efficiency materially affect operating cost."},
            {"heading": "Revenue side", "text": "Expected mining revenue depends on relative hashrate, network difficulty, block subsidy, transaction fees, pool terms and BTC price. Every estimate is assumption-sensitive."},
        ],
        "quiz": {"question": "Which statement about a mining profitability estimate is correct?", "choices": ["It guarantees future income", "It is an assumption-based estimate, not a guarantee", "It ignores electricity", "It fixes network difficulty"], "answer": 1, "explanation": "Mining economics change with network, market, hardware and operating conditions."},
    },
    {
        "id": "security",
        "track": "Security",
        "level": "Advanced",
        "title": "Mining Security",
        "summary": "Protect RPC access, credentials, firmware, wallets and mining infrastructure.",
        "objectives": ["Keep RPC private", "Protect pool and wallet secrets", "Recognize why firmware and TLS matter"],
        "sections": [
            {"heading": "Reduce exposure", "text": "Bitcoin Core RPC should not be exposed broadly to untrusted networks. Bind and authenticate it appropriately for your environment."},
            {"heading": "Protect secrets", "text": "Wallet seed material, private keys, RPC credentials and pool credentials should never be placed in public logs, screenshots or exported Academy data."},
        ],
        "quiz": {"question": "Which item should never be included in a Mining Academy export or screenshot?", "choices": ["A public block hash", "A wallet seed/private key", "A public block height", "A SHA-256 example digest"], "answer": 1, "explanation": "Wallet seed material and private keys are authentication/control secrets and must remain private."},
    },
]

LESSON_BY_ID = {row["id"]: row for row in LESSONS}
LABS = [
    {"id": "hash", "title": "Hash Explorer", "lesson_id": "sha256d"},
    {"id": "difficulty", "title": "Difficulty & Target Visualizer", "lesson_id": "difficulty-target"},
    {"id": "header", "title": "Block Header Lab", "lesson_id": "block-header"},
    {"id": "merkle", "title": "Merkle Tree Lab", "lesson_id": "merkle-trees"},
    {"id": "nonce", "title": "Nonce Mining Simulator", "lesson_id": "block-header"},
]
LAB_IDS = {row["id"] for row in LABS}

RANKS = [
    (0, "New Miner"),
    (200, "Hash Apprentice"),
    (500, "Block Builder"),
    (900, "Mining Technician"),
    (1400, "Mining Engineer"),
    (1900, "Mining Specialist"),
    (2400, "Mining Expert"),
    (3000, "Purple Dragon Mining Master"),
]


def public_catalog():
    rows = []
    for lesson in LESSONS:
        clean = dict(lesson)
        quiz = dict(clean.pop("quiz"))
        quiz.pop("answer", None)
        quiz.pop("explanation", None)
        clean["quiz"] = quiz
        rows.append(clean)
    return rows


class AcademyStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def _default(self):
        return {
            "schema": SCHEMA,
            "lessons": {},
            "labs_completed": [],
            "quizzes": {},
            "last_lesson": "fundamentals",
            "updated_at": 0.0,
        }

    def _load(self):
        try:
            if not self.path.exists():
                return self._default()
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return self._default()
        except Exception:
            return self._default()
        data = self._default()
        data.update(raw)
        data["lessons"] = {
            str(k): str(v)
            for k, v in dict(data.get("lessons") or {}).items()
            if k in LESSON_BY_ID and str(v) in {"not_started", "in_progress", "completed"}
        }
        data["labs_completed"] = sorted({str(x) for x in data.get("labs_completed") or [] if str(x) in LAB_IDS})
        quizzes = {}
        for key, value in dict(data.get("quizzes") or {}).items():
            if key not in LESSON_BY_ID or not isinstance(value, dict):
                continue
            quizzes[key] = {
                "passed": bool(value.get("passed")),
                "attempts": max(0, int(value.get("attempts") or 0)),
                "last_answer": int(value.get("last_answer") or 0),
                "updated_at": float(value.get("updated_at") or 0),
            }
        data["quizzes"] = quizzes
        if str(data.get("last_lesson")) not in LESSON_BY_ID:
            data["last_lesson"] = "fundamentals"
        return data

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def state(self):
        with self.lock:
            data = self._load()
        completed = {key for key, value in data["lessons"].items() if value == "completed"}
        in_progress = {key for key, value in data["lessons"].items() if value == "in_progress"}
        passed = {key for key, value in data["quizzes"].items() if value.get("passed")}
        labs = set(data["labs_completed"])
        points = len(completed) * 100 + len(passed) * 40 + len(labs) * 60
        rank = RANKS[0][1]
        next_rank = None
        for threshold, label in RANKS:
            if points >= threshold:
                rank = label
            elif next_rank is None:
                next_rank = {"points": threshold, "rank": label}
        total = len(LESSONS)
        percent = round(len(completed) / max(1, total) * 100, 1)
        lesson_status = {lesson["id"]: data["lessons"].get(lesson["id"], "not_started") for lesson in LESSONS}
        return {
            "schema": SCHEMA,
            "catalog": public_catalog(),
            "labs": list(LABS),
            "lesson_status": lesson_status,
            "labs_completed": sorted(labs),
            "quizzes": data["quizzes"],
            "last_lesson": data["last_lesson"],
            "completed_lessons": len(completed),
            "in_progress_lessons": len(in_progress),
            "total_lessons": total,
            "passed_quizzes": len(passed),
            "total_quizzes": total,
            "completed_labs": len(labs),
            "total_labs": len(LABS),
            "points": points,
            "rank": rank,
            "next_rank": next_rank,
            "progress_percent": percent,
            "updated_at": float(data.get("updated_at") or 0),
            "privacy": "Local educational progress only. No credentials, wallets, pool secrets, RPC passwords or mining-control state are stored.",
        }

    def set_lesson_status(self, lesson_id, status):
        lesson_id = str(lesson_id or "")
        status = str(status or "").lower()
        if lesson_id not in LESSON_BY_ID:
            raise ValueError("Unknown Mining Academy lesson.")
        if status not in {"not_started", "in_progress", "completed"}:
            raise ValueError("Lesson status must be not_started, in_progress or completed.")
        with self.lock:
            data = self._load()
            if status == "not_started":
                data["lessons"].pop(lesson_id, None)
            else:
                data["lessons"][lesson_id] = status
            data["last_lesson"] = lesson_id
            data["updated_at"] = time.time()
            self._save(data)
        return self.state()

    def complete_lab(self, lab_id):
        lab_id = str(lab_id or "")
        if lab_id not in LAB_IDS:
            raise ValueError("Unknown Mining Academy lab.")
        with self.lock:
            data = self._load()
            data["labs_completed"] = sorted(set(data["labs_completed"]) | {lab_id})
            data["updated_at"] = time.time()
            self._save(data)
        return self.state()

    def submit_quiz(self, lesson_id, answer_index):
        lesson_id = str(lesson_id or "")
        if lesson_id not in LESSON_BY_ID:
            raise ValueError("Unknown Mining Academy lesson.")
        quiz = LESSON_BY_ID[lesson_id]["quiz"]
        try:
            answer_index = int(answer_index)
        except (TypeError, ValueError) as exc:
            raise ValueError("Quiz answer must be a choice index.") from exc
        choices = quiz["choices"]
        if not 0 <= answer_index < len(choices):
            raise ValueError("Quiz answer is outside the available choices.")
        correct = answer_index == int(quiz["answer"])
        with self.lock:
            data = self._load()
            prior = dict(data["quizzes"].get(lesson_id) or {})
            data["quizzes"][lesson_id] = {
                "passed": bool(prior.get("passed")) or correct,
                "attempts": int(prior.get("attempts") or 0) + 1,
                "last_answer": answer_index,
                "updated_at": time.time(),
            }
            if data["lessons"].get(lesson_id) == "not_started" or lesson_id not in data["lessons"]:
                data["lessons"][lesson_id] = "in_progress"
            data["last_lesson"] = lesson_id
            data["updated_at"] = time.time()
            self._save(data)
        return {
            "correct": correct,
            "correct_index": int(quiz["answer"]),
            "explanation": quiz["explanation"],
            "state": self.state(),
        }

    def reset(self):
        with self.lock:
            data = self._default()
            data["updated_at"] = time.time()
            self._save(data)
        return self.state()


class MiningAcademy:
    def __init__(self, progress_path):
        self.store = AcademyStore(progress_path)

    def state(self):
        return self.store.state()

    def set_lesson_status(self, lesson_id, status):
        return self.store.set_lesson_status(lesson_id, status)

    def submit_quiz(self, lesson_id, answer_index):
        return self.store.submit_quiz(lesson_id, answer_index)

    def reset_progress(self):
        return self.store.reset()

    def hash_lab(self, text):
        raw = str(text if text is not None else "").encode("utf-8")
        first = sha256(raw)
        second = sha256(first)
        state = self.store.complete_lab("hash")
        return {
            "input_utf8_bytes": len(raw),
            "sha256": first.hex(),
            "sha256d": second.hex(),
            "state": state,
        }

    def difficulty_lab(self, difficulty=1.0, bits=None):
        if bits not in (None, ""):
            compact = _parse_bits(bits)
            target = compact_to_target(compact)
            diff = DIFF1_TARGET / target
            source = "nBits"
        else:
            diff = float(difficulty)
            target = difficulty_to_target(diff)
            compact = None
            source = "difficulty"
        state = self.store.complete_lab("difficulty")
        return {
            "source": source,
            "difficulty": diff,
            "bits": f"0x{compact:08x}" if compact is not None else "",
            "target": f"{target:064x}",
            "target_integer": str(target),
            "difficulty_one_target": f"{DIFF1_TARGET:064x}",
            "state": state,
        }

    def block_header_lab(self, payload=None):
        payload = dict(payload or {})
        version = int(payload.get("version", 0x20000000))
        prev_hash = _hex32(payload.get("previousblockhash") or "00" * 32, "Previous block hash")
        merkle_root = _hex32(payload.get("merkleroot") or "00" * 32, "Merkle root")
        timestamp = int(payload.get("time", 1231006505))
        bits = _parse_bits(payload.get("bits", "0x1d00ffff"))
        nonce = int(payload.get("nonce", 0))
        if not 0 <= version <= 0xFFFFFFFF:
            raise ValueError("Version must fit in 32 bits.")
        if not 0 <= timestamp <= 0xFFFFFFFF:
            raise ValueError("Timestamp must fit in 32 bits.")
        if not 0 <= bits <= 0xFFFFFFFF:
            raise ValueError("nBits must fit in 32 bits.")
        if not 0 <= nonce <= 0xFFFFFFFF:
            raise ValueError("Nonce must fit in 32 bits.")
        header = (
            struct.pack("<L", version)
            + bytes.fromhex(prev_hash)[::-1]
            + bytes.fromhex(merkle_root)[::-1]
            + struct.pack("<LLL", timestamp, bits, nonce)
        )
        digest = sha256d(header)
        displayed_hash = digest[::-1].hex()
        target = compact_to_target(bits)
        hash_value = int(displayed_hash, 16)
        state = self.store.complete_lab("header")
        return {
            "header_hex": header.hex(),
            "header_bytes": len(header),
            "hash": displayed_hash,
            "hash_integer": str(hash_value),
            "target": f"{target:064x}",
            "valid_pow": hash_value <= target,
            "version": version,
            "previousblockhash": prev_hash,
            "merkleroot": merkle_root,
            "time": timestamp,
            "bits": f"0x{bits:08x}",
            "nonce": nonce,
            "state": state,
        }

    def merkle_lab(self, txids):
        if isinstance(txids, str):
            txids = [row.strip() for row in txids.replace(",", "\n").splitlines() if row.strip()]
        txids = list(txids or [])
        if not txids:
            raise ValueError("Enter at least one transaction ID.")
        if len(txids) > 32:
            raise ValueError("Mining Academy Merkle Lab accepts up to 32 transaction IDs at once.")
        cleaned = [_hex32(value, f"Transaction ID {index + 1}") for index, value in enumerate(txids)]
        current = [bytes.fromhex(value)[::-1] for value in cleaned]
        levels = [[value for value in cleaned]]
        while len(current) > 1:
            if len(current) % 2:
                current = current + [current[-1]]
            nxt = [sha256d(current[i] + current[i + 1]) for i in range(0, len(current), 2)]
            levels.append([value[::-1].hex() for value in nxt])
            current = nxt
        root = current[0][::-1].hex()
        state = self.store.complete_lab("merkle")
        return {"transaction_count": len(cleaned), "merkle_root": root, "levels": levels, "state": state}

    def nonce_lab(self, payload=None):
        payload = dict(payload or {})
        seed = str(payload.get("seed") or "Purple Dragon Mining Academy")
        zero_nibbles = max(1, min(5, int(payload.get("zero_nibbles") or 3)))
        max_attempts = max(1, min(MAX_NONCE_ATTEMPTS, int(payload.get("max_attempts") or 100_000)))
        start_nonce = max(0, min(0xFFFFFFFF, int(payload.get("start_nonce") or 0)))
        prefix = "0" * zero_nibbles
        base = seed.encode("utf-8")
        started = time.perf_counter()
        found = None
        best = None
        best_hash = "f" * 64
        attempts = 0
        for offset in range(max_attempts):
            nonce = (start_nonce + offset) & 0xFFFFFFFF
            digest = sha256d(base + struct.pack("<L", nonce))[::-1].hex()
            attempts += 1
            if digest < best_hash:
                best_hash, best = digest, nonce
            if digest.startswith(prefix):
                found = (nonce, digest)
                break
        elapsed = max(1e-9, time.perf_counter() - started)
        state = self.store.complete_lab("nonce")
        return {
            "seed": seed,
            "zero_nibbles": zero_nibbles,
            "target_prefix": prefix,
            "attempts": attempts,
            "elapsed_seconds": elapsed,
            "hashrate": attempts / elapsed,
            "found": found is not None,
            "nonce": found[0] if found else None,
            "hash": found[1] if found else "",
            "best_nonce": best,
            "best_hash": best_hash,
            "state": state,
            "note": "Educational prefix target only; this is not Bitcoin network difficulty or live mining.",
        }