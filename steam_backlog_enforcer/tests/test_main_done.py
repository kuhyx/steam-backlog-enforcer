"""Tests for the main CLI: done command dispatch."""

from typing import TYPE_CHECKING

from steam_backlog_enforcer.main import (
    cmd_done,
)
from steam_backlog_enforcer.tests._cmd_done_cases import CmdDoneCases

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State


class TestCmdDone(CmdDoneCases):
    """Tests for cmd_done reached through ``steam_backlog_enforcer.main``."""

    def run_done(self, config: Config, state: State) -> None:
        """Call the CLI's re-exported cmd_done."""
        cmd_done(config, state)
