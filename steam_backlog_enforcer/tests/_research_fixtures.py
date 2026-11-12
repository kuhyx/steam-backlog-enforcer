"""Fixtures for the daemon-pass tests: every effect of one pass is a mock."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._research_tick import total_block_pass
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._research_helpers import NOW, lock

if TYPE_CHECKING:
    from collections.abc import Iterator

    from steam_backlog_enforcer.tests._total_block_paths import Paths

PKG = "steam_backlog_enforcer._research_tick"
BLOCK = "steam_backlog_enforcer._total_block"
NOW_PATCH = "steam_backlog_enforcer._research_window.now"


@dataclass
class SteamMocks:
    """The pass's Steam package effects."""

    installed: MagicMock
    kill: MagicMock
    uninstall: MagicMock
    purge: MagicMock


@dataclass
class Mocks:
    """The collaborators of one pass, all stand-ins."""

    block_tick: MagicMock
    reconcile: MagicMock
    launchers: MagicMock
    counted: MagicMock
    enforce: MagicMock
    guard: MagicMock
    notify: MagicMock
    restore_store: MagicMock
    steam: SteamMocks


@pytest.fixture
def tm(total_block_paths: Paths) -> Iterator[Mocks]:
    """An active total block with every effect replaced by a mock."""
    lock(total_block_paths)
    with (
        patch(f"{PKG}.enforce_total_block_tick") as block_tick,
        patch(f"{PKG}.reconcile_open_window") as reconcile,
        patch(f"{PKG}.kill_and_uninstall_launchers", return_value=[]) as launchers,
        patch(f"{PKG}.kill_processes_by_name", return_value=[]) as counted,
        patch(f"{PKG}.steam_is_installed", return_value=True) as installed,
        patch(f"{PKG}.enforce_allowed_game", return_value=[]) as enforce,
        patch(f"{PKG}.guard_installed_games", return_value=0) as guard,
        patch(f"{PKG}.send_notification") as notify,
        patch(f"{PKG}.restore_store_block", return_value=True) as restore_store,
        patch(f"{BLOCK}.kill_steam_and_launchers") as steam_kill,
        patch(f"{BLOCK}.uninstall_steam_package") as steam_uninstall,
        patch(f"{BLOCK}.purge_steam_and_proton") as steam_purge,
    ):
        yield Mocks(
            block_tick,
            reconcile,
            launchers,
            counted,
            enforce,
            guard,
            notify,
            restore_store,
            SteamMocks(installed, steam_kill, steam_uninstall, steam_purge),
        )


def run_pass(now: float = NOW, *, block_store: bool = True) -> None:
    """Run one total-block pass with the clock at *now*."""
    with patch(NOW_PATCH, return_value=now):
        total_block_pass(Config(block_store=block_store))
