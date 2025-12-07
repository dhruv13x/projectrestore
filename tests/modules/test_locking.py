# tests/modules/test_locking.py

import os
import stat
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil
import sys

# Fix import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from projectrestore.modules import locking


class TestLocking(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.lockfile = self.temp_dir / "test.pid"

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        # Reset signal handlers if needed
        import signal

        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def test_create_release_lock(self):
        locking.create_pid_lock(self.lockfile)
        self.assertTrue(self.lockfile.exists())
        content = self.lockfile.read_text().strip()
        self.assertEqual(content, str(os.getpid()))

        locking.release_pid_lock(self.lockfile)
        self.assertFalse(self.lockfile.exists())

    @patch("projectrestore.modules.locking._is_process_alive")
    @patch("time.time")
    def test_stale_lock(self, mock_time, mock_alive):
        mock_alive.return_value = False
        current_time = 10000.0
        mock_time.return_value = current_time
        
        stale_pid = 12345
        self.lockfile.write_text(str(stale_pid))
        
        old_mtime = current_time - 4000
        os.utime(self.lockfile, (old_mtime, old_mtime))

        locking.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertTrue(self.lockfile.exists())
        self.assertEqual(self.lockfile.read_text().strip(), str(os.getpid()))

    @patch("projectrestore.modules.locking._is_process_alive")
    def test_running_instance(self, mock_alive):
        mock_alive.return_value = True
        self.lockfile.write_text("99999")

        with self.assertRaises(SystemExit) as cm:
            locking.create_pid_lock(self.lockfile)
        self.assertEqual(cm.exception.code, 3)

    def test_release_not_owned(self):
        self.lockfile.write_text("99999")
        locking.release_pid_lock(self.lockfile)
        self.assertTrue(self.lockfile.exists())

    @patch("projectrestore.modules.locking._is_process_alive")
    @patch("time.time")
    @patch("pathlib.Path.unlink", side_effect=OSError("unlink fail"))
    def test_stale_remove_fail(self, mock_unlink, mock_time, mock_alive):
        mock_alive.return_value = False
        current_time = 10000.0
        mock_time.return_value = current_time
        
        self.lockfile.write_text("12345")
        old_mtime = current_time - 4000
        os.utime(self.lockfile, (old_mtime, old_mtime))

        with self.assertRaises(SystemExit) as cm:
            locking.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertEqual(cm.exception.code, 3)
        mock_unlink.assert_called_once()

    @patch("projectrestore.modules.locking._is_process_alive")
    @patch("time.time")
    def test_stale_not_old_enough(self, mock_time, mock_alive):
        mock_alive.return_value = False
        current_time = 10000.0
        mock_time.return_value = current_time
        
        self.lockfile.write_text("12345")
        old_mtime = current_time - 3000
        os.utime(self.lockfile, (old_mtime, old_mtime))

        with self.assertRaises(SystemExit) as cm:
            locking.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertEqual(cm.exception.code, 3)

    @patch("time.time")
    @patch("pathlib.Path.unlink", return_value=None)
    def test_unreadable_stale_remove(self, mock_unlink, mock_time):
        current_time = 10000.0
        mock_time.return_value = current_time
        
        self.lockfile.write_text("garbage")
        old_mtime = current_time - 4000
        os.utime(self.lockfile, (old_mtime, old_mtime))

        original_open = os.open
        def side_effect_open(path, flags, *args):
            if str(path) == str(self.lockfile) and (flags & os.O_EXCL):
                raise FileExistsError
            return original_open(path, flags, *args)

        with patch("os.open", side_effect=side_effect_open):
            with patch.object(locking.LOG, "error") as mock_log:
                with self.assertRaises(SystemExit) as cm:
                    locking.create_pid_lock(self.lockfile, stale_seconds=3600)
                self.assertEqual(cm.exception.code, 3)
                mock_log.assert_called_with(
                    "Failed to acquire lockfile after cleanup. Exiting."
                )

    @patch("time.time")
    def test_unreadable_recent(self, mock_time):
        current_time = 10000.0
        mock_time.return_value = current_time
        
        self.lockfile.write_text("garbage")
        old_mtime = current_time - 1000
        os.utime(self.lockfile, (old_mtime, old_mtime))

        with self.assertRaises(SystemExit) as cm:
            locking.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertEqual(cm.exception.code, 3)

    @patch.object(Path, "mkdir", side_effect=OSError("mkdir fail"))
    def test_lockfile_parent_mkdir_fail(self, mock_mkdir):
        with self.assertRaises(OSError):
            locking.create_pid_lock(self.lockfile)

    def test_lockfile_read_fail(self):
        self.lockfile.touch()

        with patch.object(Path, "read_text", side_effect=OSError("read fail")):
            with patch.object(Path, "mkdir"):
                with patch("time.time", return_value=10000.0):
                    with patch("pathlib.Path.stat") as mock_stat:
                        mock_stat.return_value.st_mtime = 9000.0
                        
                        with self.assertRaises(SystemExit) as cm:
                            locking.create_pid_lock(self.lockfile)
                        self.assertEqual(cm.exception.code, 3)

    def test_is_process_alive(self):
        with patch("os.kill") as mock_kill:
            mock_kill.return_value = None
            self.assertTrue(locking._is_process_alive(123))

            mock_kill.side_effect = ProcessLookupError
            self.assertFalse(locking._is_process_alive(123))

            mock_kill.side_effect = PermissionError
            self.assertTrue(locking._is_process_alive(123))

            mock_kill.side_effect = OSError
            self.assertTrue(locking._is_process_alive(123))

    @patch("projectrestore.modules.locking._is_process_alive")
    @patch("time.time")
    def test_stale_lock_race_condition(self, mock_time, mock_alive):
        mock_alive.return_value = False
        current_time = 10000.0
        mock_time.return_value = current_time
        
        self.lockfile.write_text("12345")
        old_mtime = current_time - 4000
        os.utime(self.lockfile, (old_mtime, old_mtime))

        original_open = os.open
        def side_effect_open(path, flags, *args):
            if str(path) == str(self.lockfile) and (flags & os.O_EXCL):
                raise FileExistsError
            return original_open(path, flags, *args)

        with patch("os.open", side_effect=side_effect_open):
            with patch("pathlib.Path.unlink", side_effect=lambda: None):
                with self.assertRaises(SystemExit) as cm:
                    locking.create_pid_lock(self.lockfile, stale_seconds=3600)
                self.assertEqual(cm.exception.code, 3)
