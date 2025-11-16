# src/projectrestore/modules/signals.py

from __future__ import annotations
import signal
import logging
from typing import Callable, List

LOG = logging.getLogger(__name__)


class GracefulShutdown:
    def __init__(self):
        self._callbacks: List[Callable] = []

    def register(self, cb: Callable) -> None:
        self._callbacks.append(cb)

    def _handler(self, signum, frame) -> None:
        LOG.info("Received signal %s, running cleanup...", signum)
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                LOG.debug("Cleanup callback raised exception (ignored).")
        raise SystemExit(2)

    def install(self) -> None:
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(s, self._handler)
            except Exception:
                LOG.debug("Could not install handler for signal %s", s)
