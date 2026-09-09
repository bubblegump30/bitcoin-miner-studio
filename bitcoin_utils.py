import hashlib
from decimal import Decimal, InvalidOperation, getcontext

getcontext().prec = 90

DIFF1_TARGET = int(
    "00000000ffff0000000000000000000000000000000000000000000000000000", 16
)
MAX_TARGET = (1 << 256) - 1


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def difficulty_to_target(difficulty) -> int:
    try:
        d = Decimal(str(difficulty))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid pool difficulty.") from exc
    if d <= 0:
        raise ValueError("Pool difficulty must be greater than zero.")
    target = int(Decimal(DIFF1_TARGET) / d)
    return max(1, min(MAX_TARGET, target))


def target_to_difficulty(target: int) -> float:
    target = int(target)
    if target <= 0:
        return 0.0
    return float(Decimal(DIFF1_TARGET) / Decimal(target))


def swap_prevhash_words(prevhash_hex: str) -> bytes:
    """
    Stratum V1 Bitcoin prevhash is commonly supplied in 4-byte-word-swapped form.
    Reverse each 4-byte word to obtain the bytes used in the serialized header.
    """
    raw = bytes.fromhex(prevhash_hex)
    if len(raw) != 32:
        raise ValueError("prevhash must be exactly 32 bytes.")
    return b"".join(raw[i:i + 4][::-1] for i in range(0, 32, 4))


def build_coinbase(coinb1: str, extranonce1: str, extranonce2: str, coinb2: str) -> bytes:
    return bytes.fromhex(coinb1 + extranonce1 + extranonce2 + coinb2)


def calculate_merkle_root(
    coinb1: str,
    extranonce1: str,
    extranonce2: str,
    coinb2: str,
    merkle_branch,
) -> bytes:
    merkle = sha256d(build_coinbase(coinb1, extranonce1, extranonce2, coinb2))
    for branch_hex in merkle_branch:
        branch = bytes.fromhex(branch_hex)
        if len(branch) != 32:
            raise ValueError("Every merkle branch hash must be 32 bytes.")
        merkle = sha256d(merkle + branch)
    return merkle


def make_extranonce2(counter: int, size: int) -> str:
    size = int(size)
    if size < 1 or size > 16:
        raise ValueError("Unsupported extranonce2 size.")
    modulus = 1 << (size * 8)
    return (int(counter) % modulus).to_bytes(size, "big").hex()


def build_header_prefix(job: dict, extranonce1: str, extranonce2: str):
    """
    Build the fixed 76-byte portion of a Bitcoin block header for Stratum V1.
    The 4-byte nonce is appended by the mining worker.
    """
    version = bytes.fromhex(job["version"])[::-1]
    if len(version) != 4:
        raise ValueError("version must be 4 bytes.")

    prevhash = swap_prevhash_words(job["prevhash"])

    merkle_root = calculate_merkle_root(
        job["coinb1"],
        extranonce1,
        extranonce2,
        job["coinb2"],
        job["merkle_branch"],
    )

    ntime = bytes.fromhex(job["ntime"])[::-1]
    nbits = bytes.fromhex(job["nbits"])[::-1]
    if len(ntime) != 4 or len(nbits) != 4:
        raise ValueError("ntime and nbits must be 4 bytes.")

    prefix = version + prevhash + merkle_root + ntime + nbits
    if len(prefix) != 76:
        raise ValueError(f"Header prefix is {len(prefix)} bytes; expected 76.")
    return prefix, merkle_root
