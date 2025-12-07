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
import os
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

# Try to import RichHelpFormatter for better help output
try:
    from rich_argparse import RichHelpFormatter
except ImportError:
    RichHelpFormatter = argparse.HelpFormatter

# Define custom theme
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "command": "bold magenta",
})
console = Console(theme=custom_theme)

from projectrestore.modules.checksum import verify_sha256_from_file
from projectrestore.modules.extraction import safe_extract_atomic
from projectrestore.modules.locking import create_pid_lock, release_pid_lock
from projectrestore.modules.signals import GracefulShutdown
from projectrestore.modules.utils import count_files, find_latest_backup
from .banner import print_logo
from . import restore_engine

LOG = logging.getLogger("extract_backup")
DEFAULT_BACKUP_DIR = Path.home() / "project_backups"
DEFAULT_PATTERN = "*-bot_platform-*.tar.gz"
DEFAULT_LOCKFILE = Path("/tmp/extract_backup.pid")


def print_restore_help():
    """Prints the help panel for the restore command using rich."""
    help_text = Text.from_markup(
        """
This command safely restores a project from a `.tar.gz` archive created by `pv clone --archive`.

[bold yellow]Note:[/bold yellow] If you created a standard folder backup (without --archive), you can simply copy/move that folder back to your workspace location using your system's file manager or `cp` command.

[bold green]Usage Examples:[/bold green]
  [cyan]pv restore[/cyan]                          Restore the latest backup from the default location.
  [cyan]pv restore --file backup.tar.gz[/cyan]     Restore a specific archive file.
  [cyan]pv restore --cloud --bucket B --file F[/cyan]  Download from cloud and restore.
  [cyan]pv restore --dry-run[/cyan]                Validate an archive without extracting it.

[bold green]Key Options:[/bold green]
  [yellow]--backup-dir <PATH>[/yellow]     Directory containing the local backups.
  [yellow]--extract-dir <PATH>[/yellow]    Directory to extract the project to.
  [yellow]--file <FILENAME>[/yellow]       Specify a particular backup archive to restore.
  [yellow]--checksum <FILE>[/yellow]       Verify archive integrity with a `.sha256` file.
  [yellow]--cloud[/yellow]                 Download the specified --file from cloud storage.
  [yellow]--bucket <NAME>[/yellow]         Cloud bucket name (required for --cloud).
  [yellow]--dry-run[/yellow]               Validate the archive without writing any files.
"""
    )
    panel = Panel(
        help_text,
        title="[bold magenta]Help: `pv restore` (Restore Command)[/bold magenta]",
        border_style="blue",
    )
    console.print(panel)


class RichHelpAction(argparse.Action):
    """A custom argparse action to show a rich-formatted help panel and exit."""
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print_restore_help()
        parser.exit()


def get_cloud_credentials(resolver=None):
    """
    Resolves cloud credentials using the main project-vault resolver
    to ensure sources like Doppler are included.
    """
    if resolver is None:
        try:
            # Import the main credential resolver from the common library
            from src.common import credentials as resolver
        except ImportError:
            # This can happen if the tool is run standalone without the full vault shell
            print("Error: Could not import 'src.common.credentials' for cloud operations.", file=sys.stderr)
            return None, None, None

    # Use a dummy args object for the resolver
    class DummyArgs:
        key_id = None
        secret_key = None

    # Resolve credentials from all sources (CLI, Doppler, Env, Config)
    key_id, secret_key, source = resolver.resolve_credentials(DummyArgs(), allow_fail=True)

    # If keys are found, determine the provider type (b2 or s3)
    if key_id and secret_key:
        provider_info, _, _ = resolver.get_cloud_provider_info()
        provider_type = None
        if provider_info == "Backblaze B2":
            provider_type = "b2"
        elif provider_info == "AWS S3":
            provider_type = "s3"
        
        # Log the source for better debugging
        logging.info(f"Authenticated via {source}")
        return provider_type, key_id, secret_key
    
    return None, None, None


def download_from_cloud(bucket_name, remote_filename, local_dest, endpoint=None):
    """
    Downloads a file from the cloud.
    """
    try:
        from src.common import b2, s3
    except ImportError:
        # Try relative import if we are inside the pv structure
        try:
            import sys
            current = Path(__file__).resolve()
            # projectrestore/projectrestore/cli.py -> ... -> tools/project_vault
            # We need to find where src/common is.
            # Assuming standard layout: project_vault/src/common
            # We are in project_vault/projectrestore/projectrestore
            # So we need to go up 3 levels to project_vault, then into src
            root = current.parents[2]
            sys.path.insert(0, str(root / "src"))
            from src.common import b2, s3
        except ImportError:
            LOG.error("Could not import 'src.common'. Cloud features require the full Project Vault environment.")
            return False

    provider, key_id, app_key = get_cloud_credentials()
    if not key_id or not app_key:
        LOG.error("Missing cloud credentials.")
        return False

    manager = None
    try:
        if endpoint or provider == "s3":
             manager = s3.S3Manager(key_id, app_key, bucket_name, endpoint)
        else:
             manager = b2.B2Manager(key_id, app_key, bucket_name)
    except Exception as e:
        LOG.error("Error initializing cloud connection: %s", e)
        return False

    LOG.info("Downloading %s from bucket '%s'...", remote_filename, bucket_name)
    try:
        manager.download_file(remote_filename, str(local_dest))
        LOG.info("✅ Download successful: %s", local_dest)
        return True
    except Exception as e:
        LOG.error("❌ Download failed: %s", e)
        return False


def vault_restore_main() -> None:
    parser = argparse.ArgumentParser(prog="projectrestore vault-restore", description="Restore from content-addressable vault", formatter_class=RichHelpFormatter)
    parser.add_argument("manifest", help="Path to the snapshot manifest file")
    parser.add_argument("dest", help="Destination directory to restore to")
    args = parser.parse_args(sys.argv[2:])

    try:
        manifest_path = os.path.abspath(os.path.expanduser(os.path.expandvars(args.manifest)))
        dest_path = os.path.abspath(os.path.expanduser(os.path.expandvars(args.dest)))
        restore_engine.restore_snapshot(manifest_path, dest_path)
    except Exception as e:
        console.print(f"[error]Error: {e}[/error]")
        sys.exit(1)


# ---------------- CLI ----------------
def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)]
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Safely extract latest bot_platform backup",
        add_help=False # Disable default help
    )
    p.add_argument('-h', '--help', action=RichHelpAction, help='Show this help message and exit.')
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
    p.add_argument("--cloud", action="store_true", help="Download archive from cloud before extracting")
    p.add_argument("--bucket", help="Cloud bucket name (required for --cloud)")
    p.add_argument("--endpoint", help="Cloud endpoint URL")
    p.add_argument("--file", help="Specific archive filename to download/extract (required for --cloud)")
    p.add_argument(
        "--version", action="version", version=f"%(prog)s 1.0.0", help="Show program's version number and exit"
    )
    
    # If no arguments are given (or only -h), show the custom help
    if len(sys.argv) <= 1:
        print_restore_help()
        sys.exit(0)

    return p.parse_args()


def main() -> int:
    print_logo()
    if len(sys.argv) > 1 and sys.argv[1] == "vault-restore":
        vault_restore_main()
        return 0

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

    if not backup_dir.exists():
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            LOG.error("Could not create backup dir %s: %s", backup_dir, e)
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
        latest = None
        
        if args.cloud:
            if not args.bucket or not args.file:
                LOG.error("Error: --cloud requires --bucket and --file")
                return 1
            
            local_target = backup_dir / args.file
            
            # Check if already exists? For safety, maybe overwrite or check size?
            # For now, we assume user wants to re-download if they asked for it.
            if not download_from_cloud(args.bucket, args.file, local_target, args.endpoint):
                LOG.error("Failed to download backup from cloud.")
                return 1
            
            latest = local_target
            
        elif args.file:
            # User specified a local file explicitly
            candidate = backup_dir / args.file
            if candidate.exists():
                latest = candidate
            else:
                # Try absolute path
                candidate = Path(args.file).resolve()
                if candidate.exists():
                    latest = candidate
        else:
            # Auto-discovery
            latest = find_latest_backup(backup_dir, args.pattern)

        if latest is None or not latest.exists():
            LOG.error(
                "No backup file found matching request in %s", backup_dir
            )
            return 1

        LOG.info("Target backup: %s", latest)

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
