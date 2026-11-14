"""Offline final-distribution seal; never run this private-key step in CI."""
import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from purple_dragon_security import verify_integrity, publisher_key_id, PRODUCT_NAME
from reliability_io import atomic_json_write
from tools.publisher_key import load_publisher_key
from update_release_center import _canonical_manifest, verify_release_folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("private_key", type=Path)
    args = parser.parse_args()
    distribution = args.distribution.resolve()
    if distribution == ROOT or not (distribution / "_runtime/python.exe").is_file():
        parser.error("Select an extracted Windows distribution, not the source checkout.")
    source = verify_integrity(distribution)
    if not source["verified"]:
        parser.error("Distribution source signature/files must verify before runtime sealing.")
    manifest_path = distribution / "purple_dragon_manifest.json"
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    protected = set(source_manifest["files"])
    files = {}
    for path in sorted(distribution.rglob("*")):
        if path.is_symlink():
            parser.error("Distribution must not contain symbolic links.")
        if not path.is_file():
            continue
        relative = path.relative_to(distribution).as_posix()
        if relative in protected or relative in {"purple_dragon_manifest.json", "purple_dragon_runtime.json", "native-smoke.json"}:
            continue
        if "__pycache__" in path.relative_to(distribution).parts and not relative.startswith("_runtime/"):
            continue
        if path.suffix.lower() in {".pem", ".key", ".pfx", ".p12", ".log", ".db", ".sqlite", ".sqlite3"}:
            parser.error("Distribution contains private/runtime material that must not be sealed.")
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    key = load_publisher_key(args.private_key, ROOT)
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    inventory = {"schema": 1, "product": PRODUCT_NAME, "version": source["release_version"],
                 "publisher_key_id": publisher_key_id(), "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                 "files": files, "signature": ""}
    inventory["signature"] = base64.b64encode(key.sign(_canonical_manifest(inventory), padding.PKCS1v15(), hashes.SHA256())).decode("ascii")
    atomic_json_write(distribution / "purple_dragon_runtime.json", inventory)
    trust = verify_release_folder(distribution)
    if not trust["trusted"]:
        raise SystemExit("Final sealed distribution failed verification: " + "; ".join(trust["errors"]))
    print(json.dumps({"trusted": True, "source_files": len(protected), "runtime_files": len(files), "total_verified": trust["files_verified"]}, indent=2))


if __name__ == "__main__":
    main()
