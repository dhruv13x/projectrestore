#!/usr/bin/env python3
# tests/test_cli.py

"""
test_projectrestore.cli.py - Unit and integration tests for projectrestore.cli.py
"""

import shutil
import tempfile
import signal
import os
import sys
from pathlib import Path
import unittest
from unittest import mock

# Fix import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from projectrestore import cli


class TestCLIIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.backup_dir = self.temp_dir / "backups"
        self.backup_dir.mkdir()
        self.tar_path = self.backup_dir / "test-bot_platform-2023.tar.gz"
        self.tar_path.touch()  # Mock backup

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @mock.patch("projectrestore.cli.safe_extract_atomic")
    @mock.patch("projectrestore.cli.find_latest_backup")
    @mock.patch("projectrestore.cli.count_files")
    def test_main_success(self, mock_count, mock_find, mock_extract):
        mock_find.return_value = self.tar_path
        mock_count.return_value = 1

        with mock.patch(
            "projectrestore.cli.sys.argv",
            ["script.py", "--backup-dir", str(self.backup_dir)],
        ):
            rc = cli.main()

        self.assertEqual(rc, 0)
        mock_extract.assert_called_once()
        mock_count.assert_called_once_with(mock.ANY)

    @mock.patch("projectrestore.cli.safe_extract_atomic")
    @mock.patch("projectrestore.cli.find_latest_backup")
    def test_main_dry_run_success(self, mock_find, mock_extract):
        mock_find.return_value = self.tar_path

        with mock.patch(
            "projectrestore.cli.sys.argv",
            ["script.py", "--backup-dir", str(self.backup_dir), "--dry-run"],
        ):
            rc = cli.main()

        self.assertEqual(rc, 0)
        mock_extract.assert_called_once_with(
            self.tar_path,
            self.backup_dir / "tmp_extract",
            max_files=None,
            max_bytes=None,
            allow_pax=False,
            reject_sparse=True,
            dry_run=True,
        )

    def test_main_no_backup_dir(self):
        with mock.patch(
            "projectrestore.cli.sys.argv", ["script.py", "--backup-dir", "/nonexistent"]
        ):
            rc = cli.main()
        self.assertEqual(rc, 1)

    @mock.patch("projectrestore.cli.find_latest_backup")
    def test_main_no_backup_file(self, mock_find):
        mock_find.return_value = None
        with mock.patch(
            "projectrestore.cli.sys.argv",
            ["script.py", "--backup-dir", str(self.backup_dir)],
        ):
            rc = cli.main()
        self.assertEqual(rc, 1)
        mock_find.assert_called_once()

    @mock.patch("projectrestore.cli.find_latest_backup")
    @mock.patch("projectrestore.cli.verify_sha256_from_file", return_value=False)
    def test_main_checksum_fail(self, mock_verify, mock_find):
        mock_find.return_value = self.tar_path
        with mock.patch(
            "projectrestore.cli.sys.argv",
            [
                "script.py",
                "--backup-dir",
                str(self.backup_dir),
                "--checksum",
                "check.txt",
            ],
        ):
            rc = cli.main()
        self.assertEqual(rc, 1)
        mock_verify.assert_called_once()

    @mock.patch.object(cli.Path, "mkdir", side_effect=OSError("mkdir fail"))
    def test_main_extract_dir_parent_fail(self, mock_mkdir):
        bad_extract = Path("/root/nonexistent/extract")
        with mock.patch(
            "projectrestore.cli.sys.argv",
            [
                "script.py",
                "--backup-dir",
                str(self.backup_dir),
                "--extract-dir",
                str(bad_extract),
            ],
        ):
            rc = cli.main()
        self.assertEqual(rc, 1)

    def test_graceful_shutdown_signals(self):
        """Test that GracefulShutdown registers signal handlers."""
        with mock.patch("signal.signal") as mock_signal:
            shutdown = cli.GracefulShutdown()
            shutdown.install()

            # Verify handlers registered for SIGINT and SIGTERM.
            # The handler is 'shutdown._handler', so we can check if it was called with that.
            calls = [
                mock.call(signal.SIGINT, shutdown._handler),
                mock.call(signal.SIGTERM, shutdown._handler)
            ]
            mock_signal.assert_has_calls(calls, any_order=True)

    @mock.patch("projectrestore.cli.create_pid_lock")
    def test_pidfile_locking_failure(self, mock_create_lock):
        """Simulate pidfile locking failure (another instance running)."""
        # Simulate SystemExit raised by create_pid_lock when locked
        mock_create_lock.side_effect = SystemExit(3)

        with mock.patch(
            "projectrestore.cli.sys.argv",
            ["script.py", "--backup-dir", str(self.backup_dir)],
        ):
            rc = cli.main()

        self.assertEqual(rc, 3)
        mock_create_lock.assert_called_once()

    @mock.patch("projectrestore.cli.find_latest_backup")
    @mock.patch("projectrestore.cli.safe_extract_atomic")
    def test_invalid_archive_handling(self, mock_extract, mock_find):
        """Run against a corrupted .tar.gz file (simulated by exception)."""
        mock_find.return_value = self.tar_path
        # Simulate extraction failure
        mock_extract.side_effect = ValueError("Invalid tar header")

        with mock.patch(
            "projectrestore.cli.sys.argv",
            ["script.py", "--backup-dir", str(self.backup_dir)],
        ):
            rc = cli.main()

        self.assertEqual(rc, 1) # General failure
        mock_extract.assert_called_once()

    def test_vault_restore_subcommand(self):
        """Test vault-restore subcommand dispatch."""
        with mock.patch("projectrestore.restore_engine.restore_snapshot") as mock_restore, \
             mock.patch("projectrestore.cli.sys.argv", ["script.py", "vault-restore", "manifest.json", "dest_dir"]), \
             mock.patch("projectrestore.cli.print_logo"):

            rc = cli.main()
            self.assertEqual(rc, 0)
            mock_restore.assert_called_once_with(os.path.abspath("manifest.json"), os.path.abspath("dest_dir"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
