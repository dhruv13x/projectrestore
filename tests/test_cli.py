#!/usr/bin/env python3
"""
test_projectrestore.cli.py - Unit and integration tests for projectrestore.cli.py

Run with: python -m unittest discover . (or pytest if available, but using stdlib unittest)

Requires: The projectrestore.cli.py script in the same directory.
Tests focus on core functions; file-system heavy tests use temp dirs.
Mocking used for PID/signal parts to avoid flakiness.
"""

import io
import os
import shutil
import sys
import tempfile
import time
import stat
from pathlib import Path
import unittest
from unittest import mock
from unittest.mock import patch, MagicMock, call

import projectrestore
from projectrestore import cli

# Add the script dir to path for import
#sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
#import projectrestore # noqa: E402

# Suppress logging during tests
# projectrestore.setup_logging(projectrestore.cli.logging.ERROR)


class TestSanitizeMemberName(unittest.TestCase):
    def test_safe_paths(self):
        safe_cases = [
            ("foo/bar.txt", "foo/bar.txt"),
            ("./foo", "foo"),
            ("dir/../safe", "safe"),  # normpath collapses but doesn't start with ..
            ("dir/", "dir"),
            (".", ""),  # . -> ""
        ]
        for input_name, expected in safe_cases:
            with self.subTest(input_name=input_name):
                result = projectrestore.cli._sanitize_member_name(input_name)
                self.assertEqual(result, expected)

    def test_unsafe_paths(self):
        unsafe_cases = [
            ("../traversal", None),
            ("..", None),
            ("../../etc/passwd", None),
        ]
        for input_name, _ in unsafe_cases:
            with self.subTest(input_name=input_name):
                result = projectrestore.cli._sanitize_member_name(input_name)
                self.assertIsNone(result)

    def test_absolute_paths(self):
        abs_cases = [
            ("/absolute", "absolute"),  # Current impl strips but doesn't reject
            ("/../foo", None),
            ("", None),  # empty -> None
        ]
        for input_name, expected in abs_cases:
            with self.subTest(input_name=input_name):
                result = projectrestore.cli._sanitize_member_name(input_name)
                self.assertEqual(result, expected)


class TestMemberTypeChecks(unittest.TestCase):
    def setUp(self):
        self.member = projectrestore.cli.tarfile.TarInfo("test")

    def test_symlink_hardlink(self):
        self.member.type = projectrestore.cli.tarfile.SYMTYPE
        self.assertTrue(projectrestore.cli._member_is_symlink_or_hardlink(self.member))
        self.member.type = projectrestore.cli.tarfile.LNKTYPE
        self.assertTrue(projectrestore.cli._member_is_symlink_or_hardlink(self.member))
        self.member.linkname = "foo"  # issym/islnk
        self.assertTrue(projectrestore.cli._member_is_symlink_or_hardlink(self.member))

    def test_not_link(self):
        self.member.type = projectrestore.cli.tarfile.REGTYPE
        self.assertFalse(projectrestore.cli._member_is_symlink_or_hardlink(self.member))

    def test_special_device(self):
        self.member.type = projectrestore.cli.tarfile.CHRTYPE
        self.assertTrue(projectrestore.cli._member_is_special_device(self.member))
        self.member.type = projectrestore.cli.tarfile.BLKTYPE
        self.assertTrue(projectrestore.cli._member_is_special_device(self.member))
        self.member.type = projectrestore.cli.tarfile.FIFOTYPE
        self.assertTrue(projectrestore.cli._member_is_special_device(self.member))

    def test_not_special(self):
        self.member.type = projectrestore.cli.tarfile.REGTYPE
        self.assertFalse(projectrestore.cli._member_is_special_device(self.member))


class TestWriteFileobjToPath(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.dest = self.temp_dir / "testfile.txt"
        self.fileobj = io.BytesIO(b"test content")
        self.mode = 0o644
        self.mtime = int(time.time())

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_write_and_rename(self):
        projectrestore.cli._write_fileobj_to_path(self.fileobj, self.dest, self.mode, self.mtime)

        self.assertTrue(self.dest.exists())
        self.assertEqual(self.dest.read_text(), "test content")
        stat_info = self.dest.stat()
        self.assertEqual(stat_info.st_mode & 0o777, 0o644)  # safe mode
        # mtime approximate check (utime sets atime too, but close enough)
        self.assertAlmostEqual(stat_info.st_mtime, self.mtime, delta=1)

    def test_zero_mode_default(self):
        projectrestore.cli._write_fileobj_to_path(self.fileobj, self.dest, 0, None)
        stat_info = self.dest.stat()
        self.assertEqual(stat_info.st_mode & 0o777, 0o644)

    @patch('os.chmod')
    def test_chmod_fail(self, mock_chmod):
        mock_chmod.side_effect = OSError("chmod fail")
        projectrestore.cli._write_fileobj_to_path(self.fileobj, self.dest, self.mode, None)
        mock_chmod.assert_called_once()
        self.assertTrue(self.dest.exists())  # still written

    @patch('os.utime')
    def test_utime_fail(self, mock_utime):
        mock_utime.side_effect = OSError("utime fail")
        projectrestore.cli._write_fileobj_to_path(self.fileobj, self.dest, self.mode, self.mtime)
        mock_utime.assert_called_once()
        self.assertTrue(self.dest.exists())

    @patch.object(Path, 'mkdir')
    def test_parent_mkdir_fail(self, mock_mkdir):
        mock_mkdir.side_effect = OSError("mkdir fail")
        with self.assertRaises(OSError) as cm:
            projectrestore.cli._write_fileobj_to_path(self.fileobj, self.dest, self.mode, None)
        self.assertEqual(str(cm.exception), "mkdir fail")


class TestRemoveDangerousBits(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_file = self.temp_dir / "testfile"
        self.test_file.write_text("content")
        # Set dangerous bits
        os.chmod(self.test_file, stat.S_IMODE(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_ISUID | stat.S_ISGID))

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_remove_bits(self):
        projectrestore.cli._remove_dangerous_bits(self.test_file)
        mode = self.test_file.stat().st_mode
        self.assertEqual(mode & (stat.S_ISUID | stat.S_ISGID), 0)

    @patch('pathlib.Path.stat', side_effect=OSError("stat fail"))
    def test_stat_fail(self, mock_stat):
        path = Path(tempfile.mktemp())
        with patch.object(projectrestore.cli.LOG, 'debug') as mock_log:
            projectrestore.cli._remove_dangerous_bits(path)
        mock_log.assert_called_once_with("Failed to sanitize mode for %s (non-fatal)", path)


class TestSafeExtractAtomic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.tar_path = self.temp_dir / "test.tar.gz"
        self.dest_dir = self.temp_dir / "extract_here"
        self.mtime = int(time.time())
        self._create_sample_tar()

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def _create_sample_tar(self, extra_members=None):
        """Create a simple tar.gz with a dir and file."""
        extra_members = extra_members or []
        tar_buffer = io.BytesIO()
        with projectrestore.cli.tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            # Dir
            dir_info = projectrestore.cli.tarfile.TarInfo("mydir/")
            dir_info.type = projectrestore.cli.tarfile.DIRTYPE
            dir_info.mode = 0o755
            dir_info.mtime = self.mtime
            tar.addfile(dir_info)

            # File
            content = b"Hello, safe extract!"
            file_info = projectrestore.cli.tarfile.TarInfo("mydir/file.txt")
            file_info.size = len(content)
            file_info.mode = 0o644
            file_info.mtime = self.mtime
            file_info.type = projectrestore.cli.tarfile.REGTYPE
            tar.addfile(file_info, io.BytesIO(content))

            # Extra members
            for member_info, member_content in extra_members:
                fobj = io.BytesIO(member_content) if member_content is not None else None
                tar.addfile(member_info, fobj)

        with open(self.tar_path, "wb") as f:
            f.write(tar_buffer.getvalue())

    def test_basic_extract(self):
        projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir, dry_run=False)

        extracted_dir = self.dest_dir / "mydir"
        self.assertTrue(extracted_dir.exists())
        self.assertTrue((extracted_dir / "file.txt").exists())
        self.assertEqual((extracted_dir / "file.txt").read_bytes(), b"Hello, safe extract!")
        # No dangerous bits
        file_stat = (extracted_dir / "file.txt").stat()
        self.assertEqual(file_stat.st_mode & (projectrestore.cli.stat.S_ISUID | projectrestore.cli.stat.S_ISGID), 0)

    def test_dry_run(self):
        with patch.object(projectrestore.cli.LOG, 'info') as mock_log:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir, dry_run=True)

        self.assertFalse(self.dest_dir.exists())  # No extraction
        mock_log.assert_called_with("Dry-run: validating archive %s", self.tar_path)

    def test_dry_run_cleanup_fail(self):
        fail_count = [0]
        def rmtree_side_effect(path):
            fail_count[0] += 1
            if fail_count[0] == 1:
                raise OSError("rmtree fail")
            return shutil.rmtree(path)

        with patch('shutil.rmtree', side_effect=rmtree_side_effect), \
             patch.object(projectrestore.cli.LOG, 'debug') as mock_log:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir, dry_run=True)

        self.assertFalse(self.dest_dir.exists())  # No extraction
        mock_log.assert_any_call("Failed to cleanup dry-run tempdir %s", mock.ANY)
        mock_log.assert_any_call("Failed to cleanup tmpdir %s", mock.ANY)

    def test_nonexistent_archive(self):
        bad_tar = self.tar_path.with_name("bad.tar.gz")
        with self.assertRaises(FileNotFoundError) as cm:
            projectrestore.cli.safe_extract_atomic(bad_tar, self.dest_dir)
        self.assertIn("Archive not found", str(cm.exception))

    @patch('projectrestore.cli.time.time', return_value=1234567890)
    @patch('projectrestore.cli.os.getpid', return_value=999)
    def test_temp_dir_exists(self, mock_getpid, mock_time):
        ts = 1234567890
        new_dir = self.dest_dir.parent / f"{self.dest_dir.name}.new_999_{ts}"
        new_dir.mkdir(mode=0o700)

        with self.assertRaises(RuntimeError) as cm:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Temp extraction dir unexpectedly exists", str(cm.exception))
        self.assertIn(str(new_dir), str(cm.exception))

    def test_max_files_limit(self):
        # Tar with 2 files
        extra_info = projectrestore.cli.tarfile.TarInfo("extra.txt")
        extra_content = b"extra"
        extra_info.size = len(extra_content)
        extra_info.mode = 0o644
        extra_info.mtime = self.mtime
        extra_info.type = projectrestore.cli.tarfile.REGTYPE
        self._create_sample_tar(extra_members=[(extra_info, extra_content)])

        with self.assertRaises(RuntimeError) as cm:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir, max_files=1)
        self.assertEqual(str(cm.exception), "Archive exceeds max-files limit")

    def test_max_bytes_limit(self):
        large_content = b"A" * 1025  # >1024, hello ~20
        extra_info = projectrestore.cli.tarfile.TarInfo("large.txt")
        extra_info.size = len(large_content)
        extra_info.mode = 0o644
        extra_info.mtime = self.mtime
        extra_info.type = projectrestore.cli.tarfile.REGTYPE
        self._create_sample_tar(extra_members=[(extra_info, large_content)])

        with self.assertRaises(RuntimeError) as cm:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir, max_bytes=1024)
        self.assertEqual(str(cm.exception), "Archive exceeds max-bytes limit")

    def test_reject_unsafe_path(self):
        # Current impl doesn't reject stripped absolute, so test traversal instead
        traversal_info = projectrestore.cli.tarfile.TarInfo("../etc/passwd")
        traversal_content = b"malicious"
        traversal_info.size = len(traversal_content)
        traversal_info.mode = 0o644
        traversal_info.mtime = self.mtime
        traversal_info.type = projectrestore.cli.tarfile.REGTYPE
        self._create_sample_tar(extra_members=[(traversal_info, traversal_content)])

        with self.assertRaises(RuntimeError) as cm:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Tar member has unsafe path", str(cm.exception))

    def test_reject_symlink(self):
        link_member = projectrestore.cli.tarfile.TarInfo("symlink")
        link_member.type = projectrestore.cli.tarfile.SYMTYPE
        link_member.linkname = "/etc/passwd"
        link_member.size = 0
        self._create_sample_tar(extra_members=[(link_member, None)])

        with self.assertRaises(RuntimeError) as cm:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Tar contains symlink/hardlink member", str(cm.exception))

    def test_reject_special_device(self):
        dev_member = projectrestore.cli.tarfile.TarInfo("device")
        dev_member.type = projectrestore.cli.tarfile.CHRTYPE
        dev_member.size = 0
        self._create_sample_tar(extra_members=[(dev_member, None)])

        with self.assertRaises(RuntimeError) as cm:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Tar contains special device/fifo member", str(cm.exception))

    def test_reject_sparse(self):
        sparse_member = projectrestore.cli.tarfile.TarInfo("sparse")
        sparse_member.type = projectrestore.cli.tarfile.GNUTYPE_SPARSE
        sparse_member.size = 0
        self._create_sample_tar(extra_members=[(sparse_member, None)])

        with self.assertRaises(RuntimeError) as cm:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Rejecting sparse/gnu-special member", str(cm.exception))

    @patch('projectrestore.cli.tarfile.open')
    def test_allow_sparse(self, mock_open):
        mock_tf = MagicMock()
        sparse_member = MagicMock()
        sparse_member.name = "sparse"
        sparse_member.type = projectrestore.cli.tarfile.GNUTYPE_SPARSE
        sparse_member.isdir.return_value = False
        sparse_member.isreg.return_value = False
        sparse_member.issym.return_value = False
        sparse_member.islnk.return_value = False
        sparse_member.size = 0
        mock_tf.__iter__.return_value = iter([sparse_member])
        mock_open.return_value.__enter__.return_value = mock_tf

        with self.assertRaises(RuntimeError) as cm:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir, reject_sparse=False)
        self.assertIn("Unsupported or disallowed tar member type", str(cm.exception))

    def test_skip_pax_headers(self):
        pax_member = projectrestore.cli.tarfile.TarInfo("paxheader")
        pax_member.type = projectrestore.cli.tarfile.XHDTYPE
        pax_member.size = 7
        pax_member.name = "./paxheader"
        self._create_sample_tar(extra_members=[(pax_member, b"path=foo")])

        # No exception, skips (not yielded by tarfile)
        projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertTrue((self.dest_dir / "mydir" / "file.txt").exists())

    def test_unknown_member_type(self):
        unknown_member = projectrestore.cli.tarfile.TarInfo("unknown")
        unknown_member.type = b'?'
        unknown_member.size = 0
        self._create_sample_tar(extra_members=[(unknown_member, None)])

        with self.assertRaises(RuntimeError) as cm:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Unsupported or disallowed tar member type", str(cm.exception))

    @patch('shutil.rmtree')
    def test_atomic_swap_with_existing_dir(self, mock_rmtree):
        # Pre-create dest_dir with a file
        self.dest_dir.mkdir()
        (self.dest_dir / "existing.txt").write_text("old")

        projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)

        # Old should be backed up
        old_backup = None
        for p in self.dest_dir.parent.iterdir():
            if p.name.startswith(self.dest_dir.name + ".old_"):
                old_backup = p
                break
        self.assertIsNotNone(old_backup)
        self.assertTrue((old_backup / "existing.txt").exists())

        # New content in place
        self.assertTrue((self.dest_dir / "mydir" / "file.txt").exists())

        # rmtree called on backup
        mock_rmtree.assert_called_once()

    @patch('projectrestore.cli.time.time', return_value=1234567890)
    def test_atomic_swap_rollback(self, mock_time):
        original_replace = Path.replace

        def replace_side_effect(src, dst):
            if src == self.dest_dir:
                return original_replace(src, dst)
            elif src.name.startswith(f"{self.dest_dir.name}.new_"):
                raise OSError("swap fail")
            else:
                return original_replace(src, dst)

        with patch('pathlib.Path.replace', side_effect=replace_side_effect):
            # Pre-create dest_dir
            self.dest_dir.mkdir()
            (self.dest_dir / "existing.txt").write_text("old")

            with self.assertRaises(OSError) as cm:
                projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
            self.assertIn("swap fail", str(cm.exception))

            # Rollback: dest_dir restored
            self.assertTrue((self.dest_dir / "existing.txt").exists())

    @patch('projectrestore.cli.time.time', return_value=1234567890)
    @patch('projectrestore.cli.LOG')
    def test_rollback_fail(self, mock_log, mock_time):
        original_replace = Path.replace

        ts = 1234567890
        pid = os.getpid()
        backup_dir = self.dest_dir.parent / f"{self.dest_dir.name}.old_{pid}_{ts}"

        def replace_side_effect(src, dst):
            if src == self.dest_dir:
                return original_replace(src, dst)
            elif src.name.startswith(f"{self.dest_dir.name}.new_"):
                raise OSError("swap fail")
            else:
                raise OSError("rollback fail")

        with patch('pathlib.Path.replace', side_effect=replace_side_effect):
            # Pre-create dest_dir
            self.dest_dir.mkdir()
            (self.dest_dir / "existing.txt").write_text("old")

            with self.assertRaises(OSError) as cm:
                projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
            self.assertIn("swap fail", str(cm.exception))
            mock_log.exception.assert_called_once_with("Failed during swap/rename: %s", mock.ANY)
            mock_log.error.assert_called_once_with("Rollback failed; manual intervention required. Backup left at %s", backup_dir)

    @patch('shutil.rmtree', side_effect=OSError("rmtree fail"))
    def test_backup_rmtree_fail(self, mock_rmtree):
        self.dest_dir.mkdir()
        with patch('projectrestore.cli.LOG.warning') as mock_log:
            projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        mock_rmtree.assert_called_once()
        mock_log.assert_called_with("Failed to remove backup directory %s (non-fatal)", mock.ANY)

    def test_touch_for_none_fileobj(self):
        # Create tar with reg size=0
        zero_file_info = projectrestore.cli.tarfile.TarInfo("zero.txt")
        zero_file_info.size = 0
        zero_file_info.mode = 0o644
        zero_file_info.mtime = self.mtime
        zero_file_info.type = projectrestore.cli.tarfile.REGTYPE
        self._create_sample_tar(extra_members=[(zero_file_info, None)])

        projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        zero_file = self.dest_dir / "zero.txt"
        self.assertTrue(zero_file.exists())
        self.assertEqual(zero_file.read_bytes(), b"")

    @patch.object(projectrestore.cli.tarfile.TarFile, 'extractfile', return_value=None)
    def test_touch_for_none_extractfile(self, mock_extractfile):
        # Force f=None for reg member
        projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir)
        mock_extractfile.assert_called()
        self.assertTrue((self.dest_dir / "mydir" / "file.txt").exists())

    # To cover allow_pax skip branch (not naturally hit)
    @patch('projectrestore.cli.tarfile.open')
    @patch.object(projectrestore.cli, 'LOG')
    def test_skip_pax_with_mock(self, mock_log, mock_open):
        mock_tf = MagicMock()
        pax_member = MagicMock()
        pax_member.name = "pax"
        pax_member.type = projectrestore.cli.tarfile.XHDTYPE
        reg_member = MagicMock()
        reg_member.name = "file.txt"
        reg_member.isdir.return_value = False
        reg_member.isreg.return_value = True
        reg_member.issym.return_value = False
        reg_member.islnk.return_value = False
        reg_member.type = projectrestore.cli.tarfile.REGTYPE
        reg_member.size = 10
        mock_tf.extractfile.return_value = io.BytesIO(b"")
        mock_tf.__iter__.return_value = iter([pax_member, reg_member])
        mock_open.return_value.__enter__.return_value = mock_tf

        projectrestore.cli.safe_extract_atomic(self.tar_path, self.dest_dir, allow_pax=True, dry_run=True)

        mock_log.debug.assert_called_once_with("Skipping pax/global header member: %s (type=%s)", "pax", projectrestore.cli.tarfile.XHDTYPE)


class TestChecksum(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_file = self.temp_dir / "test.bin"
        self.test_file.write_bytes(b"checksum test")

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_compute_sha256(self):
        actual = projectrestore.cli.compute_sha256(self.test_file)
        self.assertEqual(actual, "50743bc89b03b938f412094255c8e3cf1658b470dbc01d7db80a11dc39adfb9a")

    def test_verify_match(self):
        sum_file = self.temp_dir / "checksum.txt"
        sum_file.write_text("50743bc89b03b938f412094255c8e3cf1658b470dbc01d7db80a11dc39adfb9a  test.bin")

        self.assertTrue(projectrestore.cli.verify_sha256_from_file(self.test_file, sum_file))

    def test_verify_mismatch(self):
        sum_file = self.temp_dir / "checksum.txt"
        sum_file.write_text("deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef")

        self.assertFalse(projectrestore.cli.verify_sha256_from_file(self.test_file, sum_file))

    def test_empty_checksum_file(self):
        sum_file = self.temp_dir / "checksum.txt"
        sum_file.touch()

        self.assertFalse(projectrestore.cli.verify_sha256_from_file(self.test_file, sum_file))

    def test_checksum_read_exception(self):
        with patch('builtins.open', side_effect=OSError("read fail")):
            self.assertFalse(projectrestore.cli.verify_sha256_from_file(self.test_file, self.temp_dir / "missing.txt"))


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

        latest = projectrestore.cli.find_latest_backup(self.backup_dir, self.pattern)
        self.assertEqual(latest, file2)

    def test_no_match(self):
        latest = projectrestore.cli.find_latest_backup(self.backup_dir, self.pattern)
        self.assertIsNone(latest)

    def test_non_dir(self):
        non_dir = Path(tempfile.mktemp())
        with patch('projectrestore.cli.Path') as mock_path:
            mock_instance = mock_path.return_value
            mock_instance.exists.return_value = False
            latest = projectrestore.cli.find_latest_backup(non_dir, self.pattern)
            self.assertIsNone(latest)


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
        projectrestore.cli.create_pid_lock(self.lockfile)
        self.assertTrue(self.lockfile.exists())
        content = self.lockfile.read_text().strip()
        self.assertEqual(content, str(os.getpid()))

        projectrestore.cli.release_pid_lock(self.lockfile)
        self.assertFalse(self.lockfile.exists())

    @patch('projectrestore.cli._is_process_alive')
    @patch('os.stat')
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

        projectrestore.cli.create_pid_lock(self.lockfile, stale_seconds=3600)
        # Should acquire after removing stale
        self.assertTrue(self.lockfile.exists())
        self.assertEqual(self.lockfile.read_text().strip(), str(os.getpid()))

    @patch('projectrestore.cli._is_process_alive')
    def test_running_instance(self, mock_alive):
        mock_alive.return_value = True
        self.lockfile.write_text("99999")  # Assume alive

        with self.assertRaises(SystemExit) as cm:
            projectrestore.cli.create_pid_lock(self.lockfile)
        self.assertEqual(cm.exception.code, 3)

    def test_release_not_owned(self):
        self.lockfile.write_text("99999")
        projectrestore.cli.release_pid_lock(self.lockfile)
        self.assertTrue(self.lockfile.exists())  # Left alone

    @patch('projectrestore.cli._is_process_alive')
    @patch('os.stat')
    @patch('os.unlink', side_effect=OSError("unlink fail"))
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
            projectrestore.cli.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertEqual(cm.exception.code, 3)
        mock_unlink.assert_called_once()

    @patch('projectrestore.cli._is_process_alive')
    @patch('os.stat')
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
            projectrestore.cli.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertEqual(cm.exception.code, 3)

    @patch('os.stat')
    @patch('os.unlink', return_value=None)
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

        with patch.object(projectrestore.cli.LOG, 'error') as mock_log:
            with self.assertRaises(SystemExit) as cm:
                projectrestore.cli.create_pid_lock(self.lockfile, stale_seconds=3600)
            self.assertEqual(cm.exception.code, 3)
            mock_log.assert_called_with("Failed to acquire lockfile after cleanup. Exiting.")

    @patch('os.stat')
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
            projectrestore.cli.create_pid_lock(self.lockfile, stale_seconds=3600)
        self.assertEqual(cm.exception.code, 3)

    @patch.object(projectrestore.cli.Path, 'mkdir', side_effect=OSError("mkdir fail"))
    def test_lockfile_parent_mkdir_fail(self, mock_mkdir):
        with self.assertRaises(OSError):
            projectrestore.cli.create_pid_lock(self.lockfile)

    @patch('projectrestore.cli._is_process_alive')
    @patch('os.stat')
    @patch.object(projectrestore.cli.LOG, 'warning')
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

        projectrestore.cli.create_pid_lock(self.lockfile, stale_seconds=stale_seconds)
        self.assertTrue(self.lockfile.exists())
        self.assertEqual(self.lockfile.read_text().strip(), str(os.getpid()))
        mock_log.assert_called_once_with("Removed stale lockfile (pid %s, age %ds). Retrying.", 12345, stale_seconds + 1)

    @patch('pathlib.Path.read_text', side_effect=OSError("read fail"))
    def test_lockfile_read_fail(self, mock_read):
        self.lockfile.touch()
        with self.assertRaises(SystemExit) as cm:
            projectrestore.cli.create_pid_lock(self.lockfile)
        self.assertEqual(cm.exception.code, 3)


class TestGracefulShutdown(unittest.TestCase):
    def setUp(self):
        self.shutdown = projectrestore.cli.GracefulShutdown()
        self.mock_cb = MagicMock()

    @patch('projectrestore.cli.LOG')
    def test_handler(self, mock_log):
        self.shutdown.register(self.mock_cb)
        handler = self.shutdown._handler

        # Simulate signal
        with self.assertRaises(SystemExit):
            handler(15, None)  # SIGTERM

        self.mock_cb.assert_called_once()
        mock_log.info.assert_called()

    def test_install(self):
        self.shutdown.install()
        # Check signals are set (but mock for safety)
        with patch.object(self.shutdown, '_handler'):
            pass  # Just test no exception

    @patch('signal.signal')
    def test_install_fail(self, mock_signal):
        mock_signal.side_effect = OSError("signal fail")
        shutdown = projectrestore.cli.GracefulShutdown()
        shutdown.install()  # Should not crash


class TestCountFiles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        (self.temp_dir / "file1.txt").touch()
        (self.temp_dir / "dir").mkdir()
        (self.temp_dir / "dir" / "file2.txt").touch()  # only files counted

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_count(self):
        count = projectrestore.cli.count_files(self.temp_dir)
        self.assertEqual(count, 2)


class TestCLIIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.backup_dir = self.temp_dir / "backups"
        self.backup_dir.mkdir()
        self.tar_path = self.backup_dir / "test-bot_platform-2023.tar.gz"
        self.tar_path.touch()  # Mock backup

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @patch('projectrestore.cli.safe_extract_atomic')
    @patch('projectrestore.cli.find_latest_backup')
    @patch('projectrestore.cli.count_files')
    def test_main_success(self, mock_count, mock_find, mock_extract):
        mock_find.return_value = self.tar_path
        mock_count.return_value = 1

        with patch('projectrestore.cli.sys.argv', ['script.py', '--backup-dir', str(self.backup_dir)]):
            rc = projectrestore.cli.main()

        self.assertEqual(rc, 0)
        mock_extract.assert_called_once()
        mock_count.assert_called_once_with(mock.ANY)

    @patch('projectrestore.cli.safe_extract_atomic')
    @patch('projectrestore.cli.find_latest_backup')
    def test_main_dry_run_success(self, mock_find, mock_extract):
        mock_find.return_value = self.tar_path

        with patch('projectrestore.cli.sys.argv', ['script.py', '--backup-dir', str(self.backup_dir), '--dry-run']):
            rc = projectrestore.cli.main()

        self.assertEqual(rc, 0)
        mock_extract.assert_called_once_with(
            self.tar_path,
            self.backup_dir / "tmp_extract",
            max_files=None,
            max_bytes=None,
            allow_pax=False,
            reject_sparse=True,
            dry_run=True
        )

    def test_main_no_backup_dir(self):
        with patch('projectrestore.cli.sys.argv', ['script.py', '--backup-dir', '/nonexistent']):
            rc = projectrestore.cli.main()
        self.assertEqual(rc, 1)

    @patch('projectrestore.cli.find_latest_backup')
    def test_main_no_backup_file(self, mock_find):
        mock_find.return_value = None
        with patch('projectrestore.cli.sys.argv', ['script.py', '--backup-dir', str(self.backup_dir)]):
            rc = projectrestore.cli.main()
        self.assertEqual(rc, 1)
        mock_find.assert_called_once()

    @patch('projectrestore.cli.find_latest_backup')
    @patch('projectrestore.cli.verify_sha256_from_file', return_value=False)
    def test_main_checksum_fail(self, mock_verify, mock_find):
        mock_find.return_value = self.tar_path
        with patch('projectrestore.cli.sys.argv', ['script.py', '--backup-dir', str(self.backup_dir), '--checksum', 'check.txt']):
            rc = projectrestore.cli.main()
        self.assertEqual(rc, 1)
        mock_verify.assert_called_once()

    @patch.object(projectrestore.cli.Path, 'mkdir', side_effect=OSError("mkdir fail"))
    def test_main_extract_dir_parent_fail(self, mock_mkdir):
        bad_extract = Path("/root/nonexistent/extract")
        with patch('projectrestore.cli.sys.argv', ['script.py', '--backup-dir', str(self.backup_dir), '--extract-dir', str(bad_extract)]):
            rc = projectrestore.cli.main()
        self.assertEqual(rc, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)