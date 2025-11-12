import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from projectrestore.modules import checksum


class TestChecksum(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_file = self.temp_dir / "test.bin"
        self.test_file.write_bytes(b"checksum test")

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_compute_sha256(self):
        actual = checksum.compute_sha256(self.test_file)
        self.assertEqual(
            actual, "50743bc89b03b938f412094255c8e3cf1658b470dbc01d7db80a11dc39adfb9a"
        )

    def test_verify_match(self):
        sum_file = self.temp_dir / "checksum.txt"
        sum_file.write_text(
            "50743bc89b03b938f412094255c8e3cf1658b470dbc01d7db80a11dc39adfb9a  test.bin"
        )

        self.assertTrue(checksum.verify_sha256_from_file(self.test_file, sum_file))

    def test_verify_mismatch(self):
        sum_file = self.temp_dir / "checksum.txt"
        sum_file.write_text(
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        )

        self.assertFalse(checksum.verify_sha256_from_file(self.test_file, sum_file))

    def test_empty_checksum_file(self):
        sum_file = self.temp_dir / "checksum.txt"
        sum_file.touch()

        self.assertFalse(checksum.verify_sha256_from_file(self.test_file, sum_file))

    def test_checksum_read_exception(self):
        with patch("builtins.open", side_effect=OSError("read fail")):
            self.assertFalse(
                checksum.verify_sha256_from_file(
                    self.test_file, self.temp_dir / "missing.txt"
                )
            )
