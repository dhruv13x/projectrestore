#!/usr/bin/env python3
"""
test_projectrestore.cli.py - Unit and integration tests for projectrestore.cli.py

Run with: python -m unittest discover . (or pytest if available, but using stdlib unittest)

Requires: The projectrestore.cli.py script in the same directory.
Tests focus on core functions; file-system heavy tests use temp dirs.
Mocking used for PID/signal parts to avoid flakiness.
"""

import shutil
import tempfile
from pathlib import Path
import unittest
from unittest import mock

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
