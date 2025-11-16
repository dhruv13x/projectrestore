# tests/modules/test_utils.py

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from projectrestore.modules import utils


class TestFindLatestBackup(unittest.TestCase):
    def setUp(self):
        self.backup_dir = Path(tempfile.mkdtemp())
        self.pattern = "test-*.tar.gz"

    def tearDown(self):
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)

    def test_find_latest(self):
        # Create files with mtimes
        file1 = self.backup_dir / "test-old-1.tar.gz"
        file1.touch()
        time.sleep(0.1)
        file2 = self.backup_dir / "test-new-2.tar.gz"
        file2.touch()

        latest = utils.find_latest_backup(self.backup_dir, self.pattern)
        self.assertEqual(latest, file2)

    def test_no_match(self):
        latest = utils.find_latest_backup(self.backup_dir, self.pattern)
        self.assertIsNone(latest)

    def test_non_dir(self):
        non_dir = Path(tempfile.mktemp())
        with patch("projectrestore.modules.utils.Path") as mock_path:
            mock_instance = mock_path.return_value
            mock_instance.exists.return_value = False
            latest = utils.find_latest_backup(non_dir, self.pattern)
            self.assertIsNone(latest)


class TestCountFiles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        (self.temp_dir / "file1.txt").touch()
        (self.temp_dir / "dir").mkdir()
        (self.temp_dir / "dir" / "file2.txt").touch()  # only files counted

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_count(self):
        count = utils.count_files(self.temp_dir)
        self.assertEqual(count, 2)
