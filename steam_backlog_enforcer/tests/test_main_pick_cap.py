"""Tests for the main CLI: pick-manual slot cap."""

from unittest.mock import patch

import pytest

from steam_backlog_enforcer._pick_completion import PickProgress
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.main import (
    cmd_pick_manual,
)
from steam_backlog_enforcer.tests._main_helpers import (
    STARTED_AT,
    locked_state,
    two_pick_state,
)
from steam_backlog_enforcer.tests._main_patches import HIDE_OTHERS, confirmed_pick

PKG = "steam_backlog_enforcer.main.picks"


class TestPickManualCap:
    """pick-manual adds picks up to max_manual_picks and keeps every allowed game."""

    def test_second_pick_is_added_not_replacing(self) -> None:
        """A second pick joins the first instead of replacing it."""
        state = locked_state(app_id=100)
        with (
            patch(f"{PKG}.report_completion", return_value=[]),
            confirmed_pick(),
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        assert [p["app_id"] for p in state.manual_picks] == [100, 489830]

    def test_third_pick_refused_at_cap(self) -> None:
        """A pick beyond the cap exits 1 and lists the locked-in games."""
        state = two_pick_state()
        with (
            patch(f"{PKG}.report_completion", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            pytest.raises(SystemExit) as exc,
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        assert exc.value.code == 1
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "already have 2 manual pick(s)" in output
        assert "Already locked in (2/2)" in output
        assert len(state.manual_picks) == 2

    def test_duplicate_pick_refused_by_core(self) -> None:
        """Picking a game that is already a pick is refused."""
        # The cap has room, so this exercises the core's own refusal path.
        state = locked_state(app_id=489830)
        with (
            patch(f"{PKG}.report_completion", return_value=[]),
            confirmed_pick() as mocks,
            pytest.raises(SystemExit),
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        assert "already one of your manual picks" in " ".join(
            str(c) for c in mocks["echo"].call_args_list
        )

    def test_cascade_keeps_every_allowed_game(self) -> None:
        """Uninstall and hide spare every allowed game, old and new."""
        # The regression this whole feature turns on: adding a second pick must
        # not uninstall or hide the first.
        state = locked_state(app_id=100)
        with (
            patch(f"{PKG}.report_completion", return_value=[]),
            confirmed_pick(owned=[1, 100, 489830]) as mocks,
            patch(HIDE_OTHERS, return_value=(1, None)) as mock_hide,
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        mocks["uninstall"].assert_called_once_with({100, 489830})
        mock_hide.assert_called_once_with([1, 100, 489830], {100, 489830})

    def test_installs_every_missing_allowed_game(self) -> None:
        """Every allowed game that is not installed gets installed."""
        state = locked_state(app_id=100)
        with (
            patch(f"{PKG}.report_completion", return_value=[]),
            confirmed_pick(installed=False),
            patch(f"{PKG}.install_game") as mock_install,
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        installed = {call.args[0] for call in mock_install.call_args_list}
        assert installed == {100, 489830}


class TestPickManualRetirementNotices:
    """A pick retired by the sweep is announced before the typed-phrase prompt."""

    def test_lists_kept_games_and_stale_assignment(self) -> None:
        """Retired picks are listed as kept and a stale assignment is noted."""
        state = locked_state(app_id=100)
        state.current_app_id = 200
        state.current_game_name = "Finished"
        state.manual_picks.append(
            {
                "app_id": 200,
                "game_name": "Finished",
                "started_at": STARTED_AT,
                "released_at": STARTED_AT,
            }
        )
        retired = [PickProgress(200, "Finished", 5, 5, retired=True, determinable=True)]
        with (
            patch(f"{PKG}.report_completion", return_value=retired),
            patch(f"{PKG}._echo") as mock_echo,
            # warn_stale_assignment prints from the completion module.
            patch("steam_backlog_enforcer._pick_completion._echo") as mock_note,
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch("builtins.input", return_value="no"),
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        # The retired game is kept now, not replaced: it stays installed.
        assert "they stay installed: Finished, TestGame" in output
        assert "Aborted." in output
        # Abort leaves the finished game as the assignment, so say so.
        note = " ".join(str(c) for c in mock_note.call_args_list)
        assert "still" in note
