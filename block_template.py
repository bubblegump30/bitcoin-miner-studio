import time

from bitcoin_core import BitcoinCoreRPCError, rpc_call

# Bitcoin's difficulty-1 target, used for human-readable template difficulty.
DIFFICULTY_1_TARGET = int(
    "00000000ffff0000000000000000000000000000000000000000000000000000",
    16,
)


def compact_bits_to_target(bits):
    """Decode compact nBits into an integer target."""
    if isinstance(bits, str):
        bits_int = int(bits, 16)
    else:
        bits_int = int(bits)
    exponent = (bits_int >> 24) & 0xFF
    mantissa = bits_int & 0x007FFFFF
    if bits_int & 0x00800000:
        raise ValueError("Negative compact targets are not valid mining targets.")
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def normalize_target(target_hex=None, bits=None):
    target_hex = str(target_hex or "").strip().lower()
    if target_hex:
        if target_hex.startswith("0x"):
            target_hex = target_hex[2:]
        if not target_hex or any(ch not in "0123456789abcdef" for ch in target_hex):
            raise ValueError("Block template target is not valid hexadecimal.")
        target_int = int(target_hex, 16)
    elif bits not in (None, ""):
        target_int = compact_bits_to_target(bits)
    else:
        raise ValueError("Block template did not include target or bits.")

    if target_int <= 0 or target_int >= (1 << 256):
        raise ValueError("Block template target is outside the valid 256-bit range.")
    return f"{target_int:064x}", target_int


def target_to_difficulty(target_int):
    target_int = int(target_int)
    if target_int <= 0:
        return 0.0
    return float(DIFFICULTY_1_TARGET / target_int)


def sats_to_btc(sats):
    return float(int(sats or 0) / 100_000_000.0)


def parse_block_template(template, *, latency_ms=0.0, fetched_at=None):
    """Validate and normalize a Bitcoin Core getblocktemplate result."""
    if not isinstance(template, dict):
        raise BitcoinCoreRPCError(
            "getblocktemplate returned a non-object result.",
            kind="invalid_response",
        )

    required = ("version", "previousblockhash", "bits", "height", "coinbasevalue")
    missing = [key for key in required if key not in template]
    if missing:
        raise BitcoinCoreRPCError(
            "getblocktemplate is missing required field(s): " + ", ".join(missing),
            kind="invalid_response",
        )

    try:
        target_hex, target_int = normalize_target(template.get("target"), template.get("bits"))
    except (TypeError, ValueError) as exc:
        raise BitcoinCoreRPCError(str(exc), kind="invalid_response") from exc

    transactions = template.get("transactions") or []
    if not isinstance(transactions, list):
        raise BitcoinCoreRPCError(
            "getblocktemplate transactions field is not a list.",
            kind="invalid_response",
        )

    fee_values = []
    fees_complete = True
    total_weight = 0
    total_sigops = 0
    dependency_edges = 0
    mining_txids = []
    mining_txdata = []
    txids_complete = True
    txdata_complete = True
    for tx in transactions:
        if not isinstance(tx, dict):
            fees_complete = False
            continue
        if "fee" in tx:
            try:
                fee_values.append(int(tx.get("fee") or 0))
            except (TypeError, ValueError):
                fees_complete = False
        else:
            fees_complete = False
        try:
            total_weight += int(tx.get("weight") or 0)
        except (TypeError, ValueError):
            pass
        try:
            total_sigops += int(tx.get("sigops") or 0)
        except (TypeError, ValueError):
            pass
        depends = tx.get("depends") or []
        if isinstance(depends, list):
            dependency_edges += len(depends)

        txid = str(tx.get("txid") or "").strip().lower()
        if len(txid) == 64 and all(ch in "0123456789abcdef" for ch in txid):
            mining_txids.append(txid)
        else:
            txids_complete = False

        raw_data = str(tx.get("data") or "").strip().lower()
        if raw_data and len(raw_data) % 2 == 0 and all(ch in "0123456789abcdef" for ch in raw_data):
            mining_txdata.append(raw_data)
        else:
            txdata_complete = False

    total_fees_sats = sum(fee_values)
    coinbase_value_sats = int(template.get("coinbasevalue") or 0)
    subsidy_sats = coinbase_value_sats - total_fees_sats if fees_complete else None

    rules = [str(x) for x in (template.get("rules") or [])]
    mutable = [str(x) for x in (template.get("mutable") or [])]
    capabilities = [str(x) for x in (template.get("capabilities") or [])]

    fetched_at = float(fetched_at if fetched_at is not None else time.time())
    return {
        "available": True,
        "status": "Ready",
        "height": int(template.get("height") or 0),
        "version": int(template.get("version") or 0),
        "previousblockhash": str(template.get("previousblockhash") or ""),
        "bits": str(template.get("bits") or ""),
        "target": target_hex,
        "target_int": str(target_int),
        "difficulty": target_to_difficulty(target_int),
        "transactions": len(transactions),
        "dependency_edges": dependency_edges,
        "total_fees_sats": total_fees_sats,
        "total_fees_btc": sats_to_btc(total_fees_sats),
        "fees_complete": bool(fees_complete),
        "coinbase_value_sats": coinbase_value_sats,
        "coinbase_value_btc": sats_to_btc(coinbase_value_sats),
        "subsidy_sats": subsidy_sats,
        "subsidy_btc": sats_to_btc(subsidy_sats) if subsidy_sats is not None else None,
        "curtime": int(template.get("curtime") or 0),
        "mintime": int(template.get("mintime") or 0),
        "size_limit": int(template.get("sizelimit") or 0),
        "weight_limit": int(template.get("weightlimit") or 0),
        "sigop_limit": int(template.get("sigoplimit") or 0),
        "transaction_weight": total_weight,
        "transaction_sigops": total_sigops,
        "noncerange": str(template.get("noncerange") or ""),
        "longpollid": str(template.get("longpollid") or ""),
        "rules": rules,
        "mutable": mutable,
        "capabilities": capabilities,
        "default_witness_commitment": str(template.get("default_witness_commitment") or ""),
        "coinbase_aux_flags": str((template.get("coinbaseaux") or {}).get("flags") or "")
            if isinstance(template.get("coinbaseaux") or {}, dict)
            else "",
        "_txids": mining_txids,
        "_txids_complete": bool(txids_complete and len(mining_txids) == len(transactions)),
        "_transaction_data": mining_txdata,
        "_transaction_data_complete": bool(txdata_complete and len(mining_txdata) == len(transactions)),
        "latency_ms": float(latency_ms or 0.0),
        "fetched_at": fetched_at,
        "error": "",
        "error_kind": "",
    }


def fetch_block_template(rpc_url, username, password, timeout=6.0):
    """Fetch a SegWit-aware getblocktemplate and return normalized work data."""
    result, latency_ms = rpc_call(
        rpc_url,
        username,
        password,
        "getblocktemplate",
        [{"rules": ["segwit"]}],
        timeout=timeout,
    )
    return parse_block_template(result, latency_ms=latency_ms)


def unavailable_template(error=None):
    kind = getattr(error, "kind", "connection") if error else "waiting"
    message = str(error) if error else "Block template has not been requested yet."
    return {
        "available": False,
        "status": "Unavailable" if error else "Waiting",
        "height": 0,
        "version": 0,
        "previousblockhash": "",
        "bits": "",
        "target": "",
        "target_int": "0",
        "difficulty": 0.0,
        "transactions": 0,
        "dependency_edges": 0,
        "total_fees_sats": 0,
        "total_fees_btc": 0.0,
        "fees_complete": False,
        "coinbase_value_sats": 0,
        "coinbase_value_btc": 0.0,
        "subsidy_sats": None,
        "subsidy_btc": None,
        "curtime": 0,
        "mintime": 0,
        "size_limit": 0,
        "weight_limit": 0,
        "sigop_limit": 0,
        "transaction_weight": 0,
        "transaction_sigops": 0,
        "noncerange": "",
        "longpollid": "",
        "rules": [],
        "mutable": [],
        "capabilities": [],
        "default_witness_commitment": "",
        "coinbase_aux_flags": "",
        "_txids": [],
        "_txids_complete": False,
        "_transaction_data": [],
        "_transaction_data_complete": False,
        "latency_ms": 0.0,
        "fetched_at": 0.0,
        "error": message,
        "error_kind": kind,
    }


def template_for_ui(state, refresh_seconds=15, now=None):
    """Attach live age/refresh timing without mutating the stored snapshot."""
    result = dict(state or unavailable_template())
    for key in list(result):
        if str(key).startswith("_"):
            result.pop(key, None)
    now = float(now if now is not None else time.time())
    fetched_at = float(result.get("fetched_at") or 0.0)
    refresh_seconds = max(5, min(300, int(refresh_seconds or 15)))
    if fetched_at > 0:
        age = max(0.0, now - fetched_at)
        result["age_seconds"] = age
        result["next_refresh_at"] = fetched_at + refresh_seconds
        result["refresh_in_seconds"] = max(0.0, fetched_at + refresh_seconds - now)
        result["stale"] = bool(result.get("available")) and age > max(refresh_seconds * 2, 60)
        if result["stale"]:
            result["status"] = "Stale"
    else:
        result["age_seconds"] = 0.0
        result["next_refresh_at"] = 0.0
        result["refresh_in_seconds"] = 0.0
        result["stale"] = False
    return result


def template_report(state):
    if not state.get("available"):
        return f"BLOCK TEMPLATE UNAVAILABLE\n\n{state.get('error') or 'getblocktemplate is unavailable.'}"
    fees_note = "complete" if state.get("fees_complete") else "partial"
    subsidy = state.get("subsidy_btc")
    subsidy_text = f"{subsidy:.8f} BTC" if subsidy is not None else "unknown"
    return (
        "BLOCK TEMPLATE READY\n\n"
        f"Next height: {state.get('height', 0):,}\n"
        f"Transactions: {state.get('transactions', 0):,}\n"
        f"Coinbase value: {state.get('coinbase_value_btc', 0):.8f} BTC\n"
        f"Transaction fees ({fees_note}): {state.get('total_fees_btc', 0):.8f} BTC\n"
        f"Subsidy estimate: {subsidy_text}\n"
        f"Template difficulty: {state.get('difficulty', 0):,.8g}\n"
        f"Bits: {state.get('bits') or '—'}\n"
        f"Target: {state.get('target') or '—'}\n"
        f"Previous block: {state.get('previousblockhash') or '—'}\n"
        f"Rules: {', '.join(state.get('rules') or []) or 'none'}\n"
        f"RPC latency: {state.get('latency_ms', 0):.1f} ms\n\n"
        "getblocktemplate succeeded and the work template passed structural validation."
    )
