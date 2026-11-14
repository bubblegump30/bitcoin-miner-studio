"""Load the existing offline publisher key without extracting key archives."""
import zipfile
from pathlib import Path


def load_publisher_key(path, repository_root):
    from cryptography.hazmat.primitives import serialization
    from purple_dragon_security import PUBLIC_MODULUS, PUBLIC_EXPONENT
    path = Path(path).expanduser().resolve()
    if path.is_relative_to(Path(repository_root).resolve()):
        raise ValueError("Publisher private-key material must remain outside the repository.")
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            candidates = [item for item in archive.infolist() if "private" in item.filename.lower()
                          and item.filename.lower().endswith((".pem", ".key")) and item.file_size <= 65536]
            if len(candidates) != 1:
                raise ValueError("Publisher archive must contain exactly one private PEM/key entry.")
            private_bytes = archive.read(candidates[0])
    else:
        private_bytes = path.read_bytes()
    key = serialization.load_pem_private_key(private_bytes, password=None)
    public = key.public_key().public_numbers()
    if public.n != PUBLIC_MODULUS or public.e != PUBLIC_EXPONENT:
        raise ValueError("Publisher key does not match the embedded Purple Dragon public identity.")
    return key
