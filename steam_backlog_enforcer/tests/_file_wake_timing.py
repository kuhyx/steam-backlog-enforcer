"""Shared timing knobs and a timed wait for the _file_wake test modules."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steam_backlog_enforcer._file_wake import FileWake

PKG = "steam_backlog_enforcer._file_wake"
# Far above real latency so CI cannot flake; elapsed asserts pin "early".
LONG = 5.0
SHORT = 0.05


def timed_wait(watcher: FileWake, timeout: float) -> tuple[bool, float]:
    """Run ``watcher.wait`` and measure how long it took."""
    start = time.monotonic()
    woke = watcher.wait(timeout)
    return woke, time.monotonic() - start
