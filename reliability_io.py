"""Durable local writes shared by settings, session and workspace storage."""
import json
import os
import tempfile
import uuid
import math
from pathlib import Path


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=_reject_constant,
                      parse_float=_finite_float)


def preserve_corrupt_file(path):
    """Move private damaged input aside; return False if it must not be overwritten."""
    path = Path(path)
    try:
        path.replace(path.with_name(path.stem + ".corrupt-" + uuid.uuid4().hex + path.suffix))
        return True
    except OSError:
        return False


def atomic_json_write(path, value):
    path = Path(path)
    payload = json.dumps(value, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=path.stem + "-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
