"""Tests for the main CLI: pick-manual slot cap."""

from unittest.mock import patch

import pytest

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_pick_manual,
)
from steam_backlog_enforcer.tests._main_helpers import (
    locked_state,
    two_pick_state,
)

PKG = "steam_backlog_enforcer.main.picks"


class TestPickManualCap:
    def test_second_pick_is_added_not_replacing(self) -> None:
        state = locked_state(app_id=100)
        with (
            patch(f"{PKG}._echo"),
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        assert [p["app_id"] for p in state.manual_picks] == [100, 489830]

    def test_third_pick_refused_at_cap(self) -> None:
        state = two_pick_state()
        with (
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
        # The cap has room, so this exercises the core's own refusal path.
        state = locked_state(app_id=489830)
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            pytest.raises(SystemExit),
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        assert "already one of your manual picks" in " ".join(
            str(c) for c in mock_echo.call_args_list
        )

    def test_cascade_keeps_every_allowed_game(self) -> None:
        # The regression this whole feature turns on: adding a second pick must
        # not uninstall or hide the first.
        state = locked_state(app_id=100)
        with (
            patch(f"{PKG}._echo"),
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0) as mock_uninstall,
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 100, 489830]),
            patch(f"{PKG}.try_hide_other_games", return_value=(1, None)) as mock_hide,
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        mock_uninstall.assert_called_once_with({100, 489830})
        mock_hide.assert_called_once_with([1, 100, 489830], {100, 489830})

    def test_installs_every_missing_allowed_game(self) -> None:
        state = locked_state(app_id=100)
        with (
            patch(f"{PKG}._echo"),
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch(f"{PKG}.install_game") as mock_install,
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick_manual(Config(max_manual_picks=2), state, ["489830"])
        installed = {call.args[0] for call in mock_install.call_args_list}
        assert installed == {100, 489830}
