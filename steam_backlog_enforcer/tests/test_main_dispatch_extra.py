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
from steam_backlog_enforcer.tests._main_helpers import (
    ACTIVE_STATUS,
    VALID_REASON,
    locked_state,
)

PKG = "steam_backlog_enforcer.main"
CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done"


class TestMainDispatchAddException:
    def test_dispatches_add_exception(self) -> None:
        argv = ["prog", "add-exception", "440", "--reason", VALID_REASON]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.cmd_add_exception") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once_with(["440", "--reason", VALID_REASON])


class TestMainDispatchPickManual:
    def test_dispatches_pick_manual(self) -> None:
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
    def test_dispatches_block_gaming(self) -> None:
        argv = ["prog", "block-gaming", "14"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(
                "steam_backlog_enforcer.main._shared.is_total_block_active",
                return_value=False,
            ),
            patch(f"{PKG}.cmd_block_gaming") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once_with(["14"])

    def test_blocked_when_already_active(self) -> None:
        argv = ["prog", "scan"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(
                "steam_backlog_enforcer.main._shared.is_total_block_active",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.main._shared.get_total_block_status",
                return_value=ACTIVE_STATUS,
            ),
            patch("steam_backlog_enforcer.main._shared._show_total_block_lock_message"),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1

    def test_status_allowed_when_active(self) -> None:
        # "status" is dispatched via the COMMANDS dict, which captures the
        # cmd_status function reference at import time - patching
        # main.cmd_status would not intercept it. Verify real behavior
        # (no SystemExit, real status output) instead.
        argv = ["prog", "status"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(
                "steam_backlog_enforcer.main._shared.is_total_block_active",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.main.status.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.main.status.get_installed_games",
                return_value=[],
            ),
            # cmd_status resolves _echo from its own module, not the package.
            patch("steam_backlog_enforcer.main.status._echo") as mock_echo,
        ):
            main()  # must not raise SystemExit
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Steam Backlog Enforcer" in output


# ──────────────────────────────────────────────────────────────
# cmd_status shows total block info
# ──────────────────────────────────────────────────────────────


class TestMainDispatchGamingCommands:
    def test_enforce_passes_its_tail_args_and_exits_with_the_code(self) -> None:
        """`enforce` left COMMANDS because its signature cannot carry --demo."""
        argv = ["prog", "enforce", "--demo"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(
                "steam_backlog_enforcer.main._shared.is_total_block_active",
                return_value=False,
            ),
            patch(f"{PKG}.cmd_enforce", return_value=0) as mock_cmd,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 0
        assert mock_cmd.call_args.args[2] == ["--demo"]

    def test_enforce_propagates_a_nonzero_exit(self) -> None:
        argv = ["prog", "enforce", "--bogus"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(
                "steam_backlog_enforcer.main._shared.is_total_block_active",
                return_value=False,
            ),
            patch(f"{PKG}.cmd_enforce", return_value=2),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 2

    def test_gaming_unblock_dispatches(self) -> None:
        argv = ["prog", "gaming-unblock"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(
                "steam_backlog_enforcer.main._shared.is_total_block_active",
                return_value=False,
            ),
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
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(
                "steam_backlog_enforcer.main._shared.is_total_block_active",
                return_value=True,
            ),
            patch(f"{PKG}.cmd_gaming_unblock", return_value=0) as mock_cmd,
            pytest.raises(SystemExit),
        ):
            main()
        mock_cmd.assert_called_once_with([])
