"""Tests for the main CLI: shared lock helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer._total_block import TotalBlockStatus
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.main import (
    _TOTAL_BLOCK_EXEMPT_COMMANDS,
    _enforce_manual_pick_lock,
    _enforce_total_block_lock,
    _is_manual_pick_locked,
    _show_manual_pick_lock_message,
    _show_total_block_lock_message,
)
from steam_backlog_enforcer.tests._main_helpers import (
    ACTIVE_STATUS,
    EXPIRED_AT,
    STARTED_AT,
    locked_state,
)

PKG = "steam_backlog_enforcer.main._shared"


class TestIsManualPickLocked:
    """_is_manual_pick_locked holds until the game is done or the deadline passes."""

    def test_no_manual_pick_not_locked(self) -> None:
        """No manual pick means no lock."""
        assert _is_manual_pick_locked(State()) is False

    def test_game_finished_not_locked(self) -> None:
        """A finished pick releases the lock."""
        state = locked_state(app_id=100)
        state.finished_app_ids = [100]
        assert _is_manual_pick_locked(state) is False

    def test_deadline_passed_not_locked(self) -> None:
        """A passed deadline releases the lock."""
        state = locked_state(started_at=EXPIRED_AT)
        assert _is_manual_pick_locked(state) is False

    def test_active_lock_returns_true(self) -> None:
        """A recent unfinished pick is locked."""
        state = locked_state(started_at=STARTED_AT)
        assert _is_manual_pick_locked(state) is True

    def test_no_started_at_stays_locked(self) -> None:
        """A missing start time keeps the lock."""
        # Missing timestamp → cannot determine deadline → stays locked.
        state = locked_state(started_at="")
        assert _is_manual_pick_locked(state) is True

    def test_invalid_started_at_stays_locked(self) -> None:
        """An unparsable start time keeps the lock."""
        state = locked_state(started_at="not-a-date")
        assert _is_manual_pick_locked(state) is True


# ──────────────────────────────────────────────────────────────
# _show_manual_pick_lock_message
# ──────────────────────────────────────────────────────────────


class TestShowManualPickLockMessage:
    """The manual-pick lock message names the game and deadline."""

    def test_shows_game_info(self) -> None:
        """The message names the game and its id."""
        state = locked_state(app_id=42, name="MyGame", started_at=STARTED_AT)
        with patch(f"{PKG}._echo") as mock_echo:
            _show_manual_pick_lock_message(state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "MyGame" in output
        assert "42" in output

    def test_shows_deadline_when_started_at_valid(self) -> None:
        """A valid start time adds the deadline."""
        state = locked_state(started_at=STARTED_AT)
        with patch(f"{PKG}._echo") as mock_echo:
            _show_manual_pick_lock_message(state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Deadline" in output

    def test_no_crash_on_invalid_started_at(self) -> None:
        """An invalid start time does not crash the message."""
        state = locked_state(started_at="bad-date")
        with patch(f"{PKG}._echo"):
            _show_manual_pick_lock_message(state)  # must not raise

    def test_no_crash_on_empty_started_at(self) -> None:
        """An empty start time does not crash the message."""
        state = locked_state(started_at="")
        with patch(f"{PKG}._echo"):
            _show_manual_pick_lock_message(state)  # must not raise


# ──────────────────────────────────────────────────────────────
# _enforce_manual_pick_lock
# ──────────────────────────────────────────────────────────────


class TestEnforceManualPickLock:
    """_enforce_manual_pick_lock exits on blocked commands only."""

    def test_no_lock_passes(self) -> None:
        """Without a lock every command passes."""
        _enforce_manual_pick_lock("scan", State())  # no exit

    def test_exempt_command_passes_while_locked(self) -> None:
        """Exempt commands pass while locked."""
        state = locked_state()
        _enforce_manual_pick_lock("done", state)  # no exit
        _enforce_manual_pick_lock("status", state)  # no exit

    def test_blocked_command_exits(self) -> None:
        """A blocked command exits while locked."""
        state = locked_state()
        with (
            patch(f"{PKG}._show_manual_pick_lock_message"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _enforce_manual_pick_lock("scan", state)
        assert exc_info.value.code == 1

    def test_add_exception_blocked_when_locked(self) -> None:
        """add-exception is blocked while locked."""
        state = locked_state()
        with (
            patch(f"{PKG}._show_manual_pick_lock_message"),
            pytest.raises(SystemExit),
        ):
            _enforce_manual_pick_lock("add-exception", state)

    def test_pick_manual_allowed_when_already_locked(self) -> None:
        """pick-manual stays reachable while locked."""
        # A second pick must be reachable while the first holds the lock; the
        # cap inside cmd_pick_manual is what limits it, not the lock check.
        _enforce_manual_pick_lock("pick-manual", locked_state())


# ──────────────────────────────────────────────────────────────
# _resolve_game_name
# ──────────────────────────────────────────────────────────────


class TestShowTotalBlockLockMessage:
    """The total-block message shows the time left and exempt commands."""

    def test_shows_remaining_time(self) -> None:
        """The message shows the banner and the time left."""
        with patch(f"{PKG}._echo") as mock_echo:
            _show_total_block_lock_message(ACTIVE_STATUS)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "TOTAL GAMING BLOCK ACTIVE" in output
        assert "Time remaining: 23h 2m" in output

    def test_lists_exempt_commands(self) -> None:
        """The message lists the exempt commands."""
        with patch(f"{PKG}._echo") as mock_echo:
            _show_total_block_lock_message(ACTIVE_STATUS)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "status" in output
        assert "enforce" in output

    def test_no_crash_without_until(self) -> None:
        """A block without an end time does not crash the message."""
        status = TotalBlockStatus(
            active=True, started_at=None, until=None, days=1, days_remaining=0.5
        )
        with patch(f"{PKG}._echo"):
            _show_total_block_lock_message(status)  # must not raise


# ──────────────────────────────────────────────────────────────
# _enforce_total_block_lock
# ──────────────────────────────────────────────────────────────


class TestEnforceTotalBlockLock:
    """_enforce_total_block_lock exits on blocked commands while active."""

    def test_not_active_passes(self) -> None:
        """Without an active block every command passes."""
        with patch(f"{PKG}.is_total_block_active", return_value=False):
            _enforce_total_block_lock("scan")  # no exit

    def test_exempt_command_passes_while_active(self) -> None:
        """Exempt commands pass during a block."""
        with patch(f"{PKG}.is_total_block_active", return_value=True):
            _enforce_total_block_lock("status")  # no exit
            _enforce_total_block_lock("enforce")  # no exit

    def test_blocked_command_exits(self) -> None:
        """A blocked command exits during a block."""
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.get_total_block_status", return_value=ACTIVE_STATUS),
            patch(f"{PKG}._show_total_block_lock_message"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _enforce_total_block_lock("scan")
        assert exc_info.value.code == 1

    def test_done_blocked_while_active(self) -> None:
        """Stricter than the manual-pick lock: even 'done' is blocked."""
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.get_total_block_status", return_value=ACTIVE_STATUS),
            patch(f"{PKG}._show_total_block_lock_message"),
            pytest.raises(SystemExit),
        ):
            _enforce_total_block_lock("done")

    def test_add_exception_blocked_while_active(self) -> None:
        """add-exception is blocked during a block."""
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.get_total_block_status", return_value=ACTIVE_STATUS),
            patch(f"{PKG}._show_total_block_lock_message"),
            pytest.raises(SystemExit),
        ):
            _enforce_total_block_lock("add-exception")

    def test_exempt_set_is_stricter_than_manual_pick(self) -> None:
        """Pinned exactly: widening this set weakens the total block.

        gaming-unblock is present because a playtime bind mount makes the
        total block's own `pacman -R steam` fail EBUSY - it has to stay
        reachable exactly when the two collide. gaming-reset is deliberately
        absent: it would shorten enforcement. serve changes nothing itself
        (each job it starts is lock-checked); refusing it took the web UI down.
        """
        assert (
            frozenset({"status", "enforce", "gaming-status", "gaming-unblock", "serve"})
            | {"total-block-refresh"}  # reconciles the list; cannot shorten the lock
            | {"total-block-research"}  # once per lock, Librarian only
            == _TOTAL_BLOCK_EXEMPT_COMMANDS
        )
        assert "gaming-reset" not in _TOTAL_BLOCK_EXEMPT_COMMANDS


# ──────────────────────────────────────────────────────────────
# cmd_block_gaming
# ──────────────────────────────────────────────────────────────
