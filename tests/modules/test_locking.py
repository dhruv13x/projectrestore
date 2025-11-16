# tests/modules/test_locking.py

import os
import stat
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil
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
    @patch("os.stat")
    def test_stale_lock(self, mock_stat, mock_alive):
        mock_alive.return_value = False
        # Create stale lock
        stale_pid = 12345
        self.lockfile.write_text(str(stale_pid))
        old_mtime = time.time() - 4000  # >3600 stale

        dir_mock = MagicMock(st_mtime=time.time(), st_mode=stat.S_IFDIR | 0o755)
        file_mock = MagicMock(st_mtime=old_mtime, st_mode=stat.S_IFREG | 0o644)

        def stat_side_effect(*args, **kwargs):
            path = args[0]
            path_str = str(path)
            if str(self.lockfile) in path_str:
                return file_mock
            else:
                return dir_mock

        mock_stat.side_effect = stat_side_effect

        locking.create_pid_lock(self.lockfile, stale_seconds=3600)
        # Should acquire after removing stale
        self.assertTrue(self.lockfile.exists())
        self.assertEqual(self.lockfile.read_text().strip(), str(os.getpid()))

    @patch("projectrestore.modules.locking._is_process_alive")
    def test_running_instance(self, mock_alive):
        mock_alive.return_value = True
        self.lockfile.write_text("99999")  # Assume alive

        with self.assertRaises(SystemExit) as cm:
            locking.create_pid_lock(self.lockfile)
        self.assertEqual(cm.exception.code, 3)

    def test_release_not_owned(self):
        self.lockfile.write_text("99999")
        locking.release_pid_lock(self.lockfile)
        self.assertTrue(self.lockfile.exists())  # Left alone

    @patch("projectrestore.modules.locking._is_process_alive")
    @patch("os.stat")
    @patch("os.unlink", side_effect=OSError("unlink fail"))
    def test_stale_remove_fail(self, mock_unlink, mock_stat, mock_alive):
        mock_alive.return_value = False
        self.lockfile.write_text("12345")
        old_mtime = time.time() - 4000

        dir_mock = MagicMock(st_mtime=time.time(), st_mode=stat.S_IFDIR | 0o755)
        file_mock = MagicMock(st_mtime=old_mtime, st_mode=stat.S_IFREG | 0o644)

        def stat_side_effect(*args, **kwargs):
            path = args[0]
            path_str = str(path)
            if str(self.lockfile) in path_str:
                return file_mock
            else:
                return dir_mock

        mock_stat.side_effect = stat_side_effect

        with self.assertRaises(SystemExit) as cm:
            locking.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertEqual(cm.exception.code, 3)
        mock_unlink.assert_called_once()

    @patch("projectrestore.modules.locking._is_process_alive")
    @patch("os.stat")
    def test_stale_not_old_enough(self, mock_stat, mock_alive):
        mock_alive.return_value = False
        self.lockfile.write_text("12345")
        old_mtime = time.time() - 3000  # <3600

        dir_mock = MagicMock(st_mtime=time.time(), st_mode=stat.S_IFDIR | 0o755)
        file_mock = MagicMock(st_mtime=old_mtime, st_mode=stat.S_IFREG | 0o644)

        def stat_side_effect(*args, **kwargs):
            path = args[0]
            path_str = str(path)
            if str(self.lockfile) in path_str:
                return file_mock
            else:
                return dir_mock

        mock_stat.side_effect = stat_side_effect

        with self.assertRaises(SystemExit) as cm:
            locking.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertEqual(cm.exception.code, 3)

    @patch("os.stat")
    @patch("os.unlink", return_value=None)
    def test_unreadable_stale_remove(self, mock_unlink, mock_stat):
        self.lockfile.write_text("garbage")
        old_mtime = time.time() - 4000

        dir_mock = MagicMock(st_mtime=time.time(), st_mode=stat.S_IFDIR | 0o755)
        file_mock = MagicMock(st_mtime=old_mtime, st_mode=stat.S_IFREG | 0o644)

        def stat_side_effect(*args, **kwargs):
            path = args[0]
            path_str = str(path)
            if str(self.lockfile) in path_str:
                return file_mock
            else:
                return dir_mock

        mock_stat.side_effect = stat_side_effect

        with patch.object(locking.LOG, "error") as mock_log:
            with self.assertRaises(SystemExit) as cm:
                locking.create_pid_lock(self.lockfile, stale_seconds=3600)
            self.assertEqual(cm.exception.code, 3)
            mock_log.assert_called_with(
                "Failed to acquire lockfile after cleanup. Exiting."
            )

    @patch("os.stat")
    def test_unreadable_recent(self, mock_stat):
        self.lockfile.write_text("garbage")
        old_mtime = time.time() - 1000  # recent

        dir_mock = MagicMock(st_mtime=time.time(), st_mode=stat.S_IFDIR | 0o755)
        file_mock = MagicMock(st_mtime=old_mtime, st_mode=stat.S_IFREG | 0o644)

        def stat_side_effect(*args, **kwargs):
            path = args[0]
            path_str = str(path)
            if str(self.lockfile) in path_str:
                return file_mock
            else:
                return dir_mock

        mock_stat.side_effect = stat_side_effect

        with self.assertRaises(SystemExit) as cm:
            locking.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertEqual(cm.exception.code, 3)

    @patch.object(Path, "mkdir", side_effect=OSError("mkdir fail"))
    def test_lockfile_parent_mkdir_fail(self, mock_mkdir):
        with self.assertRaises(OSError):
            locking.create_pid_lock(self.lockfile)

    @patch("projectrestore.modules.locking._is_process_alive")
    @patch("os.stat")
    @patch.object(locking.LOG, "warning")
    def test_stale_pid_stat_fail(self, mock_log, mock_stat, mock_alive):
        mock_alive.return_value = False
        self.lockfile.write_text("12345")
        stale_seconds = 3600

        raise_flag = [True]

        def stat_side_effect(*args, **kwargs):
            path = args[0]
            if str(path) == str(self.lockfile) and raise_flag[0]:
                raise_flag[0] = False
                raise OSError("stat fail")
            return MagicMock(st_mtime=time.time(), st_mode=stat.S_IFDIR | 0o755)

        mock_stat.side_effect = stat_side_effect

        locking.create_pid_lock(self.lockfile, stale_seconds=stale_seconds)
        self.assertTrue(self.lockfile.exists())
        self.assertEqual(self.lockfile.read_text().strip(), str(os.getpid()))
        mock_log.assert_called_once_with(
            "Removed stale lockfile (pid %s, age %ds). Retrying.",
            12345,
            stale_seconds + 1,
        )

    @patch("pathlib.Path.read_text", side_effect=OSError("read fail"))
    def test_lockfile_read_fail(self, mock_read):
        self.lockfile.touch()
        with self.assertRaises(SystemExit) as cm:
            locking.create_pid_lock(self.lockfile)
        self.assertEqual(cm.exception.code, 3)
