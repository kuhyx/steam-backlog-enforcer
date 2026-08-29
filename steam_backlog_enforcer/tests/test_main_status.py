"""Tests for the main CLI: status and list commands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from steam_backlog_enforcer._total_block import TotalBlockStatus
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_list,
    cmd_status,
)
from steam_backlog_enforcer.tests._main_helpers import (
    ACTIVE_STATUS,
    INACTIVE_STATUS,
    locked_state,
    snap,
)

PKG = "steam_backlog_enforcer.main.status"


class TestCmdStatus:
    """Tests for cmd_status."""

    def test_with_game(self) -> None:
        state = State(current_app_id=440, current_game_name="TF2")
        with (
            patch(f"{PKG}.is_store_blocked", return_value=True),
            patch(f"{PKG}.get_installed_games", return_value=[(440, "TF2")]),
            patch(f"{PKG}._echo"),
        ):
            cmd_status(Config(), state)

    def test_no_game(self) -> None:
        with (
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo"),
        ):
            cmd_status(Config(), State())


class TestCmdList:
    """Tests for cmd_list."""

    def test_no_snapshot(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=None),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_list(Config(), State())
            assert any("No snapshot" in str(c) for c in mock_echo.call_args_list)

    def test_with_games(self) -> None:
        snapshot = [
            snap(1, "A", 10, 5, 20.0),
            snap(2, "B", 10, 10, 10.0),
            snap(3, "C", 10, 3, -1),
        ]
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}._echo"),
        ):
            cmd_list(Config(), state)

    def test_many_games(self) -> None:
        snapshot = [snap(i, f"Game{i}") for i in range(60)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_list(Config(), State())
            assert any("more" in str(c) for c in mock_echo.call_args_list)


class TestCmdStatusLockHint:
    def test_shows_lock_hint_when_locked(self) -> None:
        state = locked_state()
        with (
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_status(Config(), state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "MANUAL PICK LOCK" in output

    def test_no_lock_hint_when_not_locked(self) -> None:
        with (
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_status(Config(), State())
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "MANUAL PICK LOCK" not in output


# ──────────────────────────────────────────────────────────────
# cmd_abandon_pick (grace period escape hatch)
# ──────────────────────────────────────────────────────────────

# A pick made yesterday / one made over a week ago. Both are abandonable.
_RECENT_PICK = (datetime.now(UTC) - timedelta(days=1)).isoformat()


def _abandonable_state(app_id: int = 100, started_at: str = _RECENT_PICK) -> State:
    state = locked_state(app_id=app_id, started_at=started_at)
    state.current_app_id = app_id
    state.current_game_name = state.manual_pick_game_name
    return state


class TestCmdStatusTotalBlock:
    def test_shows_total_block_when_active(self) -> None:
        with (
            patch(f"{PKG}.get_total_block_status", return_value=ACTIVE_STATUS),
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
            patch(f"{PKG}.get_total_block_status", return_value=INACTIVE_STATUS),
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


# ──────────────────────────────────────────────────────────────
# main() dispatch to the daily-gaming-budget commands
# ──────────────────────────────────────────────────────────────
