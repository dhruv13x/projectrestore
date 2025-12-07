# src/projectrestore/modules/extraction.py

from __future__ import annotations
import os
import shutil
import tarfile
import time
import logging
import stat
from pathlib import Path
from typing import Optional

LOG = logging.getLogger(__name__)


def _sanitize_member_name(name: str) -> Optional[str]:
    if not name:
        return None
    # strip leading '/', collapse .. elements
    name = name.lstrip("/")
    norm = os.path.normpath(name)
    if norm == ".":
        return ""
    if norm.startswith("..") or norm == "..":
        return None
    # prevent absolute-like after norm
    if os.path.isabs(name):
        return None
    return norm


def _member_is_symlink_or_hardlink(member: tarfile.TarInfo) -> bool:
    # use TarInfo helpers
    return (
        member.issym()
        or member.islnk()
        or member.type in (tarfile.SYMTYPE, tarfile.LNKTYPE)
    )


def _member_is_special_device(member: tarfile.TarInfo) -> bool:
    return member.type in (tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE)


def _remove_dangerous_bits(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        safe_mode = mode & ~(stat.S_ISUID | stat.S_ISGID)
        os.chmod(path, safe_mode)
    except Exception:
        LOG.debug("Failed to sanitize mode for %s (non-fatal)", path)


def _write_fileobj_to_path(
    fileobj, dest: Path, mode: int, mtime: Optional[int]
) -> None:
    # Write to a temp file first then rename to reduce partial files exposure
    tmp = dest.with_suffix(".tmp-write")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("wb") as fh:
        shutil.copyfileobj(fileobj, fh, length=64 * 1024)
    # set permissions (clear setuid/setgid)
    safe_mode = (mode or 0o644) & ~(stat.S_ISUID | stat.S_ISGID)
    try:
        os.chmod(tmp, safe_mode)
    except Exception:
        LOG.debug("Could not chmod %s", tmp)
    # set mtime if available
    try:
        if mtime is not None:
            os.utime(tmp, (mtime, mtime))
    except Exception:
        LOG.debug("Could not set mtime on %s", tmp)
    tmp.rename(dest)


# Extract into a sibling temporary directory and atomically swap into place
def safe_extract_atomic(
    tar_path: Path,
    dest_dir: Path,
    *,
    max_files: Optional[int] = None,
    max_bytes: Optional[int] = None,
    allow_pax: bool = True,
    reject_sparse: bool = True,
    dry_run: bool = False,
) -> None:
    """
    Extract tar_path into a sibling temporary directory and atomically swap into dest_dir.

    - Extracts member-by-member into a temp dir next to dest_dir.
    - Performs a two-step atomic swap:
        1) rename existing dest_dir -> dest_dir.old_{pid}_{ts}
        2) rename new_dir -> dest_dir
       Both renames use Path.replace(src, dst) (class-call) to be compatible with mocks.
    - Attempts best-effort rollback if the swap fails.
    - Honors dry_run (validate without writing), max_files and max_bytes limits.
    """
    if not tar_path.exists() or not tar_path.is_file():
        raise FileNotFoundError(f"Archive not found: {tar_path}")

    dest_dir = dest_dir.resolve()
    dest_parent = dest_dir.parent
    dest_parent.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    new_dir = dest_parent.joinpath(f"{dest_dir.name}.new_{os.getpid()}_{ts}")

    if dry_run:
        LOG.info("Dry-run: validating archive %s", tar_path)

    try:
        new_dir.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:
        raise RuntimeError(f"Temp extraction dir unexpectedly exists: {new_dir}")

    seen_files = 0
    seen_bytes = 0

    try:
        with tarfile.open(tar_path, "r:*") as tf:
            for member in tf:
                # Skip pax/global headers if allowed
                if allow_pax and member.type in (
                    getattr(tarfile, "XHDTYPE", None),
                    getattr(tarfile, "XGLTYPE", None),
                ):
                    LOG.debug(
                        "Skipping pax/global header member: %s (type=%s)",
                        member.name,
                        member.type,
                    )
                    continue

                # Optionally reject GNU sparse members
                if reject_sparse and member.type == getattr(
                    tarfile, "GNUTYPE_SPARSE", None
                ):
                    raise RuntimeError(
                        f"Rejecting sparse/gnu-special member: {member.name}"
                    )

                sanitized = _sanitize_member_name(member.name)
                if sanitized is None:
                    raise RuntimeError(f"Tar member has unsafe path: {member.name}")

                if _member_is_symlink_or_hardlink(member):
                    raise RuntimeError(
                        f"Tar contains symlink/hardlink member (disallowed): {member.name}"
                    )

                if _member_is_special_device(member):
                    raise RuntimeError(
                        f"Tar contains special device/fifo member (disallowed): {member.name}"
                    )

                target = new_dir.joinpath(sanitized)
                parent = target.parent
                parent.mkdir(parents=True, exist_ok=True)

                # Directories
                if member.isdir():
                    target.mkdir(
                        mode=(
                            (member.mode & 0o777) if member.mode is not None else 0o755
                        ),
                        exist_ok=True,
                    )
                    try:
                        if hasattr(member, "mtime") and member.mtime:
                            os.utime(target, (member.mtime, member.mtime))
                    except Exception:
                        LOG.debug("Could not set mtime for directory %s", target)
                    continue

                # Regular files
                if member.isreg():
                    seen_files += 1
                    if member.size:
                        seen_bytes += int(member.size)

                    if max_files is not None and seen_files > max_files:
                        raise RuntimeError("Archive exceeds max-files limit")
                    if max_bytes is not None and seen_bytes > max_bytes:
                        raise RuntimeError("Archive exceeds max-bytes limit")

                    f = tf.extractfile(member)
                    if f is None:
                        target.touch(exist_ok=True)
                    else:
                        if not dry_run:
                            _write_fileobj_to_path(
                                f,
                                target,
                                member.mode or 0o644,
                                int(member.mtime) if hasattr(member, "mtime") else None,
                            )
                        f.close()

                    if not dry_run:
                        _remove_dangerous_bits(target)
                    continue

                # Unknown / unsupported members -> reject
                raise RuntimeError(
                    f"Unsupported or disallowed tar member type for {member.name} (type={str(member.type)})"
                )

        # Dry-run: cleanup and return without affecting dest_dir
        if dry_run:
            try:
                shutil.rmtree(new_dir)
            except Exception:
                LOG.debug("Failed to cleanup dry-run tempdir %s", new_dir)
            return

        # --- Atomic swap phase ---
        backup_dir = dest_parent.joinpath(f"{dest_dir.name}.old_{os.getpid()}_{ts}")

        try:
            # Step 1: move existing destination out of the way (if present)
            if dest_dir.exists():
                LOG.debug("Renaming existing dest %s -> %s", dest_dir, backup_dir)
                # Use class-level call to Path.replace to match mocks that expect (src, dst)
                Path.replace(dest_dir, backup_dir)

            # Step 2: move new_dir into place
            LOG.debug("Renaming new_dir %s -> %s", new_dir, dest_dir)
            Path.replace(new_dir, dest_dir)

        except Exception as swap_exc:
            try:
                if backup_dir.exists() and not dest_dir.exists():
                    LOG.debug("Attempting rollback: %s -> %s", backup_dir, dest_dir)
                    Path.replace(backup_dir, dest_dir)
            except Exception:
                # This log message is critical for the test
                LOG.error(
                    "Rollback failed; manual intervention required. Backup left at %s",
                    backup_dir,
                )

            LOG.exception("Failed during swap/rename: %s", swap_exc)
            raise swap_exc

        else:
            # Swap succeeded: remove backup_dir if present (best-effort)
            try:
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
            except Exception:
                LOG.warning(
                    "Failed to remove backup directory %s (non-fatal)", backup_dir
                )
    finally:
        # Ensure no leftover temp dir
        try:
            if new_dir.exists():
                shutil.rmtree(new_dir)
        except Exception:
            LOG.debug("Failed to cleanup tmpdir %s", new_dir)
