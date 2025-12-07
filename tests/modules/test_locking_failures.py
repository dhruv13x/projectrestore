# projectrestore/tests/modules/test_locking_failures.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from projectrestore.modules import locking

class TestLockingFailures:
    """Tests for projectrestore/modules/locking.py focusing on edge cases."""

    def test_locking_stale_removal_fail(self, tmp_path):
        lockfile = tmp_path / "lock.pid"
        lockfile.write_text("12345")

        # Mock _is_process_alive to return False (stale)
        with patch("projectrestore.modules.locking._is_process_alive", return_value=False):
            # Mock time to make it look old
            with patch("time.time", return_value=os.path.getmtime(lockfile) + 10000):
                 # Mock unlink to fail
                 with patch("os.unlink", side_effect=OSError("Permission denied")):
                     # Should exit
                     with pytest.raises(SystemExit):
                         locking.create_pid_lock(lockfile)
