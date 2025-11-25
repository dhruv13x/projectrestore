#!/usr/bin/env python3
# src/projectrestore/cli.py

"""
extract_backup.py

production-ready, improved, hardened safe extractor

Highlights / safety improvements:
 - Robust PID-file locking with stale-lock detection and ownership checks.
 - Member-by-member safe extraction (no tar.extractall with raw names).
 - Rejects absolute paths, path traversal, symlinks, hardlinks, special device nodes.
 - Skips PAX/GNU metadata headers by default (configurable).
 - Optionally rejects GNU sparse members (conservative default: reject).
 - Extraction limits: max files, max unpacked bytes to guard against tarbombs.
 - Extracts into a sibling temporary directory, performs an atomic swap of the target
   directory using rename semantics, with rollback of the previous state on error.
 - Removes setuid/setgid bits from extracted files.
 - Optional sha256 checksum verification.
 - Dry-run that validates archive without writing to disk.
 - Signal handling and clear exit codes:
     0 - success
     1 - general failure
     2 - interrupted / cleanup
     3 - another instance is running

Usage: see --help for CLI options.
"""

from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

from projectrestore.modules.checksum import verify_sha256_from_file
from projectrestore.modules.extraction import safe_extract_atomic
from projectrestore.modules.locking import create_pid_lock, release_pid_lock
from projectrestore.modules.signals import GracefulShutdown
from projectrestore.modules.utils import count_files, find_latest_backup
from .banner import print_logo


LOG = logging.getLogger("extract_backup")
DEFAULT_BACKUP_DIR = Path("/sdcard/project_backups")
DEFAULT_PATTERN = "*-bot_platform-*.tar.gz"
DEFAULT_LOCKFILE = Path("/tmp/extract_backup.pid")


# ---------------- CLI ----------------
def setup_logging(level: int = logging.INFO) -> None:
    fmt = "%(asctime)s %(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Safely extract latest bot_platform backup")
    p.add_argument(
        "--backup-dir",
        "-b",
        default=str(DEFAULT_BACKUP_DIR),
        help="Directory containing backups",
    )
    p.add_argument(
        "--extract-dir",
        "-e",
        default=None,
        help="Extraction target directory (defaults to BACKUP_DIR/tmp_extract)",
    )
    p.add_argument(
        "--pattern", "-p", default=DEFAULT_PATTERN, help="Glob pattern to match backups"
    )
    p.add_argument(
        "--lockfile",
        "-l",
        default=str(DEFAULT_LOCKFILE),
        help="PID file used for locking",
    )
    p.add_argument(
        "--checksum",
        "-c",
        default=None,
        help="Optional checksum file (sha256). Format: '<hex> [filename]'",
    )
    p.add_argument(
        "--stale-seconds",
        type=int,
        default=3600,
        help="Seconds before a lock is considered stale",
    )
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Maximum number of files to extract (safety limit)",
    )
    p.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        help="Maximum total bytes to extract (safety limit)",
    )
    p.add_argument(
        "--allow-pax",
        action="store_true",
        help="Allow pax/global headers (they are skipped by default)",
    )
    p.add_argument(
        "--allow-sparse",
        action="store_true",
        help="Allow GNU sparse members (disabled by default)",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Validate archive without writing files"
    )
    p.add_argument(
        "--version", action="version", version=f"%(prog)s 2.0.0", help="Show program's version number and exit"
    )
    return p.parse_args()


def main() -> int:
    print_logo()
    args = parse_args()
    setup_logging(logging.DEBUG if args.debug else logging.INFO)

    backup_dir = Path(args.backup_dir).expanduser().resolve()
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else (backup_dir / "tmp_extract")
    )
    lockfile = Path(args.lockfile)

    LOG.info("Backup dir: %s", backup_dir)
    LOG.info("Extract dir: %s", extract_dir)
    LOG.info("Pattern: %s", args.pattern)

    if not backup_dir.exists() or not backup_dir.is_dir():
        LOG.error("Backup directory not found: %s", backup_dir)
        return 1

    # Ensure parent of extract dir exists
    try:
        extract_dir.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        LOG.error(
            "Unable to create extraction directory parent %s: %s",
            extract_dir.parent,
            exc,
        )
        return 1

    # Acquire lock
    try:
        create_pid_lock(lockfile, stale_seconds=args.stale_seconds)
    except SystemExit as se:
        return int(se.code) if isinstance(se.code, int) else 3
    except Exception as exc:
        LOG.exception("Failed to acquire lock: %s", exc)
        return 1

    # graceful shutdown to ensure lock release
    shutdown = GracefulShutdown()
    shutdown.register(lambda: release_pid_lock(lockfile))
    shutdown.install()

    try:
        latest = find_latest_backup(backup_dir, args.pattern)
        if latest is None:
            LOG.error(
                "No backup file found in %s matching %s", backup_dir, args.pattern
            )
            return 1

        LOG.info("Latest backup found: %s", latest)

        if args.checksum:
            ok = verify_sha256_from_file(latest, Path(args.checksum))
            if not ok:
                LOG.error("Integrity verification failed.")
                return 1

        LOG.info("Extracting %s -> %s", latest, extract_dir)
        try:
            safe_extract_atomic(
                latest,
                extract_dir,
                max_files=args.max_files,
                max_bytes=args.max_bytes,
                allow_pax=args.allow_pax,
                reject_sparse=not args.allow_sparse,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            LOG.exception("Extraction failed: %s", exc)
            return 1

        if not args.dry_run:
            total = count_files(extract_dir)
            LOG.info("Extraction complete. Total files extracted: %d", total)
        else:
            LOG.info("Dry-run validation successful.")
        return 0
    except SystemExit as se:
        return int(se.code) if isinstance(se.code, int) else 2
    finally:
        release_pid_lock(lockfile)


if __name__ == "__main__":
    try:
        rc = main()
    except KeyboardInterrupt:
        LOG.info("Interrupted by user")
        rc = 2
    sys.exit(rc)
