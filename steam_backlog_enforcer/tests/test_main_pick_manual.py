"""Tests for the main CLI: pick-manual command."""

from unittest.mock import patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_pick_manual,
)
from steam_backlog_enforcer.tests._main_patches import HIDE_OTHERS, confirmed_pick

PKG = "steam_backlog_enforcer.main.picks"


class TestCmdPickManual:
    """cmd_pick_manual validates the id, confirms, then locks the pick in."""

    def test_invalid_app_id(self) -> None:
        """A non-numeric app id prints an error."""
        with patch(f"{PKG}._echo") as mock_echo:
            cmd_pick_manual(Config(), State(), ["abc"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Error" in output

    def test_game_not_found(self) -> None:
        """An app id with no resolvable name reports not found."""
        with (
            patch(f"{PKG}._resolve_game_name", return_value=None),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_pick_manual(Config(), State(), ["489830"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "not found" in output

    def test_aborted_when_not_yes(self) -> None:
        """Any answer other than the lock-in phrase aborts without saving."""
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="no"),
            patch("steam_backlog_enforcer.config.State.save") as mock_save,
        ):
            cmd_pick_manual(Config(), State(), ["489830"])
        mock_save.assert_not_called()

    def test_prompts_for_id_when_no_args(self) -> None:
        """With no args the app id is asked for interactively."""
        state = State()
        with confirmed_pick(answers=["489830", "lock in Skyrim SE"]):
            cmd_pick_manual(Config(), state, [])
        assert state.current_app_id == 489830

    def test_success_sets_state_and_runs_post_steps(self) -> None:
        """A confirmed pick is recorded and uninstall, install and hide all run."""
        state = State()
        config = Config(uninstall_other_games=True)
        with (
            confirmed_pick(owned=[1, 489830], installed=False, uninstall=2) as mocks,
            patch(f"{PKG}.install_game") as mock_install,
            patch(HIDE_OTHERS, return_value=(1, None)) as mock_hide,
        ):
            cmd_pick_manual(config, state, ["489830"])

        assert [p["app_id"] for p in state.manual_picks] == [489830]
        assert state.manual_picks[0]["game_name"] == "Skyrim SE"
        assert state.manual_picks[0]["started_at"] != ""
        assert state.current_app_id == 489830
        mocks["save"].assert_called_once()
        mocks["uninstall"].assert_called_once_with({489830})
        mock_install.assert_called_once()
        mock_hide.assert_called_once()

    def test_enforcement_started_at_set_when_empty(self) -> None:
        """A confirmed pick stamps enforcement_started_at when it is empty."""
        state = State(enforcement_started_at="")
        with confirmed_pick():
            cmd_pick_manual(Config(), state, ["489830"])
        assert state.enforcement_started_at != ""

    def test_enforcement_started_at_not_overwritten(self) -> None:
        """A confirmed pick keeps an existing enforcement_started_at."""
        existing_ts = "2026-01-01T00:00:00+00:00"
        state = State(enforcement_started_at=existing_ts)
        with confirmed_pick():
            cmd_pick_manual(Config(), state, ["489830"])
        assert state.enforcement_started_at == existing_ts
