# projectrestore/tests/test_restore_extended.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch
import projectrestore.cli
from projectrestore.modules import locking

class TestRestoreExtended:

    # --- CLI Tests ---

    def test_restore_no_backup_found(self, tmp_path, caplog):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        with patch.object(sys, 'argv', ['extract_backup.py', '--backup-dir', str(backup_dir)]):
            ret = projectrestore.cli.main()
            assert ret == 1

        assert "No backup file found" in caplog.text

    def test_restore_lock_fail(self, tmp_path, caplog):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        with patch.object(sys, 'argv', ['extract_backup.py', '--backup-dir', str(backup_dir)]):
            with patch("projectrestore.cli.create_pid_lock", side_effect=Exception("Lock fail")):
                ret = projectrestore.cli.main()
                assert ret == 1

        assert "Failed to acquire lock" in caplog.text

    def test_restore_extract_fail(self, tmp_path, caplog):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "backup-bot_platform-2023.tar.gz").touch()

        with patch.object(sys, 'argv', ['extract_backup.py', '--backup-dir', str(backup_dir)]):
            with patch("projectrestore.cli.safe_extract_atomic", side_effect=Exception("Extract fail")):
                ret = projectrestore.cli.main()
                assert ret == 1

        assert "Extraction failed" in caplog.text

    def test_vault_restore_fail(self, tmp_path):
        with patch.object(sys, 'argv', ['extract_backup.py', 'vault-restore', 'm', 'd']):
            with patch("projectrestore.cli.restore_engine.restore_snapshot", side_effect=Exception("Fail")):
                with pytest.raises(SystemExit):
                    projectrestore.cli.main()

    # --- Locking Tests ---

    def test_pid_lock_invalid_content_exit(self, tmp_path):
        lockfile = tmp_path / "lock.pid"
        lockfile.write_text("invalid")

        with pytest.raises(SystemExit) as excinfo:
            locking.create_pid_lock(lockfile)
        assert excinfo.value.code == 3

    def test_pid_lock_stale_overwrite(self, tmp_path):
        lockfile = tmp_path / "lock.pid"
        lockfile.write_text("99999")
        # Make it old
        import time
        os.utime(lockfile, (time.time()-7200, time.time()-7200))

        # We mock projectrestore.modules.locking.psutil instead of just psutil
        # assuming the module imports it.
        # However, checking the error, it says ModuleNotFoundError: No module named 'psutil'
        # This means psutil is not installed in the environment, so we cannot even patch it if we try to import it to patch it.
        # We need to use patch.dict on sys.modules to mock psutil existence first, OR patch where it is used.

        # If locking.py does `import psutil`, then we need to mock it in sys.modules before locking is imported?
        # But locking is already imported.

        # The error in the test log showed:
        #   File "projectrestore/tests/test_restore_extended.py", line 69, in test_pid_lock_stale_overwrite
        #     with patch("psutil.pid_exists", return_value=False):
        # ...
        #   ModuleNotFoundError: No module named 'psutil'

        # This happens because patch attempts to import psutil to verify the attribute exists or to patch it.

        # Since psutil is an optional dependency (or missing dependency), we should probably mock it completely.

        mock_psutil = MagicMock()
        mock_psutil.pid_exists.return_value = False

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
             # We might need to reload locking module if it imports psutil at top level
             # checking locking.py:
             # try: import psutil; except ImportError: psutil = None

             # If it was already imported as None, we need to force it to see our mock.
             import importlib
             import projectrestore.modules.locking
             importlib.reload(projectrestore.modules.locking)

             projectrestore.modules.locking.create_pid_lock(lockfile, stale_seconds=3600)
             assert lockfile.read_text().strip() == str(os.getpid())

    # --- Engine/Logic Tests ---

    def test_restore_engine_metadata_fail(self, tmp_path, capsys):
        # Test metadata application failure warning
        from projectrestore import restore_engine

        # Correct structure: vault/snapshots/m.json (if we assume manifest in root of snapshots works)
        # Or vault/snapshots/proj/m.json AND vault/snapshots/objects (if we want relative path to work)

        vault = tmp_path / "vault"
        snapshots_dir = vault / "snapshots"
        snapshots_dir.mkdir(parents=True)
        objects_dir = vault / "objects"
        objects_dir.mkdir(parents=True)
        (objects_dir / "hash1").write_text("content")

        # restore_engine.py calculates objects_dir as:
        # manifest_dir = dirname(manifest_path)
        # objects_dir = abspath(join(manifest_dir, "../objects"))

        # If manifest is in vault/snapshots/m.json:
        # manifest_dir = vault/snapshots
        # objects_dir = vault/objects
        # This matches where we put objects!

        manifest = snapshots_dir / "m.json"
        manifest.write_text('{"files": {"f1": {"hash": "hash1", "mode": 511}}}')

        dest = tmp_path / "dest"

        # Mock shutil.copy2 to succeed
        with patch("shutil.copy2"):
            # Mock os.chmod to fail
            with patch("projectrestore.restore_engine.os.chmod", side_effect=OSError("Chmod fail")):
                restore_engine.restore_snapshot(str(manifest), str(dest))

        captured = capsys.readouterr()
        assert "Warning: Failed to apply metadata" in captured.out
