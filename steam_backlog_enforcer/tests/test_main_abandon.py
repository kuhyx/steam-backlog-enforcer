"""Tests for the main CLI: abandon-pick command."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    _enforce_manual_pick_lock,
    _show_manual_pick_lock_message,
    cmd_abandon_pick,
    cmd_status,
    main,
)
from steam_backlog_enforcer.tests._main_helpers import (
    OLD_PICK,
    RECENT_PICK,
    abandonable_state,
    locked_state,
    two_pick_state,
)

PKG = "steam_backlog_enforcer.main.abandon"


class TestCmdAbandonPick:
    def test_no_args_exits(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo, pytest.raises(SystemExit) as exc:
            cmd_abandon_pick(Config(), abandonable_state(), [])
        assert exc.value.code == 1
        assert "Usage" in " ".join(str(c) for c in mock_echo.call_args_list)

    def test_non_numeric_app_id_exits(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo, pytest.raises(SystemExit):
            cmd_abandon_pick(Config(), abandonable_state(), ["abc"])
        assert "must be a number" in " ".join(str(c) for c in mock_echo.call_args_list)

    def test_no_active_pick_exits(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo, pytest.raises(SystemExit):
            cmd_abandon_pick(Config(), State(), ["100"])
        assert "No manual pick" in " ".join(str(c) for c in mock_echo.call_args_list)

    def test_wrong_app_id_exits(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo, pytest.raises(SystemExit):
            cmd_abandon_pick(Config(), abandonable_state(app_id=100), ["999"])
        assert "not one of your manual picks" in " ".join(
            str(c) for c in mock_echo.call_args_list
        )

    def test_old_pick_can_still_be_abandoned(self) -> None:
        """A pick has no grace window: however old, it can be abandoned."""
        state = abandonable_state(started_at=OLD_PICK)
        with (
            patch(f"{PKG}._echo"),
            patch(f"{PKG}.input", return_value="YES"),
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch.object(State, "save"),
        ):
            cmd_abandon_pick(Config(), state, ["100"])
        assert state.manual_picks == []

    def test_bad_timestamp_pick_can_still_be_abandoned(self) -> None:
        """An unparsable started_at does not block abandoning."""
        state = abandonable_state(started_at="not-a-date")
        with (
            patch(f"{PKG}._echo"),
            patch(f"{PKG}.input", return_value="YES"),
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch.object(State, "save"),
        ):
            cmd_abandon_pick(Config(), state, ["100"])
        assert state.manual_picks == []

    def test_aborted_when_not_yes(self) -> None:
        state = abandonable_state()
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="no"),
            patch.object(State, "save") as mock_save,
            patch(f"{PKG}.uninstall_game") as mock_uninstall,
        ):
            cmd_abandon_pick(Config(), state, ["100"])
        mock_save.assert_not_called()
        mock_uninstall.assert_not_called()
        assert [p["app_id"] for p in state.manual_picks] == [100]

    def test_success_clears_lock_and_uninstalls(self) -> None:
        state = abandonable_state()
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.uninstall_game", return_value=True) as mock_uninstall,
        ):
            cmd_abandon_pick(Config(), state, ["100"])
        assert state.manual_picks == []
        assert state.current_app_id is None
        assert state.skipped_until["100"] != ""
        mock_uninstall.assert_called_once_with(100, "TestGame")
        assert "abandoned" in " ".join(str(c) for c in mock_echo.call_args_list)

    def test_skips_uninstall_when_not_installed(self) -> None:
        state = abandonable_state()
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch(f"{PKG}.uninstall_game") as mock_uninstall,
        ):
            cmd_abandon_pick(Config(), state, ["100"])
        mock_uninstall.assert_not_called()

    def test_warns_when_uninstall_fails(self) -> None:
        state = abandonable_state()
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.uninstall_game", return_value=False),
        ):
            cmd_abandon_pick(Config(), state, ["100"])
        assert "Warning" in " ".join(str(c) for c in mock_echo.call_args_list)


class TestAbandonPickLockInteraction:
    def test_abandon_pick_is_exempt_from_the_lock(self) -> None:
        # The escape hatch must survive the pre-dispatch lock check.
        _enforce_manual_pick_lock("abandon-pick", locked_state())

    def test_main_dispatches_abandon_pick_while_locked(self) -> None:
        argv = ["prog", "abandon-pick", "100"]
        with (
            patch.object(sys, "argv", argv),
            patch(
                "steam_backlog_enforcer.main.Config.load",
                return_value=Config(steam_api_key="k"),
            ),
            patch(
                "steam_backlog_enforcer.main.State.load",
                return_value=abandonable_state(),
            ),
            patch("steam_backlog_enforcer.main.cmd_abandon_pick") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once()

    def test_lock_message_advertises_abandon(self) -> None:
        state = abandonable_state(started_at=RECENT_PICK)
        with patch("steam_backlog_enforcer.main._shared._echo") as mock_echo:
            _show_manual_pick_lock_message(state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "abandon-pick 100" in output
        assert "day(s) ago" in output

    def test_lock_message_advertises_abandon_for_old_picks_too(self) -> None:
        state = abandonable_state(started_at=OLD_PICK)
        with patch("steam_backlog_enforcer.main._shared._echo") as mock_echo:
            _show_manual_pick_lock_message(state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "abandon-pick 100" in output


# ──────────────────────────────────────────────────────────────
# Two concurrent manual picks (cap, coexistence, per-pick abandon)
# ──────────────────────────────────────────────────────────────


class TestAbandonOneOfTwoPicks:
    def test_other_pick_survives(self) -> None:
        state = two_pick_state()
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.is_game_installed", return_value=False),
        ):
            cmd_abandon_pick(Config(), state, ["200"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "stay locked in: TestGame (AppID=100)" in output
        assert "Still assigned: TestGame" in output
        assert [p["app_id"] for p in state.manual_picks] == [100]
        assert state.current_app_id == 100

    def test_wrong_id_lists_all_active_picks(self) -> None:
        state = two_pick_state()
        with patch(f"{PKG}._echo") as mock_echo, pytest.raises(SystemExit):
            cmd_abandon_pick(Config(), state, ["999"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "TestGame (AppID=100)" in output
        assert "SecondGame (AppID=200)" in output

    def test_lock_message_lists_both_picks(self) -> None:
        with patch("steam_backlog_enforcer.main._shared._echo") as mock_echo:
            _show_manual_pick_lock_message(two_pick_state())
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "picked 2 game(s)" in output
        assert "abandon-pick 100" in output
        assert "abandon-pick 200" in output

    def test_status_lists_both_picks(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer.main.status.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.main.status.get_installed_games",
                return_value=[],
            ),
            patch(
                "steam_backlog_enforcer.main.status.report_completion",
                return_value=[],
            ),
            patch("steam_backlog_enforcer.main.status._echo") as mock_echo,
        ):
            cmd_status(Config(), two_pick_state())
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Manual picks (2)" in output
        assert "picked" in output
        assert "day(s) ago" in output

    def test_status_shows_age_for_old_picks(self) -> None:
        state = two_pick_state()
        state.manual_picks[0]["started_at"] = OLD_PICK
        state.manual_picks[1]["started_at"] = OLD_PICK
        with (
            patch(
                "steam_backlog_enforcer.main.status.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.main.status.get_installed_games",
                return_value=[],
            ),
            patch(
                "steam_backlog_enforcer.main.status.report_completion",
                return_value=[],
            ),
            patch("steam_backlog_enforcer.main.status._echo") as mock_echo,
        ):
            cmd_status(Config(), state)
        assert "picked 8.0 day(s) ago" in " ".join(
            str(c) for c in mock_echo.call_args_list
        )
