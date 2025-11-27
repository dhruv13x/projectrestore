# src/projectrestore/modules/utils.py

from __future__ import annotations
from pathlib import Path
from typing import Optional


def count_files(path: Path) -> int:
    return sum(1 for _ in path.rglob("*") if _.is_file())


def find_latest_backup(backup_dir: Path, pattern: str) -> Optional[Path]:
    if not backup_dir.exists() or not backup_dir.is_dir():
        return None
    files = [p for p in backup_dir.iterdir() if p.is_file() and p.match(pattern)]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]
