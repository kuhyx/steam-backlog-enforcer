"""Autouse isolation for the total-block research window.

The record lives in ``/var/lib/steam-backlog-enforcer`` (root only) and the
install step checks pacman's real ``db.lck``. A test that reached either would
open or burn a window on the developer's machine, so both are redirected to
``tmp_path`` for every test, and the module-level memory (corrupt-record log
dedupe, install backoff, windows already released) starts empty each time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _research_net, _research_window

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_research(tmp_path: Path) -> Iterator[None]:
    """Point the research record and pacman lock at tmp_path; reset memory."""
    _research_window.LOGGED.clear()
    _research_net.RETRY.clear()
    _research_net.RELEASED.clear()
    with (
        patch(
            "steam_backlog_enforcer._research_record.RESEARCH_FILE",
            tmp_path / "research" / "total_block_research.json",
        ),
        patch(
            "steam_backlog_enforcer._research_net.DB_LOCK_FILE",
            tmp_path / "pacman" / "db.lck",
        ),
    ):
        yield
