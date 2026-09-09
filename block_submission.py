"""Bitcoin Miner Studio v0.4.5 block assembly and controlled submission.

Only target-valid candidate bundles produced by the local SoloMiningEngine can
reach the submit path. There is deliberately no arbitrary "submit hex" API.
"""

import hashlib
import json
import time
from pathlib import Path

from solo_miner import UINT256_MAX, hash_header, merkle_root_from_txids


class BlockAssemblyError(ValueError):
    pass


def _compact_size(value):
    value = int(value)
    if value < 0:
        raise BlockAssemblyError("CompactSize cannot encode a negative value.")
    if value < 0xFD:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + value.to_bytes(2, "little")
    if value <= 0xFFFFFFFF:
        return b"\xfe" + value.to_bytes(4, "little")
    if value <= 0xFFFFFFFFFFFFFFFF:
        return b"\xff" + value.to_bytes(8, "little")
    raise BlockAssemblyError("CompactSize value is too large.")


def _hex_bytes(value, label):
    value = str(value or "").strip().lower()
    if not value or len(value) % 2 or any(ch not in "0123456789abcdef" for ch in value):
        raise BlockAssemblyError(f"{label} is not valid hexadecimal.")
    return bytes.fromhex(value)


def _valid_hash(value, label):
    value = str(value or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise BlockAssemblyError(f"{label} must be a 32-byte hexadecimal hash.")
    return value


def unavailable_submission_state(message="Waiting for a target-valid solo-mining candidate."):
    return {
        "status": "Waiting",
        "detail": str(message),
        "candidate_available": False,
        "candidate_source": "",
        "assembled": False,
        "proposal_checked": False,
        "proposal_valid": False,
        "submitted": False,
        "accepted": False,
        "stale": False,
        "height": 0,
        "block_hash": "",
        "previousblockhash": "",
        "merkle_root": "",
        "target": "",
        "target_valid": False,
        "nonce": 0,
        "extranonce": 0,
        "transaction_count": 0,
        "block_size": 0,
        "block_weight": 0,
        "size_limit": 0,
        "weight_limit": 0,
        "proposal_result": "",
        "submit_result": "",
        "rpc_latency_ms": 0.0,
        "archive_json": "",
        "archive_block": "",
        "busy": False,
        "operation": "",
        "result_text": "",
        "error": "",
    }


def assemble_candidate_block(bundle, *, require_target=True):
    if not isinstance(bundle, dict):
        raise BlockAssemblyError("Candidate bundle is unavailable.")
    template = dict(bundle.get("template") or {})
    work = dict(bundle.get("work") or {})
    candidate = dict(bundle.get("candidate") or {})

    if not template.get("available"):
        raise BlockAssemblyError("Candidate template is unavailable.")
    header_hex = str(candidate.get("header_hex") or "").strip().lower()
    header = _hex_bytes(header_hex, "Candidate header")
    if len(header) != 80:
        raise BlockAssemblyError("Candidate header must be exactly 80 bytes.")

    block_hash, block_hash_int = hash_header(header)
    expected_hash = _valid_hash(candidate.get("hash"), "Candidate hash")
    if block_hash != expected_hash:
        raise BlockAssemblyError("Candidate header hash does not match the preserved candidate hash.")

    try:
        target_int = int(str(work.get("target_int") or template.get("target_int") or "0"))
    except ValueError as exc:
        raise BlockAssemblyError("Candidate target is invalid.") from exc
    if target_int <= 0 or target_int > UINT256_MAX:
        raise BlockAssemblyError("Candidate target is outside the valid 256-bit range.")
    target_valid = block_hash_int <= target_int
    if require_target and not target_valid:
        raise BlockAssemblyError("Candidate hash does not meet the Bitcoin Core template target.")

    previous = _valid_hash(work.get("previousblockhash"), "Previous block hash")
    merkle = _valid_hash(work.get("merkle_root"), "Merkle root")
    if header[4:36][::-1].hex() != previous:
        raise BlockAssemblyError("Header previous-block hash does not match the preserved work.")
    if header[36:68][::-1].hex() != merkle:
        raise BlockAssemblyError("Header merkle root does not match the preserved work.")
    nonce = int.from_bytes(header[76:80], "little")
    if nonce != int(candidate.get("nonce") or 0):
        raise BlockAssemblyError("Header nonce does not match the preserved candidate nonce.")

    coinbase = dict(work.get("coinbase") or {})
    coinbase_raw = _hex_bytes(coinbase.get("raw_transaction"), "Coinbase transaction")
    coinbase_txid = _valid_hash(coinbase.get("txid"), "Coinbase TXID")

    txids = list(template.get("_txids") or [])
    txdata = list(template.get("_transaction_data") or [])
    expected_transactions = int(template.get("transactions") or 0)
    if expected_transactions != len(txids) or not template.get("_txids_complete"):
        raise BlockAssemblyError("Template transaction-ID set is incomplete.")
    if expected_transactions != len(txdata) or not template.get("_transaction_data_complete"):
        raise BlockAssemblyError("Template raw-transaction set is incomplete.")

    expected_merkle = merkle_root_from_txids([coinbase_txid] + txids)
    if expected_merkle != merkle:
        raise BlockAssemblyError("Recomputed transaction merkle root does not match the block header.")

    raw_transactions = [_hex_bytes(raw, f"Template transaction {index + 1}") for index, raw in enumerate(txdata)]
    transaction_count = 1 + len(raw_transactions)
    count_prefix = _compact_size(transaction_count)
    block = header + count_prefix + coinbase_raw + b"".join(raw_transactions)
    block_hex = block.hex()

    # Block-weight accounting: header + transaction-count prefix are non-witness
    # bytes (4 WU/byte). GBT transaction_weight excludes the coinbase.
    overhead_weight = 4 * (80 + len(count_prefix))
    block_weight = overhead_weight + int(template.get("transaction_weight") or 0) + int(coinbase.get("weight") or 0)
    block_size = len(block)
    size_limit = int(template.get("size_limit") or 0)
    weight_limit = int(template.get("weight_limit") or 0)

    if size_limit and block_size > size_limit:
        raise BlockAssemblyError(f"Assembled block is {block_size:,} bytes, above template size limit {size_limit:,}.")
    if weight_limit and block_weight > weight_limit:
        raise BlockAssemblyError(f"Assembled block weight is {block_weight:,} WU, above template limit {weight_limit:,} WU.")

    witness_expected = str(template.get("default_witness_commitment") or "").strip().lower()
    witness_actual = str(coinbase.get("witness_commitment") or "").strip().lower()
    if witness_expected and witness_actual != witness_expected:
        raise BlockAssemblyError("Coinbase witness commitment does not match the Bitcoin Core template.")

    return {
        "height": int(work.get("height") or template.get("height") or 0),
        "block_hash": block_hash,
        "block_hash_int": str(block_hash_int),
        "previousblockhash": previous,
        "merkle_root": merkle,
        "target": str(work.get("target") or template.get("target") or ""),
        "target_int": str(target_int),
        "target_valid": bool(target_valid),
        "nonce": nonce,
        "extranonce": int(work.get("extranonce") or 0),
        "transaction_count": transaction_count,
        "block_size": block_size,
        "block_weight": block_weight,
        "size_limit": size_limit,
        "weight_limit": weight_limit,
        "coinbase_txid": coinbase_txid,
        "witness_commitment": witness_actual,
        "header_hex": header_hex,
        "raw_block": block_hex,
        "raw_block_sha256": hashlib.sha256(block).hexdigest(),
        "assembled_at": time.time(),
    }


def assembly_for_ui(
    assembly,
    *,
    status="Assembled",
    detail="Complete raw Bitcoin block assembled locally.",
    candidate_available=None,
):
    a = dict(assembly or {})
    if candidate_available is None:
        candidate_available = bool(a.get("target_valid"))
    result = unavailable_submission_state(detail)
    result.update({
        "status": status,
        "detail": detail,
        "candidate_available": bool(candidate_available),
        "candidate_source": str(a.get("candidate_source") or ""),
        "assembled": True,
        "height": int(a.get("height") or 0),
        "block_hash": str(a.get("block_hash") or ""),
        "previousblockhash": str(a.get("previousblockhash") or ""),
        "merkle_root": str(a.get("merkle_root") or ""),
        "target": str(a.get("target") or ""),
        "target_valid": bool(a.get("target_valid")),
        "nonce": int(a.get("nonce") or 0),
        "extranonce": int(a.get("extranonce") or 0),
        "transaction_count": int(a.get("transaction_count") or 0),
        "block_size": int(a.get("block_size") or 0),
        "block_weight": int(a.get("block_weight") or 0),
        "size_limit": int(a.get("size_limit") or 0),
        "weight_limit": int(a.get("weight_limit") or 0),
    })
    return result


def assembly_report(assembly, *, target_required=True):
    a = dict(assembly or {})
    return (
        "BLOCK ASSEMBLY VERIFIED\n\n"
        f"Height: {int(a.get('height') or 0):,}\n"
        f"Block hash: {a.get('block_hash')}\n"
        f"Previous block: {a.get('previousblockhash')}\n"
        f"Merkle root: {a.get('merkle_root')}\n"
        f"Transactions: {int(a.get('transaction_count') or 0):,}\n"
        f"Serialized size: {int(a.get('block_size') or 0):,} bytes\n"
        f"Block weight: {int(a.get('block_weight') or 0):,} WU\n"
        f"Nonce: {int(a.get('nonce') or 0):,}\n"
        f"Extranonce: {int(a.get('extranonce') or 0):,}\n"
        f"Target met: {'YES' if a.get('target_valid') else 'NO'}\n\n"
        + (
            "This block is eligible for Bitcoin Core proposal validation."
            if a.get("target_valid")
            else "Structure is valid, but the test nonce does not meet the network target (expected for a normal mainnet test)."
        )
    )


def archive_candidate(assembly, directory):
    a = dict(assembly or {})
    raw_block = str(a.get("raw_block") or "")
    if not raw_block:
        raise BlockAssemblyError("No assembled raw block is available to archive.")

    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    height = int(a.get("height") or 0)
    block_hash = str(a.get("block_hash") or "unknown")
    stem = f"candidate-{height}-{block_hash[:16]}"

    block_path = directory / f"{stem}.block.hex"
    json_path = directory / f"{stem}.json"
    block_path.write_text(raw_block + "\n", encoding="ascii")

    summary = {key: value for key, value in a.items() if key != "raw_block"}
    summary["block_hex_file"] = block_path.name
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return str(json_path), str(block_path)
