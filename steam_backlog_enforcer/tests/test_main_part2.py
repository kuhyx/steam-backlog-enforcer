"""Tests for main CLI module — part 2 (missing coverage)."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from python_pkg.steam_backlog_enforcer._cmd_done import (
    _enforce_on_done,
    _finalize_completion,
    cmd_done,
)
from python_pkg.steam_backlog_enforcer.config import Config, State
from python_pkg.steam_backlog_enforcer.main import main
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "python_pkg.steam_backlog_enforcer._cmd_done"
PKG = "python_pkg.steam_backlog_enforcer.main"


def _snap(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 0,
    hours: float = -1,
) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "name": name,
        "total_achievements": total,
        "unlocked_achievements": unlocked,
        "playtime_minutes": 60,
        "completionist_hours": hours,
    }


class TestFinalizeCompletion:
    """Tests for _finalize_completion."""

    def test_with_snapshot_and_hiding(self) -> None:
        config = Config(steam_api_key="k", steam_id="i")
        state = State(current_app_id=1, current_game_name="G")
        snap = [_snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(f"{CMD_DONE_PKG}.hide_other_games", return_value=2),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):

            def set_next(
                _games: object,
                s: State,
                _c: object,
            ) -> None:
                s.current_app_id = 2
                s.current_game_name = "NewGame"

            mock_pick.side_effect = set_next
            _finalize_completion(config, state, "G", 1)
        assert 1 in state.finished_app_ids

    def test_no_snapshot(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=None),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, "G", 1)
        assert state.current_app_id is None

    def test_no_next_game(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snap = [_snap(1, "G", 10, 10)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch.object(State, "save"),
        ):

            def set_none(
                _games: object,
                s: State,
                _c: object,
            ) -> None:
                s.current_app_id = None

            mock_pick.side_effect = set_none
            _finalize_completion(config, state, "G", 1)

    def test_no_owned_ids(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snap = [_snap(2, "Next", 10, 0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):

            def set_2(
                _games: object,
                s: State,
                _c: object,
            ) -> None:
                s.current_app_id = 2
                s.current_game_name = "Next"

            mock_pick.side_effect = set_2
            _finalize_completion(config, state, "G", 1)

    def test_hide_returns_zero(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snap = [_snap(2, "Next", 10, 0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{CMD_DONE_PKG}.hide_other_games", return_value=0),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):

            def set_2(
                _games: object,
                s: State,
                _c: object,
            ) -> None:
                s.current_app_id = 2
                s.current_game_name = "Next"

            mock_pick.side_effect = set_2
            _finalize_completion(config, state, "G", 1)

    def test_refreshes_snapshot_hours_before_pick(self) -> None:
        """Ensure stale snapshot hours are replaced before picking next game."""
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snap = [
            _snap(2, "A Space for the Unbound", 10, 0, 0.56),
            _snap(3, "Lacuna", 10, 0, 1.2),
        ]
        seen: dict[int, float] = {}

        def capture_pick(
            games: list[GameInfo],
            s: State,
            _c: object,
        ) -> None:
            for game in games:
                seen[game.app_id] = game.completionist_hours
            # Force early return path after pick_next_game.
            s.current_app_id = None

        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={2: 20.05}),
            patch(
                f"{CMD_DONE_PKG}.fetch_hltb_times_cached",
                return_value={3: 18.81},
            ) as mock_fetch_hltb,
            patch(f"{CMD_DONE_PKG}.pick_next_game", side_effect=capture_pick),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, "G", 1)

        assert seen[2] == 20.05
        assert seen[3] == 18.81
        mock_fetch_hltb.assert_called_once_with([(3, "Lacuna")])


class TestEnforceOnDone:
    """Tests for _enforce_on_done."""

    def test_no_current_game(self) -> None:
        _enforce_on_done(Config(), State())

    def test_kills_and_uninstalls(self) -> None:
        config = Config(
            kill_unauthorized_games=True,
            uninstall_other_games=True,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(
                f"{CMD_DONE_PKG}.enforce_allowed_game",
                return_value=[(1234, 999)],
            ),
            patch(f"{CMD_DONE_PKG}.uninstall_other_games", return_value=2),
            patch(f"{CMD_DONE_PKG}.is_game_installed", return_value=True),
        ):
            _enforce_on_done(config, state)

    def test_no_violations_no_uninstalls(self) -> None:
        config = Config(
            kill_unauthorized_games=True,
            uninstall_other_games=True,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.enforce_allowed_game", return_value=[]),
            patch(f"{CMD_DONE_PKG}.uninstall_other_games", return_value=0),
            patch(f"{CMD_DONE_PKG}.is_game_installed", return_value=True),
        ):
            _enforce_on_done(config, state)

    def test_reinstall_when_not_installed(self) -> None:
        config = Config(
            kill_unauthorized_games=False,
            uninstall_other_games=False,
            steam_id="s1",
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.is_game_installed", return_value=False),
            patch(f"{CMD_DONE_PKG}.install_game") as mock_install,
        ):
            _enforce_on_done(config, state)
        mock_install.assert_called_once_with(1, "G", "s1", use_steam_protocol=True)


class TestCmdDone:
    """Tests for cmd_done."""

    def test_no_game_assigned(self) -> None:
        with patch(f"{CMD_DONE_PKG}._echo") as mock_echo:
            cmd_done(Config(), State())
        assert any("No game" in str(c) for c in mock_echo.call_args_list)

    def test_fetch_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = None
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_not_complete_enforces(self) -> None:
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={1: 20.0}),
            patch(f"{CMD_DONE_PKG}._try_reassign_shorter_game", return_value=False),
            patch(f"{CMD_DONE_PKG}._enforce_on_done"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_complete_finalizes(self) -> None:
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=10,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={1: 10.0}),
            patch(f"{CMD_DONE_PKG}._try_reassign_shorter_game", return_value=False),
            patch(f"{CMD_DONE_PKG}._finalize_completion") as mock_final,
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)
        mock_final.assert_called_once()

    def test_hltb_cache_miss_fetches(self) -> None:
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={}),
            patch(
                f"{CMD_DONE_PKG}.fetch_hltb_times_cached",
                return_value={1: 15.0},
            ),
            patch(f"{CMD_DONE_PKG}._try_reassign_shorter_game", return_value=False),
            patch(f"{CMD_DONE_PKG}._enforce_on_done"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_hltb_negative_no_display(self) -> None:
        """Covers the hours <= 0 branch (no HLTB estimate display)."""
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={1: -1.0}),
            patch(f"{CMD_DONE_PKG}._try_reassign_shorter_game", return_value=False),
            patch(f"{CMD_DONE_PKG}._enforce_on_done"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_reassign_returns_true(self) -> None:
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={1: 50.0}),
            patch(f"{CMD_DONE_PKG}._try_reassign_shorter_game", return_value=True),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)


class TestMain:
    """Tests for main CLI entry point."""

    def test_no_args_exits(self) -> None:
        with (
            patch.object(sys, "argv", ["prog"]),
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_unknown_command_exits(self) -> None:
        with (
            patch.object(sys, "argv", ["prog", "bogus"]),
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_valid_command_runs(self) -> None:
        mock_cmd = MagicMock()
        with (
            patch.object(sys, "argv", ["prog", "status"]),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch.dict(f"{PKG}.COMMANDS", {"status": ("s", mock_cmd)}),
        ):
            main()
        mock_cmd.assert_called_once()

    def test_setup_no_key_required(self) -> None:
        mock_cmd = MagicMock()
        with (
            patch.object(sys, "argv", ["prog", "setup"]),
            patch(f"{PKG}.Config.load", return_value=Config()),
            patch(f"{PKG}.State.load", return_value=State()),
            patch.dict(f"{PKG}.COMMANDS", {"setup": ("s", mock_cmd)}),
        ):
            main()
        mock_cmd.assert_called_once()

    def test_no_api_key_exits(self) -> None:
        with (
            patch.object(sys, "argv", ["prog", "status"]),
            patch(f"{PKG}.Config.load", return_value=Config()),
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()
