# tests/modules/test_extraction.py

import tarfile
import io
import os
import shutil
import tempfile
import time
import stat
from pathlib import Path
import unittest
from unittest import mock
from unittest.mock import patch, MagicMock
from projectrestore.modules import extraction


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
                result = extraction._sanitize_member_name(input_name)
                self.assertEqual(result, expected)

    def test_unsafe_paths(self):
        unsafe_cases = [
            ("../traversal", None),
            ("..", None),
            ("../../etc/passwd", None),
        ]
        for input_name, _ in unsafe_cases:
            with self.subTest(input_name=input_name):
                result = extraction._sanitize_member_name(input_name)
                self.assertIsNone(result)

    def test_absolute_paths(self):
        abs_cases = [
            ("/absolute", "absolute"),  # Current impl strips but doesn't reject
            ("/../foo", None),
            ("", None),  # empty -> None
        ]
        for input_name, expected in abs_cases:
            with self.subTest(input_name=input_name):
                result = extraction._sanitize_member_name(input_name)
                self.assertEqual(result, expected)


class TestMemberTypeChecks(unittest.TestCase):
    def setUp(self):
        self.member = tarfile.TarInfo("test")

    def test_symlink_hardlink(self):
        self.member.type = tarfile.SYMTYPE
        self.assertTrue(extraction._member_is_symlink_or_hardlink(self.member))
        self.member.type = tarfile.LNKTYPE
        self.assertTrue(extraction._member_is_symlink_or_hardlink(self.member))
        self.member.linkname = "foo"  # issym/islnk
        self.assertTrue(extraction._member_is_symlink_or_hardlink(self.member))

    def test_not_link(self):
        self.member.type = tarfile.REGTYPE
        self.assertFalse(extraction._member_is_symlink_or_hardlink(self.member))

    def test_special_device(self):
        self.member.type = tarfile.CHRTYPE
        self.assertTrue(extraction._member_is_special_device(self.member))
        self.member.type = tarfile.BLKTYPE
        self.assertTrue(extraction._member_is_special_device(self.member))
        self.member.type = tarfile.FIFOTYPE
        self.assertTrue(extraction._member_is_special_device(self.member))

    def test_not_special(self):
        self.member.type = tarfile.REGTYPE
        self.assertFalse(extraction._member_is_special_device(self.member))


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
        extraction._write_fileobj_to_path(
            self.fileobj, self.dest, self.mode, self.mtime
        )

        self.assertTrue(self.dest.exists())
        self.assertEqual(self.dest.read_text(), "test content")
        stat_info = self.dest.stat()
        self.assertEqual(stat_info.st_mode & 0o777, 0o644)  # safe mode
        # mtime approximate check (utime sets atime too, but close enough)
        self.assertAlmostEqual(stat_info.st_mtime, self.mtime, delta=1)

    def test_zero_mode_default(self):
        extraction._write_fileobj_to_path(self.fileobj, self.dest, 0, None)
        stat_info = self.dest.stat()
        self.assertEqual(stat_info.st_mode & 0o777, 0o644)

    @patch("os.chmod")
    def test_chmod_fail(self, mock_chmod):
        mock_chmod.side_effect = OSError("chmod fail")
        extraction._write_fileobj_to_path(self.fileobj, self.dest, self.mode, None)
        mock_chmod.assert_called_once()
        self.assertTrue(self.dest.exists())  # still written

    @patch("os.utime")
    def test_utime_fail(self, mock_utime):
        mock_utime.side_effect = OSError("utime fail")
        extraction._write_fileobj_to_path(
            self.fileobj, self.dest, self.mode, self.mtime
        )
        mock_utime.assert_called_once()
        self.assertTrue(self.dest.exists())

    @patch.object(Path, "mkdir")
    def test_parent_mkdir_fail(self, mock_mkdir):
        mock_mkdir.side_effect = OSError("mkdir fail")
        with self.assertRaises(OSError) as cm:
            extraction._write_fileobj_to_path(self.fileobj, self.dest, self.mode, None)
        self.assertEqual(str(cm.exception), "mkdir fail")


class TestRemoveDangerousBits(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_file = self.temp_dir / "testfile"
        self.test_file.write_text("content")
        # Set dangerous bits
        os.chmod(
            self.test_file,
            stat.S_IMODE(
                stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_ISUID | stat.S_ISGID
            ),
        )

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_remove_bits(self):
        extraction._remove_dangerous_bits(self.test_file)
        mode = self.test_file.stat().st_mode
        self.assertEqual(mode & (stat.S_ISUID | stat.S_ISGID), 0)

    @patch("pathlib.Path.stat", side_effect=OSError("stat fail"))
    def test_stat_fail(self, mock_stat):
        path = Path(tempfile.mktemp())
        with patch.object(extraction.LOG, "debug") as mock_log:
            extraction._remove_dangerous_bits(path)
        mock_log.assert_called_once_with(
            "Failed to sanitize mode for %s (non-fatal)", path
        )


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
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            # Dir
            dir_info = tarfile.TarInfo("mydir/")
            dir_info.type = tarfile.DIRTYPE
            dir_info.mode = 0o755
            dir_info.mtime = self.mtime
            tar.addfile(dir_info)

            # File
            content = b"Hello, safe extract!"
            file_info = tarfile.TarInfo("mydir/file.txt")
            file_info.size = len(content)
            file_info.mode = 0o644
            file_info.mtime = self.mtime
            file_info.type = tarfile.REGTYPE
            tar.addfile(file_info, io.BytesIO(content))

            # Extra members
            for member_info, member_content in extra_members:
                fobj = (
                    io.BytesIO(member_content) if member_content is not None else None
                )
                tar.addfile(member_info, fobj)

        with open(self.tar_path, "wb") as f:
            f.write(tar_buffer.getvalue())

    def test_basic_extract(self):
        extraction.safe_extract_atomic(self.tar_path, self.dest_dir, dry_run=False)

        extracted_dir = self.dest_dir / "mydir"
        self.assertTrue(extracted_dir.exists())
        self.assertTrue((extracted_dir / "file.txt").exists())
        self.assertEqual(
            (extracted_dir / "file.txt").read_bytes(), b"Hello, safe extract!"
        )
        # No dangerous bits
        file_stat = (extracted_dir / "file.txt").stat()
        self.assertEqual(file_stat.st_mode & (stat.S_ISUID | stat.S_ISGID), 0)

    def test_dry_run(self):
        with patch.object(extraction.LOG, "info") as mock_log:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir, dry_run=True)

        self.assertFalse(self.dest_dir.exists())  # No extraction
        mock_log.assert_called_with("Dry-run: validating archive %s", self.tar_path)

    def test_dry_run_cleanup_fail(self):
        fail_count = [0]

        def rmtree_side_effect(path):
            fail_count[0] += 1
            if fail_count[0] == 1:
                raise OSError("rmtree fail")
            return shutil.rmtree(path)

        with patch("shutil.rmtree", side_effect=rmtree_side_effect), patch.object(
            extraction.LOG, "debug"
        ) as mock_log:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir, dry_run=True)

        self.assertFalse(self.dest_dir.exists())  # No extraction
        mock_log.assert_any_call("Failed to cleanup dry-run tempdir %s", mock.ANY)
        mock_log.assert_any_call("Failed to cleanup tmpdir %s", mock.ANY)

    def test_nonexistent_archive(self):
        bad_tar = self.tar_path.with_name("bad.tar.gz")
        with self.assertRaises(FileNotFoundError) as cm:
            extraction.safe_extract_atomic(bad_tar, self.dest_dir)
        self.assertIn("Archive not found", str(cm.exception))

    @patch("time.time", return_value=1234567890)
    @patch("os.getpid", return_value=999)
    def test_temp_dir_exists(self, mock_getpid, mock_time):
        ts = 1234567890
        new_dir = self.dest_dir.parent / f"{self.dest_dir.name}.new_999_{ts}"
        new_dir.mkdir(mode=0o700)

        with self.assertRaises(RuntimeError) as cm:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Temp extraction dir unexpectedly exists", str(cm.exception))
        self.assertIn(str(new_dir), str(cm.exception))

    def test_max_files_limit(self):
        # Tar with 2 files
        extra_info = tarfile.TarInfo("extra.txt")
        extra_content = b"extra"
        extra_info.size = len(extra_content)
        extra_info.mode = 0o644
        extra_info.mtime = self.mtime
        extra_info.type = tarfile.REGTYPE
        self._create_sample_tar(extra_members=[(extra_info, extra_content)])

        with self.assertRaises(RuntimeError) as cm:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir, max_files=1)
        self.assertEqual(str(cm.exception), "Archive exceeds max-files limit")

    def test_max_bytes_limit(self):
        large_content = b"A" * 1025  # >1024, hello ~20
        extra_info = tarfile.TarInfo("large.txt")
        extra_info.size = len(large_content)
        extra_info.mode = 0o644
        extra_info.mtime = self.mtime
        extra_info.type = tarfile.REGTYPE
        self._create_sample_tar(extra_members=[(extra_info, large_content)])

        with self.assertRaises(RuntimeError) as cm:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir, max_bytes=1024)
        self.assertEqual(str(cm.exception), "Archive exceeds max-bytes limit")

    def test_reject_unsafe_path(self):
        # Current impl doesn't reject stripped absolute, so test traversal instead
        traversal_info = tarfile.TarInfo("../etc/passwd")
        traversal_content = b"malicious"
        traversal_info.size = len(traversal_content)
        traversal_info.mode = 0o644
        traversal_info.mtime = self.mtime
        traversal_info.type = tarfile.REGTYPE
        self._create_sample_tar(extra_members=[(traversal_info, traversal_content)])

        with self.assertRaises(RuntimeError) as cm:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Tar member has unsafe path", str(cm.exception))

    def test_reject_symlink(self):
        link_member = tarfile.TarInfo("symlink")
        link_member.type = tarfile.SYMTYPE
        link_member.linkname = "/etc/passwd"
        link_member.size = 0
        self._create_sample_tar(extra_members=[(link_member, None)])

        with self.assertRaises(RuntimeError) as cm:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Tar contains symlink/hardlink member", str(cm.exception))

    def test_reject_special_device(self):
        dev_member = tarfile.TarInfo("device")
        dev_member.type = tarfile.CHRTYPE
        dev_member.size = 0
        self._create_sample_tar(extra_members=[(dev_member, None)])

        with self.assertRaises(RuntimeError) as cm:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Tar contains special device/fifo member", str(cm.exception))

    def test_reject_sparse(self):
        sparse_member = tarfile.TarInfo("sparse")
        sparse_member.type = tarfile.GNUTYPE_SPARSE
        sparse_member.size = 0
        self._create_sample_tar(extra_members=[(sparse_member, None)])

        with self.assertRaises(RuntimeError) as cm:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Rejecting sparse/gnu-special member", str(cm.exception))

    @patch("tarfile.open")
    def test_allow_sparse(self, mock_open):
        mock_tf = MagicMock()
        sparse_member = MagicMock()
        sparse_member.name = "sparse"
        sparse_member.type = tarfile.GNUTYPE_SPARSE
        sparse_member.isdir.return_value = False
        sparse_member.isreg.return_value = False
        sparse_member.issym.return_value = False
        sparse_member.islnk.return_value = False
        sparse_member.size = 0
        mock_tf.__iter__.return_value = iter([sparse_member])
        mock_open.return_value.__enter__.return_value = mock_tf

        with self.assertRaises(RuntimeError) as cm:
            extraction.safe_extract_atomic(
                self.tar_path, self.dest_dir, reject_sparse=False
            )
        self.assertIn("Unsupported or disallowed tar member type", str(cm.exception))

    def test_skip_pax_headers(self):
        pax_member = tarfile.TarInfo("paxheader")
        pax_member.type = tarfile.XHDTYPE
        pax_member.size = 7
        pax_member.name = "./paxheader"
        self._create_sample_tar(extra_members=[(pax_member, b"path=foo")])

        # No exception, skips (not yielded by tarfile)
        extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertTrue((self.dest_dir / "mydir" / "file.txt").exists())

    def test_unknown_member_type(self):
        unknown_member = tarfile.TarInfo("unknown")
        unknown_member.type = b"?"
        unknown_member.size = 0
        self._create_sample_tar(extra_members=[(unknown_member, None)])

        with self.assertRaises(RuntimeError) as cm:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        self.assertIn("Unsupported or disallowed tar member type", str(cm.exception))

    @patch("shutil.rmtree")
    def test_atomic_swap_with_existing_dir(self, mock_rmtree):
        # Pre-create dest_dir with a file
        self.dest_dir.mkdir()
        (self.dest_dir / "existing.txt").write_text("old")

        extraction.safe_extract_atomic(self.tar_path, self.dest_dir)

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

    @patch("time.time", return_value=1234567890)
    def test_atomic_swap_rollback(self, mock_time):
        original_replace = Path.replace

        def replace_side_effect(src, dst):
            if src == self.dest_dir:
                return original_replace(src, dst)
            elif src.name.startswith(f"{self.dest_dir.name}.new_"):
                raise OSError("swap fail")
            else:
                return original_replace(src, dst)

        with patch("pathlib.Path.replace", side_effect=replace_side_effect):
            # Pre-create dest_dir
            self.dest_dir.mkdir()
            (self.dest_dir / "existing.txt").write_text("old")

            with self.assertRaises(OSError) as cm:
                extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
            self.assertIn("swap fail", str(cm.exception))

            # Rollback: dest_dir restored
            self.assertTrue((self.dest_dir / "existing.txt").exists())

    @patch("time.time", return_value=1234567890)
    @patch("projectrestore.modules.extraction.LOG")
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

        with patch("pathlib.Path.replace", side_effect=replace_side_effect):
            # Pre-create dest_dir
            self.dest_dir.mkdir()
            (self.dest_dir / "existing.txt").write_text("old")

            with self.assertRaises(OSError) as cm:
                extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
            self.assertIn("swap fail", str(cm.exception))
            mock_log.exception.assert_called_once_with(
                "Failed during swap/rename: %s", mock.ANY
            )
            mock_log.error.assert_called_once_with(
                "Rollback failed; manual intervention required. Backup left at %s",
                backup_dir,
            )

    @patch("shutil.rmtree", side_effect=OSError("rmtree fail"))
    def test_backup_rmtree_fail(self, mock_rmtree):
        self.dest_dir.mkdir()
        with patch("projectrestore.modules.extraction.LOG.warning") as mock_log:
            extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        mock_rmtree.assert_called_once()
        mock_log.assert_called_with(
            "Failed to remove backup directory %s (non-fatal)", mock.ANY
        )

    def test_touch_for_none_fileobj(self):
        # Create tar with reg size=0
        zero_file_info = tarfile.TarInfo("zero.txt")
        zero_file_info.size = 0
        zero_file_info.mode = 0o644
        zero_file_info.mtime = self.mtime
        zero_file_info.type = tarfile.REGTYPE
        self._create_sample_tar(extra_members=[(zero_file_info, None)])

        extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        zero_file = self.dest_dir / "zero.txt"
        self.assertTrue(zero_file.exists())
        self.assertEqual(zero_file.read_bytes(), b"")

    @patch.object(tarfile.TarFile, "extractfile", return_value=None)
    def test_touch_for_none_extractfile(self, mock_extractfile):
        # Force f=None for reg member
        extraction.safe_extract_atomic(self.tar_path, self.dest_dir)
        mock_extractfile.assert_called()
        self.assertTrue((self.dest_dir / "mydir" / "file.txt").exists())

    # To cover allow_pax skip branch (not naturally hit)
    @patch("tarfile.open")
    @patch.object(extraction, "LOG")
    def test_skip_pax_with_mock(self, mock_log, mock_open):
        mock_tf = MagicMock()
        pax_member = MagicMock()
        pax_member.name = "pax"
        pax_member.type = tarfile.XHDTYPE
        reg_member = MagicMock()
        reg_member.name = "file.txt"
        reg_member.isdir.return_value = False
        reg_member.isreg.return_value = True
        reg_member.issym.return_value = False
        reg_member.islnk.return_value = False
        reg_member.type = tarfile.REGTYPE
        reg_member.size = 10
        mock_tf.extractfile.return_value = io.BytesIO(b"")
        mock_tf.__iter__.return_value = iter([pax_member, reg_member])
        mock_open.return_value.__enter__.return_value = mock_tf

        extraction.safe_extract_atomic(
            self.tar_path, self.dest_dir, allow_pax=True, dry_run=True
        )

        mock_log.debug.assert_called_once_with(
            "Skipping pax/global header member: %s (type=%s)", "pax", tarfile.XHDTYPE
        )
