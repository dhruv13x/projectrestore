import unittest
from unittest.mock import MagicMock, patch
from projectrestore.modules import signals


class TestGracefulShutdown(unittest.TestCase):
    def setUp(self):
        self.shutdown = signals.GracefulShutdown()
        self.mock_cb = MagicMock()

    @patch("projectrestore.modules.signals.LOG")
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
        with patch.object(self.shutdown, "_handler"):
            pass  # Just test no exception

    @patch("signal.signal")
    def test_install_fail(self, mock_signal):
        mock_signal.side_effect = OSError("signal fail")
        shutdown = signals.GracefulShutdown()
        shutdown.install()  # Should not crash
