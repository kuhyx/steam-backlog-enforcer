"""Autouse redirection of the playtime module's on-disk state.

Split out of ``conftest.py`` to keep every file inside the 250-line cap;
``conftest`` imports the fixture by name, which is what registers it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_playtime(tmp_path: Path) -> Iterator[None]:
    """Redirect the daily-gaming-budget paths to a temporary directory.

    Separate from :func:`_isolate_filesystem` only because CPython caps a
    ``with`` statement at 20 statically nested blocks and that fixture is
    already at the limit.

    The ``BLOCK_TARGETS`` patch is the load-bearing one: unpatched, that tuple
    names the real ``/usr/bin/steam``, and a test reaching the mount code would
    mask the user's actual Steam install behind a refusal stub.
    """
    # Namespaced names: an autouse fixture that creates bare "proc"/"targets"
    # inside tmp_path would claim those names for every other test in the
    # suite (test_enforcer builds its own tmp_path/"proc" with mkdir()).
    fake_config = tmp_path / "config"
    fake_config.mkdir(exist_ok=True)
    fake_proc = tmp_path / "playtime_proc"
    fake_proc.mkdir(exist_ok=True)
    fake_targets = tmp_path / "playtime_targets"
    fake_targets.mkdir(exist_ok=True)

    with (
        # Computed at import time from CONFIG_DIR, so patching CONFIG_DIR
        # alone does not redirect them.
        patch(
            "steam_backlog_enforcer._playtime_state.PLAYTIME_STATE_FILE",
            fake_config / "playtime_state.json",
        ),
        patch(
            "steam_backlog_enforcer._playtime_state.PLAYTIME_DEMO_STATE_FILE",
            fake_config / "playtime_demo_state.json",
        ),
        # Per-day history. Derived from CONFIG_DIR at import time, so patching
        # CONFIG_DIR alone does not redirect it.
        patch(
            "steam_backlog_enforcer._playtime_history.HISTORY_FILE",
            fake_config / "playtime_history.json",
        ),
        # The audit log lives under /var/log, outside CONFIG_DIR entirely, and
        # is the record used to reconstruct real incidents — a test must never
        # append to it, nor read the host's.
        patch(
            "steam_backlog_enforcer._playtime_log.BUDGET_LOG_FILE",
            tmp_path / "budget.jsonl",
        ),
        patch(
            "steam_backlog_enforcer._playtime_log.BUDGET_DEMO_LOG_FILE",
            tmp_path / "budget-demo.jsonl",
        ),
        patch("steam_backlog_enforcer._playtime_procs._PROC", fake_proc),
        patch("steam_backlog_enforcer._playtime_kill._PROC", fake_proc),
        # Never let a test chattr +i a file inside tmp_path — pytest could
        # then not clean the directory up.
        patch("steam_backlog_enforcer._playtime_state._try_set_immutable", MagicMock()),
        patch("steam_backlog_enforcer._playtime_state.unlock_for_write", MagicMock()),
        patch(
            "steam_backlog_enforcer._playtime_block.BLOCK_TARGETS",
            (
                fake_targets / "steam",
                fake_targets / "bin_steam.sh",
                fake_targets / "steam.sh",
                fake_targets / "lutris",
            ),
        ),
        patch("steam_backlog_enforcer._playtime_block._STUB_DIR", tmp_path / "run"),
        patch(
            "steam_backlog_enforcer._playtime_block.STUB_PATH",
            tmp_path / "run" / "gaming-blocked",
        ),
        patch(
            "steam_backlog_enforcer._playtime_block.MOUNTINFO_PATH",
            tmp_path / "mountinfo",
        ),
        patch(
            "steam_backlog_enforcer._playtime_block._INIT_MOUNTINFO_PATH",
            tmp_path / "init_mountinfo",
        ),
        patch(
            "steam_backlog_enforcer._playtime_block.PACMAN_LOCK", tmp_path / "db.lck"
        ),
        patch("steam_backlog_enforcer._playtime_block._PROC", fake_proc),
    ):
        yield
