"""Autouse isolation of the shared /proc scan and the shadow leisure inputs.

The scanners moved to ``leisure_watch.procscan`` read ``/proc`` through their
own module constants, and the shadow tick reads the desktop user's gatelock
claims, i3lock and the watcher's signed ``now.json``. Unpatched, a test would
see the developer's live games, lockers and browser.

Default: nothing paused and no trusted watcher fact (the fail-closed reading).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_shadow(tmp_path: Path) -> Iterator[None]:
    """Point the scan at an empty /proc and the shadow inputs at nothing."""
    fake_proc = tmp_path / "procscan_proc"
    fake_proc.mkdir(exist_ok=True)
    with (
        patch("leisure_watch.procscan._steam._PROC", fake_proc),
        patch("leisure_watch.procscan._cmdline._PROC", fake_proc),
        patch("steam_backlog_enforcer._shadow.paused_by", return_value=None),
        patch("steam_backlog_enforcer._shadow.read_now", return_value=None),
    ):
        yield
