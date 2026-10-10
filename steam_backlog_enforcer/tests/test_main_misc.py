"""Tests for the main CLI: store, reset, setup, exception and block-gaming commands."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._store_window import DEFAULT_WINDOW_MINUTES
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_buy_dlc,
    cmd_reset,
    cmd_setup,
    cmd_unblock,
)

PKG = "steam_backlog_enforcer.main.misc"
_UNTIL = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
_FIVE_MINUTES = 5


class TestCmdUnblock:
    """Tests for cmd_unblock: it opens a timed store window."""

    def test_default_window(self) -> None:
        with (
            patch(f"{PKG}.open_store_window", return_value=_UNTIL) as mock_open,
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_unblock(Config(), State())
        assert mock_open.call_args.args[1] == DEFAULT_WINDOW_MINUTES
        assert any("UNBLOCKED until" in str(c) for c in mock_echo.call_args_list)

    def test_explicit_minutes(self) -> None:
        with (
            patch(f"{PKG}.open_store_window", return_value=_UNTIL) as mock_open,
            patch(f"{PKG}._echo"),
        ):
            cmd_unblock(Config(), State(), ["5"])
        assert mock_open.call_args.args[1] == _FIVE_MINUTES

    @pytest.mark.parametrize("raw", ["abc", "0", "31"])
    def test_bad_minutes_exits(self, raw: str) -> None:
        with (
            patch(f"{PKG}._echo") as mock_echo,
            pytest.raises(SystemExit),
        ):
            cmd_unblock(Config(), State(), [raw])
        assert any("Usage" in str(c) for c in mock_echo.call_args_list)

    def test_unblock_failure_exits(self) -> None:
        with (
            patch(f"{PKG}.open_store_window", side_effect=RuntimeError("sudo?")),
            patch(f"{PKG}._echo") as mock_echo,
            pytest.raises(SystemExit),
        ):
            cmd_unblock(Config(), State())
        assert any("Failed" in str(c) for c in mock_echo.call_args_list)


class TestCmdBuyDlc:
    """cmd_buy_dlc is the default-length window, assigned game or not."""

    def test_opens_default_window(self) -> None:
        with (
            patch(f"{PKG}.open_store_window", return_value=_UNTIL) as mock_open,
            patch(f"{PKG}._echo"),
        ):
            cmd_buy_dlc(Config(), State())
        assert mock_open.call_args.args[1] == DEFAULT_WINDOW_MINUTES


_RESET_PHRASE = "wipe all enforcer state"


def _reset(
    state: State,
    owned: object,
    *,
    typed: str = _RESET_PHRASE,
    unhidden: int = 2,
) -> list[str]:
    """Run ``cmd_reset`` with *typed* as the answer; return what it printed."""
    with (
        patch("builtins.input", return_value=typed),
        patch(f"{PKG}.get_all_owned_app_ids", side_effect=owned)
        if isinstance(owned, Exception)
        else patch(f"{PKG}.get_all_owned_app_ids", return_value=owned),
        patch(f"{PKG}.unhide_all_games", return_value=unhidden),
        patch(f"{PKG}._echo") as mock_echo,
        patch.object(State, "save"),
    ):
        cmd_reset(Config(), state)
    return [str(c.args[0]) for c in mock_echo.call_args_list if c.args]


class TestCmdReset:
    """Tests for cmd_reset."""

    def test_normal_reset(self) -> None:
        state = State(current_app_id=1, current_game_name="G", finished_app_ids=[1])
        printed = _reset(state, [1, 2])
        assert state.current_app_id is None
        assert state.finished_app_ids == []
        assert "Unhidden 2 games." in printed

    def test_leaves_the_store_blocked(self) -> None:
        """Reset no longer lifts the store block: that needs ``unblock``."""
        printed = _reset(State(current_app_id=1), [])
        assert any("Store left blocked" in line for line in printed)

    def test_wrong_phrase_aborts_and_keeps_state(self) -> None:
        state = State(current_app_id=1)
        printed = _reset(state, [1], typed="yes")
        assert printed == ["Aborted."]
        assert state.current_app_id == 1

    def test_reports_the_backup_it_took(self) -> None:
        backup = MagicMock(id="20261010T000000Z-abcdef")
        with patch(f"{PKG}.create_backup", return_value=backup):
            printed = _reset(State(), [])
        assert "State backed up as 20261010T000000Z-abcdef." in printed

    def test_unhide_fails(self) -> None:
        state = State(current_app_id=1)
        printed = _reset(state, OSError("fail"))
        assert any("could not unhide games: fail" in line for line in printed)
        assert state.current_app_id is None

    def test_unhide_returns_zero(self) -> None:
        state = State(current_app_id=1)
        printed = _reset(state, [1, 2], unhidden=0)
        assert not any("Unhidden" in line for line in printed)


class TestCmdSetup:
    """Tests for cmd_setup."""

    def test_calls_interactive(self) -> None:
        with patch(f"{PKG}.interactive_setup") as mock_setup:
            cmd_setup(Config(), State())
            mock_setup.assert_called_once()
