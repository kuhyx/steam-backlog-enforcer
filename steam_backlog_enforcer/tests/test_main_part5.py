"""Tests for main CLI module — part 5 (total gaming block lock + command)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._total_block import TotalBlockStatus
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    _TOTAL_BLOCK_EXEMPT_COMMANDS,
    _enforce_total_block_lock,
    _show_total_block_lock_message,
    cmd_block_gaming,
    cmd_status,
    main,
)

PKG = "steam_backlog_enforcer.main"

_ACTIVE_STATUS = TotalBlockStatus(
    active=True,
    started_at=datetime.now(timezone.utc) - timedelta(hours=1),
    until=datetime.now(timezone.utc) + timedelta(hours=23),
    days=1,
    days_remaining=0.96,
)
_INACTIVE_STATUS = TotalBlockStatus(
    active=False, started_at=None, until=None, days=0, days_remaining=0.0
)


# ──────────────────────────────────────────────────────────────
# _show_total_block_lock_message
# ──────────────────────────────────────────────────────────────


class TestShowTotalBlockLockMessage:
    def test_shows_remaining_time(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo:
            _show_total_block_lock_message(_ACTIVE_STATUS)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "TOTAL GAMING BLOCK ACTIVE" in output
        assert "Days remaining" in output

    def test_lists_exempt_commands(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo:
            _show_total_block_lock_message(_ACTIVE_STATUS)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "status" in output
        assert "enforce" in output

    def test_no_crash_without_until(self) -> None:
        status = TotalBlockStatus(
            active=True, started_at=None, until=None, days=1, days_remaining=0.5
        )
        with patch(f"{PKG}._echo"):
            _show_total_block_lock_message(status)  # must not raise


# ──────────────────────────────────────────────────────────────
# _enforce_total_block_lock
# ──────────────────────────────────────────────────────────────


class TestEnforceTotalBlockLock:
    def test_not_active_passes(self) -> None:
        with patch(f"{PKG}.is_total_block_active", return_value=False):
            _enforce_total_block_lock("scan")  # no exit

    def test_exempt_command_passes_while_active(self) -> None:
        with patch(f"{PKG}.is_total_block_active", return_value=True):
            _enforce_total_block_lock("status")  # no exit
            _enforce_total_block_lock("enforce")  # no exit

    def test_blocked_command_exits(self) -> None:
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.get_total_block_status", return_value=_ACTIVE_STATUS),
            patch(f"{PKG}._show_total_block_lock_message"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _enforce_total_block_lock("scan")
        assert exc_info.value.code == 1

    def test_done_blocked_while_active(self) -> None:
        """Stricter than the manual-pick lock: even 'done' is blocked."""
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.get_total_block_status", return_value=_ACTIVE_STATUS),
            patch(f"{PKG}._show_total_block_lock_message"),
            pytest.raises(SystemExit),
        ):
            _enforce_total_block_lock("done")

    def test_add_exception_blocked_while_active(self) -> None:
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.get_total_block_status", return_value=_ACTIVE_STATUS),
            patch(f"{PKG}._show_total_block_lock_message"),
            pytest.raises(SystemExit),
        ):
            _enforce_total_block_lock("add-exception")

    def test_exempt_set_is_stricter_than_manual_pick(self) -> None:
        assert frozenset({"status", "enforce"}) == _TOTAL_BLOCK_EXEMPT_COMMANDS


# ──────────────────────────────────────────────────────────────
# cmd_block_gaming
# ──────────────────────────────────────────────────────────────


class TestCmdBlockGaming:
    def test_no_args_shows_usage(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo, pytest.raises(SystemExit) as exc_info:
            cmd_block_gaming([])
        assert exc_info.value.code == 1
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Usage" in output

    def test_non_numeric_days(self) -> None:
        with patch(f"{PKG}._echo"), pytest.raises(SystemExit):
            cmd_block_gaming(["abc"])

    def test_zero_days_rejected(self) -> None:
        with patch(f"{PKG}._echo"), pytest.raises(SystemExit):
            cmd_block_gaming(["0"])

    def test_negative_days_rejected(self) -> None:
        with patch(f"{PKG}._echo"), pytest.raises(SystemExit):
            cmd_block_gaming(["-1"])

    def test_aborted_when_not_yes(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="no"),
            patch(f"{PKG}.start_total_block") as mock_start,
        ):
            cmd_block_gaming(["14"])
        mock_start.assert_not_called()

    def test_confirmed_starts_block(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch(f"{PKG}.start_total_block", return_value=True) as mock_start,
        ):
            cmd_block_gaming(["14"])
        mock_start.assert_called_once_with(14)

    def test_start_failure_exits_nonzero(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch(f"{PKG}.start_total_block", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_block_gaming(["14"])
        assert exc_info.value.code == 1


# ──────────────────────────────────────────────────────────────
# main() dispatch to block-gaming
# ──────────────────────────────────────────────────────────────


class TestMainDispatchBlockGaming:
    def test_dispatches_block_gaming(self) -> None:
        argv = ["prog", "block-gaming", "14"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(f"{PKG}.is_total_block_active", return_value=False),
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
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.get_total_block_status", return_value=_ACTIVE_STATUS),
            patch(f"{PKG}._show_total_block_lock_message"),
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
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            main()  # must not raise SystemExit
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Steam Backlog Enforcer" in output


# ──────────────────────────────────────────────────────────────
# cmd_status shows total block info
# ──────────────────────────────────────────────────────────────


class TestCmdStatusTotalBlock:
    def test_shows_total_block_when_active(self) -> None:
        with (
            patch(f"{PKG}.get_total_block_status", return_value=_ACTIVE_STATUS),
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_status(Config(), State())
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "TOTAL GAMING BLOCK ACTIVE" in output
        assert "Days remaining" in output

    def test_no_total_block_section_when_inactive(self) -> None:
        with (
            patch(f"{PKG}.get_total_block_status", return_value=_INACTIVE_STATUS),
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_status(Config(), State())
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "TOTAL GAMING BLOCK" not in output

    def test_active_without_until_skips_remaining_time(self) -> None:
        status = TotalBlockStatus(
            active=True, started_at=None, until=None, days=1, days_remaining=0.5
        )
        with (
            patch(f"{PKG}.get_total_block_status", return_value=status),
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_status(Config(), State())
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "TOTAL GAMING BLOCK ACTIVE" in output
        assert "Days remaining" not in output
