"""Content-addressed original-release archive outside the observation database.

Hash equality protects byte identity after upload. Publisher authenticity,
publication time and licence rights require independent human review.
"""
import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

DEFAULT_MAX_BYTES = 4_000_000
HARD_MAX_BYTES = 8_000_000
REFERENCE = re.compile(r"^archive://sha256/([0-9a-f]{64})$")


def max_bytes() -> int:
    try:
        value = int(os.getenv("SOURCE_ARCHIVE_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
    except ValueError as exc:
        raise ValueError("SOURCE_ARCHIVE_MAX_BYTES must be an integer") from exc
    if not 750_000 <= value <= HARD_MAX_BYTES:
        raise ValueError("SOURCE_ARCHIVE_MAX_BYTES must be between 750000 and 8000000")
    return value


def _directory() -> Path:
    root = os.getenv("SOURCE_ARCHIVE_ROOT")
    if not root or not Path(root).is_absolute():
        raise ValueError("SOURCE_ARCHIVE_ROOT must be an absolute isolated archive path")
    root_path = Path(root)
    if root_path.is_symlink():
        raise ValueError("Archive root cannot be a symlink")
    directory = root_path / "sha256"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Archive directory cannot be a symlink")
    return directory


def archive_original(raw: bytes) -> dict:
    if not raw or len(raw) > max_bytes():
        raise ValueError("Original publisher file exceeds configured archive limit")
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
        stored = _read_checked(destination, max_bytes())
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
    raw = _read_checked(path, max_bytes())
    if not raw or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Archived source bytes failed integrity check")
    return raw


def _read_checked(path: Path, limit: int) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ValueError("Original source release is missing from controlled archive") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError("Archived source file is not a bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Archived source file exceeds configured limit")
        return raw
    finally:
        os.close(fd)
