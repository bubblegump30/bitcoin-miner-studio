"""Bitcoin Miner Studio coinbase transaction construction and payout validation.

No private keys or seed phrases are used here.  A coinbase pays to a public
Bitcoin address supplied by the user and is constructed from a live
getblocktemplate snapshot.
"""

import hashlib

SATOSHIS_PER_BTC = 100_000_000
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_MAP = {ch: i for i, ch in enumerate(BASE58_ALPHABET)}
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32_MAP = {ch: i for i, ch in enumerate(BECH32_CHARSET)}
BECH32_CONST = 1
BECH32M_CONST = 0x2BC830A3

NETWORKS = {
    "main": {"base58": {0x00: "P2PKH", 0x05: "P2SH"}, "hrp": "bc"},
    "testnet": {"base58": {0x6F: "P2PKH", 0xC4: "P2SH"}, "hrp": "tb"},
    "testnet4": {"base58": {0x6F: "P2PKH", 0xC4: "P2SH"}, "hrp": "tb"},
    "signet": {"base58": {0x6F: "P2PKH", 0xC4: "P2SH"}, "hrp": "tb"},
    "regtest": {"base58": {0x6F: "P2PKH", 0xC4: "P2SH"}, "hrp": "bcrt"},
}


class CoinbaseError(ValueError):
    pass


def _sha256(data):
    return hashlib.sha256(data).digest()


def _hash256(data):
    return _sha256(_sha256(data))


def _varint(value):
    value = int(value)
    if value < 0:
        raise CoinbaseError("Negative compact sizes are not valid.")
    if value < 0xFD:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + value.to_bytes(2, "little")
    if value <= 0xFFFFFFFF:
        return b"\xfe" + value.to_bytes(4, "little")
    return b"\xff" + value.to_bytes(8, "little")


def _push_data(data):
    data = bytes(data)
    size = len(data)
    if size <= 75:
        return bytes([size]) + data
    if size <= 0xFF:
        return b"\x4c" + bytes([size]) + data
    if size <= 0xFFFF:
        return b"\x4d" + size.to_bytes(2, "little") + data
    raise CoinbaseError("Coinbase data item is too large.")


def _script_num(value):
    value = int(value)
    if value < 0:
        raise CoinbaseError("Block height cannot be negative.")
    if value == 0:
        return b""
    out = bytearray()
    while value:
        out.append(value & 0xFF)
        value >>= 8
    if out[-1] & 0x80:
        out.append(0)
    return bytes(out)


def _b58decode_check(address):
    if not address:
        raise CoinbaseError("Payout address is required.")
    num = 0
    try:
        for ch in address:
            num = num * 58 + BASE58_MAP[ch]
    except KeyError as exc:
        raise CoinbaseError("Address contains an invalid Base58 character.") from exc
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    pad = len(address) - len(address.lstrip("1"))
    raw = b"\x00" * pad + raw
    if len(raw) < 5:
        raise CoinbaseError("Base58 address is too short.")
    payload, checksum = raw[:-4], raw[-4:]
    if _hash256(payload)[:4] != checksum:
        raise CoinbaseError("Base58 address checksum is invalid.")
    return payload


def _bech32_polymod(values):
    chk = 1
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for i, gen in enumerate(generators):
            if (top >> i) & 1:
                chk ^= gen
    return chk


def _bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_decode(address):
    if not address or len(address) > 90:
        raise CoinbaseError("Bech32 address length is invalid.")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in address):
        raise CoinbaseError("Bech32 address contains an invalid character.")
    if address.lower() != address and address.upper() != address:
        raise CoinbaseError("Bech32 address cannot mix uppercase and lowercase.")
    address = address.lower()
    pos = address.rfind("1")
    if pos < 1 or pos + 7 > len(address):
        raise CoinbaseError("Bech32 separator/checksum is invalid.")
    hrp = address[:pos]
    try:
        data = [BECH32_MAP[ch] for ch in address[pos + 1:]]
    except KeyError as exc:
        raise CoinbaseError("Bech32 address contains an invalid character.") from exc
    polymod = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    if polymod == BECH32_CONST:
        encoding = "bech32"
    elif polymod == BECH32M_CONST:
        encoding = "bech32m"
    else:
        raise CoinbaseError("Bech32 checksum is invalid.")
    return hrp, data[:-6], encoding


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def _network_info(network):
    network = str(network or "main").lower()
    if network not in NETWORKS:
        raise CoinbaseError(f"Unsupported Bitcoin network: {network}")
    return network, NETWORKS[network]


def decode_payout_address(address, network="main"):
    """Validate a Bitcoin address locally and return its scriptPubKey metadata."""
    address = str(address or "").strip()
    network, info = _network_info(network)
    if not address:
        raise CoinbaseError("Enter a Bitcoin payout address first.")

    lower = address.lower()
    possible_bech32 = lower.startswith(("bc1", "tb1", "bcrt1"))
    if possible_bech32:
        hrp, data, encoding = _bech32_decode(address)
        if hrp != info["hrp"]:
            raise CoinbaseError(
                f"Address is for the '{hrp}' network, but Bitcoin Core is configured for {network}."
            )
        if not data:
            raise CoinbaseError("SegWit address has no witness version.")
        version = data[0]
        if version > 16:
            raise CoinbaseError("SegWit witness version is outside 0-16.")
        program_values = _convertbits(data[1:], 5, 8, False)
        if program_values is None:
            raise CoinbaseError("SegWit witness program has invalid padding.")
        program = bytes(program_values)
        if not 2 <= len(program) <= 40:
            raise CoinbaseError("SegWit witness program must be 2-40 bytes.")
        if version == 0:
            if encoding != "bech32":
                raise CoinbaseError("Witness v0 addresses must use Bech32, not Bech32m.")
            if len(program) not in (20, 32):
                raise CoinbaseError("Witness v0 program must be 20 or 32 bytes.")
        elif encoding != "bech32m":
            raise CoinbaseError("Witness v1+ addresses must use Bech32m.")

        opcode = 0x00 if version == 0 else 0x50 + version
        script = bytes([opcode, len(program)]) + program
        if version == 0 and len(program) == 20:
            kind = "P2WPKH"
        elif version == 0 and len(program) == 32:
            kind = "P2WSH"
        elif version == 1 and len(program) == 32:
            kind = "P2TR"
        else:
            kind = f"Witness v{version}"
        return {
            "valid": True,
            "address": address,
            "network": network,
            "type": kind,
            "encoding": encoding,
            "witness_version": version,
            "program_hex": program.hex(),
            "script_pubkey": script.hex(),
        }

    payload = _b58decode_check(address)
    if len(payload) != 21:
        raise CoinbaseError("Base58 Bitcoin address payload must be 21 bytes.")
    version = payload[0]
    h160 = payload[1:]
    kind = info["base58"].get(version)
    if not kind:
        other = "mainnet" if version in NETWORKS["main"]["base58"] else "test-style/unknown"
        raise CoinbaseError(
            f"Base58 address version does not match {network} ({other} address prefix)."
        )
    if kind == "P2PKH":
        script = b"\x76\xa9\x14" + h160 + b"\x88\xac"
    else:
        script = b"\xa9\x14" + h160 + b"\x87"
    return {
        "valid": True,
        "address": address,
        "network": network,
        "type": kind,
        "encoding": "base58check",
        "witness_version": None,
        "program_hex": h160.hex(),
        "script_pubkey": script.hex(),
    }


def _serialize_input(script_sig):
    return b"\x00" * 32 + (0xFFFFFFFF).to_bytes(4, "little") + _varint(len(script_sig)) + script_sig + (0xFFFFFFFF).to_bytes(4, "little")


def _serialize_output(value_sats, script_pubkey):
    value_sats = int(value_sats)
    if not 0 <= value_sats <= 21_000_000 * SATOSHIS_PER_BTC:
        raise CoinbaseError("Coinbase output value is outside Bitcoin's money range.")
    return value_sats.to_bytes(8, "little") + _varint(len(script_pubkey)) + script_pubkey



def _encode_extranonce(value, size):
    size = int(size)
    if value is None:
        return b"\x00" * size
    if isinstance(value, int):
        if value < 0 or value >= (1 << (size * 8)):
            raise CoinbaseError(f"Extranonce value does not fit in {size} bytes.")
        return int(value).to_bytes(size, "little")
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    else:
        text = str(value).strip().lower()
        if text.startswith("0x"):
            text = text[2:]
        try:
            raw = bytes.fromhex(text)
        except ValueError as exc:
            raise CoinbaseError("Extranonce must be an integer, bytes, or hexadecimal string.") from exc
    if len(raw) != size:
        raise CoinbaseError(f"Extranonce must be exactly {size} bytes.")
    return raw

def build_coinbase_transaction(template, payout_address, *, network="main", tag="Bitcoin Miner Studio", extranonce_size=8, extranonce_value=None):
    """Build a valid coinbase transaction preview for a normalized template."""
    if not isinstance(template, dict) or not template.get("available"):
        raise CoinbaseError("A ready getblocktemplate is required before building a coinbase transaction.")

    try:
        height = int(template.get("height") or 0)
        coinbase_value = int(template.get("coinbase_value_sats") or 0)
        extranonce_size = int(extranonce_size)
    except (TypeError, ValueError) as exc:
        raise CoinbaseError("Template/coinbase numeric fields are invalid.") from exc
    if height <= 0 or coinbase_value <= 0:
        raise CoinbaseError("Template height and coinbase value must be positive.")
    if not 4 <= extranonce_size <= 32:
        raise CoinbaseError("Extranonce placeholder size must be between 4 and 32 bytes.")

    payout = decode_payout_address(payout_address, network)
    tag_bytes = str(tag or "").encode("utf-8")
    if len(tag_bytes) > 64:
        raise CoinbaseError("Coinbase tag must be 64 UTF-8 bytes or fewer.")

    height_item = _script_num(height)
    script_sig = _push_data(height_item)

    aux_hex = str(template.get("coinbase_aux_flags") or "").strip()
    if aux_hex:
        try:
            aux = bytes.fromhex(aux_hex)
        except ValueError as exc:
            raise CoinbaseError("Template coinbaseaux.flags is not valid hexadecimal.") from exc
        script_sig += aux
    if tag_bytes:
        script_sig += _push_data(tag_bytes)
    extranonce_bytes = _encode_extranonce(extranonce_value, extranonce_size)
    script_sig += _push_data(extranonce_bytes)

    if not 2 <= len(script_sig) <= 100:
        raise CoinbaseError(
            f"Coinbase scriptSig is {len(script_sig)} bytes; consensus requires 2-100 bytes. Shorten the tag or extranonce."
        )

    txin = _serialize_input(script_sig)
    payout_script = bytes.fromhex(payout["script_pubkey"])
    outputs = [(coinbase_value, payout_script, "payout")]

    commitment_hex = str(template.get("default_witness_commitment") or "").strip()
    commitment_script = b""
    has_witness_commitment = False
    if commitment_hex:
        try:
            commitment_script = bytes.fromhex(commitment_hex)
        except ValueError as exc:
            raise CoinbaseError("Template default witness commitment is not valid hexadecimal.") from exc
        if not commitment_script.startswith(bytes.fromhex("6a24aa21a9ed")):
            raise CoinbaseError("Template witness commitment does not have the expected BIP141 prefix.")
        outputs.append((0, commitment_script, "witness_commitment"))
        has_witness_commitment = True

    outputs_blob = b"".join(_serialize_output(value, script) for value, script, _ in outputs)
    version = (2).to_bytes(4, "little")
    locktime = (0).to_bytes(4, "little")
    base_tx = version + _varint(1) + txin + _varint(len(outputs)) + outputs_blob + locktime

    if has_witness_commitment:
        witness_reserved = b"\x00" * 32
        witness = _varint(1) + _varint(len(witness_reserved)) + witness_reserved
        full_tx = version + b"\x00\x01" + _varint(1) + txin + _varint(len(outputs)) + outputs_blob + witness + locktime
    else:
        full_tx = base_tx

    txid = _hash256(base_tx)[::-1].hex()
    wtxid = _hash256(full_tx)[::-1].hex()
    base_size = len(base_tx)
    total_size = len(full_tx)
    weight = base_size * 3 + total_size
    vsize = (weight + 3) // 4
    fees_sats = int(template.get("total_fees_sats") or 0)
    subsidy_sats = template.get("subsidy_sats")

    return {
        "available": True,
        "status": "Ready",
        "network": network,
        "height": height,
        "payout_address": payout["address"],
        "payout_type": payout["type"],
        "payout_script_pubkey": payout["script_pubkey"],
        "coinbase_value_sats": coinbase_value,
        "coinbase_value_btc": coinbase_value / SATOSHIS_PER_BTC,
        "fees_sats": fees_sats,
        "fees_btc": fees_sats / SATOSHIS_PER_BTC,
        "subsidy_sats": subsidy_sats,
        "subsidy_btc": (int(subsidy_sats) / SATOSHIS_PER_BTC) if subsidy_sats is not None else None,
        "tag": str(tag or ""),
        "extranonce_size": extranonce_size,
        "extranonce_value": int.from_bytes(extranonce_bytes, "little"),
        "extranonce_hex": extranonce_bytes.hex(),
        "extranonce_placeholder_hex": extranonce_bytes.hex(),
        "coinbase_script_sig_hex": script_sig.hex(),
        "coinbase_script_sig_bytes": len(script_sig),
        "witness_commitment": commitment_script.hex(),
        "witness_commitment_present": has_witness_commitment,
        "witness_reserved_value": (b"\x00" * 32).hex() if has_witness_commitment else "",
        "output_count": len(outputs),
        "txid": txid,
        "wtxid": wtxid,
        "raw_transaction": full_tx.hex(),
        "base_transaction": base_tx.hex(),
        "base_size": base_size,
        "total_size": total_size,
        "weight": weight,
        "vsize": vsize,
        "error": "",
    }


def unavailable_coinbase(message="Enter and validate a payout address, then build the coinbase preview."):
    return {
        "available": False,
        "status": "Waiting",
        "network": "",
        "height": 0,
        "payout_address": "",
        "payout_type": "",
        "payout_script_pubkey": "",
        "coinbase_value_sats": 0,
        "coinbase_value_btc": 0.0,
        "fees_sats": 0,
        "fees_btc": 0.0,
        "subsidy_sats": None,
        "subsidy_btc": None,
        "tag": "",
        "extranonce_size": 0,
        "extranonce_value": 0,
        "extranonce_hex": "",
        "extranonce_placeholder_hex": "",
        "coinbase_script_sig_hex": "",
        "coinbase_script_sig_bytes": 0,
        "witness_commitment": "",
        "witness_commitment_present": False,
        "witness_reserved_value": "",
        "output_count": 0,
        "txid": "",
        "wtxid": "",
        "raw_transaction": "",
        "base_transaction": "",
        "base_size": 0,
        "total_size": 0,
        "weight": 0,
        "vsize": 0,
        "error": str(message or ""),
    }


def coinbase_report(state):
    if not state.get("available"):
        return f"COINBASE PREVIEW UNAVAILABLE\n\n{state.get('error') or 'Build a coinbase preview first.'}"
    subsidy = state.get("subsidy_btc")
    subsidy_text = f"{subsidy:.8f} BTC" if subsidy is not None else "unknown"
    return (
        "COINBASE & PAYOUT READY\n\n"
        f"Next block height: {state.get('height', 0):,}\n"
        f"Payout address: {state.get('payout_address')}\n"
        f"Address type: {state.get('payout_type')} ({state.get('network')})\n"
        f"Subsidy: {subsidy_text}\n"
        f"Template fees: {state.get('fees_btc', 0):.8f} BTC\n"
        f"Maximum coinbase value: {state.get('coinbase_value_btc', 0):.8f} BTC\n"
        f"Coinbase tag: {state.get('tag') or 'none'}\n"
        f"scriptSig: {state.get('coinbase_script_sig_bytes', 0)} bytes\n"
        f"Witness commitment: {'included' if state.get('witness_commitment_present') else 'not required'}\n"
        f"Coinbase TXID: {state.get('txid')}\n"
        f"Transaction size: {state.get('total_size', 0)} bytes / {state.get('weight', 0)} WU\n\n"
        "This is a transaction preview only. No private key or wallet seed is required or stored."
    )
