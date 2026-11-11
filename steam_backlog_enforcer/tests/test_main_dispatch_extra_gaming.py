"""Tests for the main CLI: enforce and gaming-unblock dispatch."""

from unittest.mock import patch

import pytest

from steam_backlog_enforcer.main import main
from steam_backlog_enforcer.tests._main_dispatch_world import PKG, cli_run


class TestMainDispatchGamingCommands:
    """enforce and gaming-unblock dispatch and exit codes."""

    def test_enforce_passes_its_tail_args_and_exits_with_the_code(self) -> None:
        """`enforce` left COMMANDS because its signature cannot carry --demo."""
        argv = ["prog", "enforce", "--demo"]
        with (
            cli_run(argv, total_block=False),
            patch(f"{PKG}.cmd_enforce", return_value=0) as mock_cmd,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 0
        assert mock_cmd.call_args.args[2] == ["--demo"]

    def test_enforce_propagates_a_nonzero_exit(self) -> None:
        """A nonzero enforce result becomes the exit code."""
        argv = ["prog", "enforce", "--bogus"]
        with (
            cli_run(argv, total_block=False),
            patch(f"{PKG}.cmd_enforce", return_value=2),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 2

    def test_gaming_unblock_dispatches(self) -> None:
        """gaming-unblock calls its handler and exits 0."""
        argv = ["prog", "gaming-unblock"]
        with (
            cli_run(argv, total_block=False),
            patch(f"{PKG}.cmd_gaming_unblock", return_value=0) as mock_cmd,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 0
        mock_cmd.assert_called_once_with([])

    def test_gaming_unblock_reachable_during_a_total_block(self) -> None:
        """A playtime mount makes the total block's own pacman -R fail EBUSY."""
        argv = ["prog", "gaming-unblock"]
        with (
            cli_run(argv, total_block=True),
            patch(f"{PKG}.cmd_gaming_unblock", return_value=0) as mock_cmd,
            pytest.raises(SystemExit),
        ):
            main()
        mock_cmd.assert_called_once_with([])
