"""Content-addressed original-release archive outside the observation database.

Hash equality protects byte identity after upload. Publisher authenticity,
publication time and licence rights require independent human review.
"""
import hashlib
import os
import re
import tempfile
from pathlib import Path

MAX_BYTES = 750_000
REFERENCE = re.compile(r"^archive://sha256/([0-9a-f]{64})$")


def _directory() -> Path:
    root = os.getenv("SOURCE_ARCHIVE_ROOT")
    if not root or not Path(root).is_absolute():
        raise ValueError("SOURCE_ARCHIVE_ROOT must be an absolute isolated archive path")
    directory = Path(root) / "sha256"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Archive directory cannot be a symlink")
    return directory


def archive_original(raw: bytes) -> dict:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Original publisher file must be nonempty and at most 750 KB")
    digest = hashlib.sha256(raw).hexdigest()
    directory = _directory()
    destination = directory / digest
    temp_path = None
    created = False
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".upload-", delete=False) as handle:
            temp_path = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, destination)
            created = True
        except FileExistsError:
            pass
        stored = destination.read_bytes()
        if hashlib.sha256(stored).hexdigest() != digest or stored != raw:
            raise ValueError("Archived source bytes differ from submitted bytes")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return {"reference": f"archive://sha256/{digest}", "sha256": digest, "size_bytes": len(raw), "created": created}


def read_original(reference: str, expected_sha256: str) -> bytes:
    match = REFERENCE.fullmatch(reference)
    if not match or match.group(1) != expected_sha256:
        raise ValueError("Archive reference and source hash mismatch")
    path = _directory() / expected_sha256
    if path.is_symlink() or not path.is_file():
        raise ValueError("Original source release is missing from controlled archive")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Archived source bytes failed integrity check")
    return raw
