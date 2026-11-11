"""Tests for the main CLI: raw-argv command dispatch."""

import sys
from unittest.mock import (
    patch,
)

import pytest

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    main,
)
from steam_backlog_enforcer.tests._main_dispatch_world import (
    PKG,
    SHARED,
    cli_run,
    status_stubs,
)
from steam_backlog_enforcer.tests._main_helpers import (
    ACTIVE_STATUS,
    VALID_REASON,
    locked_state,
)

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done"


class TestMainDispatchAddException:
    """add-exception reaches its command handler."""

    def test_dispatches_add_exception(self) -> None:
        """The raw tail argv is handed to cmd_add_exception."""
        argv = ["prog", "add-exception", "440", "--reason", VALID_REASON]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.cmd_add_exception") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once_with(["440", "--reason", VALID_REASON])


class TestMainDispatchServe:
    """serve reaches its command handler."""

    def test_dispatches_serve_with_raw_argv(self) -> None:
        """serve gets its flags untouched."""
        # serve parses its own flags, so the dispatcher must hand the argv
        # through untouched rather than pre-parsing it.
        argv = ["prog", "serve", "--port", "8123"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(f"{PKG}.cmd_serve") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once_with(["--port", "8123"])


class TestMainDispatchUnblock:
    """unblock reaches its command handler."""

    def test_dispatches_unblock_with_minutes(self) -> None:
        """The minutes argument is passed through to cmd_unblock."""
        argv = ["prog", "unblock", "10"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(f"{PKG}.cmd_unblock") as mock_cmd,
        ):
            main()
        assert mock_cmd.call_args.args[2] == ["10"]


class TestMainDispatchPickManual:
    """pick-manual reaches its command handler."""

    def test_dispatches_pick_manual(self) -> None:
        """pick-manual calls cmd_pick_manual."""
        argv = ["prog", "pick-manual", "489830"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(f"{PKG}.cmd_pick_manual") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once()

    def test_pick_manual_dispatches_while_locked(self) -> None:
        """pick-manual is not stopped by an active lock."""
        # Reaching cmd_pick_manual is required for a second concurrent pick.
        argv = ["prog", "pick-manual", "730"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=locked_state()),
            patch(f"{PKG}.cmd_pick_manual") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once()


# ──────────────────────────────────────────────────────────────
# cmd_status shows lock hint when locked
# ──────────────────────────────────────────────────────────────


class TestMainDispatchBlockGaming:
    """block-gaming dispatch and the total-block gate."""

    def test_dispatches_block_gaming(self) -> None:
        """block-gaming passes its day count to the handler."""
        argv = ["prog", "block-gaming", "14"]
        with (
            cli_run(argv, total_block=False),
            patch(f"{PKG}.cmd_block_gaming") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once_with(["14"])

    def test_blocked_when_already_active(self) -> None:
        """A gated command exits 1 during a total block."""
        argv = ["prog", "scan"]
        with (
            cli_run(argv, total_block=True),
            patch(f"{SHARED}.get_total_block_status", return_value=ACTIVE_STATUS),
            patch(f"{SHARED}._show_total_block_lock_message"),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1

    def test_status_allowed_when_active(self) -> None:
        """status still runs and prints during a total block."""
        # "status" is dispatched via the COMMANDS dict, which captures the
        # cmd_status function reference at import time - patching
        # main.cmd_status would not intercept it. Verify real behavior
        # (no SystemExit, real status output) instead.
        argv = ["prog", "status"]
        with (
            cli_run(argv, total_block=True),
            status_stubs(stub_completion=False) as mock_echo,
        ):
            main()  # must not raise SystemExit
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Steam Backlog Enforcer" in output
