"""Autouse isolation for the total-block research window and research game.

The record lives in ``/var/lib/steam-backlog-enforcer`` (root only) and the
install step checks pacman's real ``db.lck``. A test that reached either would
open or burn a window on the developer's machine, so both are redirected to
``tmp_path`` for every test, and the module-level memory (corrupt-record log
dedupe, install backoff, windows already released) starts empty each time.
The research game slot (game-research's approval file in ``~/.config``, the
root record, the audit log and the home its session flags must sit under) is
redirected the same way.
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
    """Point research records, files and pacman lock at tmp_path; reset memory."""
    rg = "steam_backlog_enforcer._research_game"
    home = tmp_path / "fake_home"
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
        patch(
            f"{rg}.APPROVAL_FILE",
            home / ".config" / "game-research" / "research_game.json",
        ),
        patch(f"{rg}.RECORD_FILE", tmp_path / "research" / "research_game.json"),
        patch(f"{rg}.AUDIT_LOG", tmp_path / "research" / "audit.log"),
        patch(f"{rg}.HOME", home),
    ):
        yield
