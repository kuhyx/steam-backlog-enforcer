"""Tests for ``cmd_done``: fetch, the completion verdict and the HLTB estimate.

Split out of ``test_main_part2b.py`` to keep both files inside the 250-line cap.
"""

from typing import TYPE_CHECKING

from steam_backlog_enforcer._cmd_done_finalize import cmd_done
from steam_backlog_enforcer.tests._cmd_done_cases import CmdDoneCases

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State


class TestCmdDoneVerdict(CmdDoneCases):
    """Tests for cmd_done imported from its defining module."""

    def run_done(self, config: Config, state: State) -> None:
        """Call cmd_done from ``_cmd_done_finalize``."""
        cmd_done(config, state)
