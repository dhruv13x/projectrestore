# projectrestore/tests/test_cli_ext_v2.py


import pytest
import sys
import os
from unittest.mock import MagicMock, patch
from pathlib import Path
from projectrestore import cli

@pytest.fixture
def mock_credentials_module():
    mock_creds = MagicMock()
    # Since the import is inside a function, we must patch sys.modules
    # to ensure our mock is loaded by 'from src.common import credentials'
    with patch.dict('sys.modules', {'src.common.credentials': mock_creds}):
        yield mock_creds

class TestProjectRestoreCliExtended:
    @pytest.fixture
    def mock_args(self):
        """Mock standard arguments."""
        args = MagicMock()
        args.backup_dir = "/tmp/backups"
        args.extract_dir = None
        args.pattern = "*.tar.gz"
        args.lockfile = "/tmp/lock.pid"
        args.checksum = None
        args.stale_seconds = 3600
        args.debug = False
        args.max_files = None
        args.max_bytes = None
        args.allow_pax = False
        args.allow_sparse = False
        args.dry_run = False
        args.cloud = False
        args.bucket = None
        args.endpoint = None
        args.file = None
        return args

    def test_get_cloud_credentials_aws_env(self):
        """Test cloud credentials resolution for AWS from env."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_credentials.return_value = ("pv_aws_key", "pv_aws_secret", "Environment")
        mock_resolver.get_cloud_provider_info.return_value = ("AWS S3", None, None)

        provider, key, secret = cli.get_cloud_credentials(resolver=mock_resolver)
        assert provider == "s3"
        assert key == "pv_aws_key"
        assert secret == "pv_aws_secret"

    def test_get_cloud_credentials_b2_env(self):
        """Test cloud credentials resolution for B2 from env."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_credentials.return_value = ("pv_b2_key", "pv_b2_app", "Environment")
        mock_resolver.get_cloud_provider_info.return_value = ("Backblaze B2", None, None)

        provider, key, app = cli.get_cloud_credentials(resolver=mock_resolver)
        assert provider == "b2"
        assert key == "pv_b2_key"
        assert app == "pv_b2_app"

    def test_get_cloud_credentials_none(self):
        """Test cloud credentials resolution when none are present."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_credentials.return_value = (None, None, None)
        assert cli.get_cloud_credentials(resolver=mock_resolver) == (None, None, None)

    @patch("projectrestore.cli.get_cloud_credentials")
    def test_download_from_cloud_missing_creds(self, mock_creds, capsys):
        mock_creds.return_value = (None, None, None)
        res = cli.download_from_cloud("bucket", "remote", Path("/tmp/local"))
        assert res is False

    @patch("projectrestore.cli.get_cloud_credentials")
    @patch("src.common.s3.S3Manager")
    def test_download_from_cloud_s3(self, mock_s3_manager, mock_creds):
        mock_creds.return_value = ("s3", "key", "secret")
        manager = mock_s3_manager.return_value
        with patch.dict('sys.modules', {'src.common.b2': MagicMock(), 'src.common.s3': MagicMock(S3Manager=mock_s3_manager)}):
            res = cli.download_from_cloud("bucket", "remote", Path("/tmp/local"))
            assert res is True
            manager.download_file.assert_called_with("remote", "/tmp/local")

    @patch("projectrestore.cli.get_cloud_credentials")
    @patch("src.common.b2.B2Manager")
    def test_download_from_cloud_b2(self, mock_b2_manager, mock_creds):
        mock_creds.return_value = ("b2", "key", "app")
        manager = mock_b2_manager.return_value
        with patch.dict('sys.modules', {'src.common.b2': MagicMock(B2Manager=mock_b2_manager), 'src.common.s3': MagicMock()}):
            res = cli.download_from_cloud("bucket", "remote", Path("/tmp/local"))
            assert res is True
            manager.download_file.assert_called_with("remote", "/tmp/local")

    @patch("projectrestore.cli.restore_engine")
    def test_vault_restore_main(self, mock_engine):
        test_args = ["pv", "vault-restore", "manifest.json", "/tmp/dest"]
        with patch.object(sys, 'argv', test_args):
             cli.main()
        mock_engine.restore_snapshot.assert_called()

    def test_parse_args_help(self):
        test_args = ["pv"]
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(SystemExit) as exc:
                cli.parse_args()
            assert exc.value.code == 0

    @patch("projectrestore.cli.parse_args")
    @patch("projectrestore.cli.create_pid_lock")
    @patch("projectrestore.cli.release_pid_lock")
    @patch("projectrestore.cli.find_latest_backup")
    @patch("projectrestore.cli.safe_extract_atomic")
    @patch("projectrestore.cli.count_files")
    def test_main_success(self, mock_count, mock_extract, mock_find, mock_release, mock_lock, mock_parse, mock_args):
        mock_parse.return_value = mock_args
        mock_find.return_value = Path("/tmp/backups/backup.tar.gz")
        mock_count.return_value = 10

        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.mkdir"):

             rc = cli.main()
             assert rc == 0
             mock_extract.assert_called()
             mock_release.assert_called()

    @patch("projectrestore.cli.parse_args")
    @patch("projectrestore.cli.create_pid_lock")
    def test_main_lock_fail(self, mock_lock, mock_parse, mock_args):
        mock_parse.return_value = mock_args
        mock_lock.side_effect = Exception("Lock error")

        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.mkdir"):

             rc = cli.main()
             assert rc == 1

    @patch("projectrestore.cli.parse_args")
    @patch("projectrestore.cli.create_pid_lock")
    @patch("projectrestore.cli.release_pid_lock")
    @patch("projectrestore.cli.download_from_cloud")
    @patch("projectrestore.cli.safe_extract_atomic")
    @patch("projectrestore.cli.count_files")
    def test_main_cloud_download_success(self, mock_count, mock_extract, mock_dl, mock_release, mock_lock, mock_parse, mock_args):
        mock_args.cloud = True
        mock_args.bucket = "bucket"
        mock_args.file = "backup.tar.gz"
        mock_parse.return_value = mock_args
        mock_dl.return_value = True
        mock_count.return_value = 10

        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.mkdir"):

             rc = cli.main()
             assert rc == 0
             mock_dl.assert_called()

    @patch("projectrestore.cli.parse_args")
    @patch("projectrestore.cli.create_pid_lock")
    @patch("projectrestore.cli.release_pid_lock")
    def test_main_cloud_download_fail(self, mock_release, mock_lock, mock_parse, mock_args):
        mock_args.cloud = True
        mock_args.bucket = "bucket"
        mock_args.file = "backup.tar.gz"
        mock_parse.return_value = mock_args

        with patch("projectrestore.cli.download_from_cloud", return_value=False), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.mkdir"):

             rc = cli.main()
             assert rc == 1

    @patch("projectrestore.cli.parse_args")
    @patch("projectrestore.cli.create_pid_lock")
    @patch("projectrestore.cli.release_pid_lock")
    @patch("projectrestore.cli.verify_sha256_from_file")
    def test_main_checksum_fail(self, mock_verify, mock_release, mock_lock, mock_parse, mock_args):
        mock_args.checksum = "checksum.sha256"
        mock_parse.return_value = mock_args

        with patch("projectrestore.cli.find_latest_backup", return_value=Path("/tmp/backups/backup.tar.gz")), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.mkdir"):

             mock_verify.return_value = False
             rc = cli.main()
             assert rc == 1
