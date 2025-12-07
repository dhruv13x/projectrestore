import sys
import pytest
from unittest.mock import MagicMock, patch
from projectrestore import cli

class TestProjectRestoreCliCoverageV2:
    def test_vault_restore_main_success(self):
        with patch.object(sys, 'argv', ['projectrestore', 'vault-restore', 'manifest.json', 'dest']):
             with patch("projectrestore.restore_engine.restore_snapshot") as mock_restore:
                 rc = cli.main()
                 assert rc == 0
                 mock_restore.assert_called()

    def test_vault_restore_main_exception(self, capsys):
        with patch.object(sys, 'argv', ['projectrestore', 'vault-restore', 'manifest.json', 'dest']):
             with patch("projectrestore.restore_engine.restore_snapshot", side_effect=Exception("Restoration Failed")):
                 with pytest.raises(SystemExit) as exc:
                     cli.main()
                 assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Restoration Failed" in captured.out

    def test_main_cloud_download_fail(self, capsys):
        with patch.object(sys, 'argv', ['projectrestore', '--cloud', '--bucket', 'b', '--file', 'f']):
             with patch("projectrestore.cli.download_from_cloud", return_value=False):
                 rc = cli.main()
                 assert rc == 1
        captured = capsys.readouterr()

    def test_main_cloud_args_missing(self, capsys):
        with patch.object(sys, 'argv', ['projectrestore', '--cloud', '--bucket', 'b']):
             rc = cli.main()
             assert rc == 1
        captured = capsys.readouterr()

    def test_main_no_backup_found(self, capsys):
        with patch.object(sys, 'argv', ['projectrestore', '-b', '/tmp/empty']):
             with patch("projectrestore.cli.find_latest_backup", return_value=None):
                 rc = cli.main()
                 assert rc == 1
        captured = capsys.readouterr()

    def test_download_from_cloud_success(self):
        # Test success path for download_from_cloud function directly
        with patch("src.common.credentials.resolve_credentials", return_value=("k", "s", "Env")):
            with patch("src.common.credentials.get_cloud_provider_info", return_value=("Backblaze B2", "b", "e")):
                # Mock B2Manager in src.common.b2
                with patch("src.common.b2.B2Manager") as MockB2:
                    instance = MockB2.return_value
                    instance.download_file.return_value = None

                    res = cli.download_from_cloud("bucket", "file", "dest")
                    assert res is True
                    instance.download_file.assert_called_with("file", "dest")

    def test_download_from_cloud_exception(self, capsys):
        with patch("src.common.credentials.resolve_credentials", return_value=("k", "s", "Env")):
            with patch("src.common.credentials.get_cloud_provider_info", return_value=("Backblaze B2", "b", "e")):
                with patch("src.common.b2.B2Manager", side_effect=Exception("Download Fail")):
                    res = cli.download_from_cloud("bucket", "file", "dest")
                    assert res is False
