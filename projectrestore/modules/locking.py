# src/projectrestore/modules/locking.py

from __future__ import annotations
import os
import time
import logging
from pathlib import Path

LOG = logging.getLogger(__name__)


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    return True


def create_pid_lock(lockfile: Path, stale_seconds: int = 3600) -> None:
    pid_str = str(os.getpid())
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            fh.write(pid_str + "\n")
        LOG.debug("Acquired lock file %s", lockfile)
        return
    except FileExistsError:
        # inspect existing lock
        try:
            existing = lockfile.read_text().strip()
            existing_pid = int(existing.splitlines()[0]) if existing else None
        except Exception:
            existing_pid = None

        if existing_pid:
            if _is_process_alive(existing_pid):
                LOG.error(
                    "Another instance is running (pid=%s). Exiting.", existing_pid
                )
                raise SystemExit(3)
            else:
                # stale check by mtime
                try:
                    age = time.time() - lockfile.stat().st_mtime
                except Exception:
                    age = stale_seconds + 1
                if age < stale_seconds:
                    LOG.error(
                        "Lockfile contains stale pid %s but is not old enough (age %ds). Exiting.",
                        existing_pid,
                        int(age),
                    )
                    raise SystemExit(3)
                try:
                    lockfile.unlink()
                    LOG.warning(
                        "Removed stale lockfile (pid %s, age %ds). Retrying.",
                        existing_pid,
                        int(age),
                    )
                except Exception as e:
                    LOG.error("Failed to remove stale lockfile: %s", e)
                    raise SystemExit(3)
                # retry acquire
                try:
                    fd = os.open(str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    with os.fdopen(fd, "w") as fh:
                        fh.write(pid_str + "\n")
                    LOG.debug(
                        "Acquired lock file %s after removing stale lock.", lockfile
                    )
                    return
                except FileExistsError:
                    LOG.error(
                        "Failed to acquire lockfile after removing stale one. Exiting."
                    )
                    raise SystemExit(3)
        else:
            # unreadable content; remove if stale
            try:
                age = time.time() - lockfile.stat().st_mtime
            except Exception:
                age = stale_seconds + 1
            if age >= stale_seconds:
                try:
                    lockfile.unlink()
                    LOG.warning("Removed non-parseable, stale lockfile. Retrying.")
                except Exception as e:
                    LOG.error("Failed to remove non-parseable lockfile: %s", e)
                    raise SystemExit(3)
                try:
                    fd = os.open(str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    with os.fdopen(fd, "w") as fh:
                        fh.write(pid_str + "\n")
                    LOG.debug(
                        "Acquired lock file %s after removing non-parseable lock.",
                        lockfile,
                    )
                    return
                except FileExistsError:
                    LOG.error("Failed to acquire lockfile after cleanup. Exiting.")
                    raise SystemExit(3)
            else:
                LOG.error("Lockfile exists and is recent but unreadable. Exiting.")
                raise SystemExit(3)


def release_pid_lock(lockfile: Path) -> None:
    try:
        if lockfile.exists():
            content = lockfile.read_text().strip()
            if content.splitlines()[0] == str(os.getpid()) or not content:
                lockfile.unlink()
                LOG.debug("Released lock file %s", lockfile)
            else:
                LOG.debug(
                    "Lock file %s not owned by current pid (%s). Leaving it.",
                    lockfile,
                    os.getpid(),
                )
    except Exception:
        LOG.debug("Failed to release lock file %s (non-fatal)", lockfile)
