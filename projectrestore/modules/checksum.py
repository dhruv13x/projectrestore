# src/projectrestore/modules/checksum.py

from __future__ import annotations
import hashlib
import logging
from pathlib import Path

LOG = logging.getLogger(__name__)


def compute_sha256(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_sha256_from_file(archive: Path, checksum_file: Path) -> bool:
    try:
        text = checksum_file.read_text().strip().split()
        if not text:
            LOG.error("Checksum file %s is empty", checksum_file)
            return False
        declared = text[0].strip()
        actual = compute_sha256(archive)
        if declared.lower() == actual.lower():
            LOG.debug("Checksum match: %s", actual)
            return True
        LOG.error("Checksum mismatch: declared=%s actual=%s", declared, actual)
        return False
    except Exception as e:
        LOG.exception("Failed to verify checksum: %s", e)
        return False
