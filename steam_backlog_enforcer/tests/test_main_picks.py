"""Tests for the main CLI: pick and pick-manual commands."""

from unittest.mock import patch

import pytest

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    _resolve_game_name,
    cmd_pick,
)
from steam_backlog_enforcer.steam_api import GameInfo, SteamAPIError
from steam_backlog_enforcer.tests._main_helpers import (
    snap,
)
from steam_backlog_enforcer.tests._main_patches import (
    HIDE_OTHERS,
    HIDER_ECHO,
    OWNED_IDS,
    library_hider,
)

PKG = "steam_backlog_enforcer.main.picks"


class TestCmdPick:
    """Tests for cmd_pick."""

    def test_no_snapshot_prints_message(self) -> None:
        """Without a snapshot, pick tells the user to scan first."""
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), State())
        mock_echo.assert_called_once_with("No snapshot found. Run 'scan' first.")

    def test_calls_pick_next_game(self) -> None:
        """With a snapshot, pick hands the games to pick_next_game."""
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={2: 5.0}),
            patch(f"{PKG}.pick_next_game") as mock_pick,
            library_hider([]),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State()
            cmd_pick(config, state)
        mock_pick.assert_called_once()

    def test_hides_games_after_pick(self) -> None:
        """After a pick every game except the assigned one is hidden."""
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={2: 5.0}),
            patch(f"{PKG}.pick_next_game"),
            library_hider([1, 2, 3], (2, None)) as mock_hide,
            patch(f"{PKG}._echo"),
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        mock_hide.assert_called_once_with([1, 2, 3], {2})

    def test_no_hide_message_when_none_hidden(self) -> None:
        """Nothing hidden means nothing is printed."""
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            library_hider([1, 2, 3], (0, None)),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        mock_echo.assert_not_called()

    def test_unreachable_steam_reports_skip(self) -> None:
        """A hide skipped for an unreachable Steam is reported with its reason."""
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            library_hider([1, 2, 3], (0, "Steam is not installed")),
            patch(f"{PKG}._echo") as mock_echo,
            patch(HIDER_ECHO, mock_echo),
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "skipped (Steam is not installed)" in output

    def test_no_hide_when_no_current_app(self) -> None:
        """No assignment after the pick means no hide attempt."""
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            patch(OWNED_IDS) as mock_owned,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), State())
        mock_owned.assert_not_called()

    def test_no_hide_when_owned_ids_empty(self) -> None:
        """An empty owned-games list skips hiding."""
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            library_hider([]),
            patch(HIDE_OTHERS) as mock_hide,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        mock_hide.assert_not_called()

    def test_hltb_cache_applied_to_games(self) -> None:
        """Cached HLTB hours replace unknown hours before picking."""
        snapshot = [snap(2, "NewGame", 10, 0, -1.0)]
        captured_games: list[list[GameInfo]] = []
        config = Config(steam_api_key="k", steam_id="i")
        state = State()

        def capture_pick(
            games: list[GameInfo], *_args: object, **_kwargs: object
        ) -> None:
            captured_games.append(list(games))

        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={2: 7.5}),
            patch(f"{PKG}.pick_next_game", side_effect=capture_pick),
            library_hider([]),
        ):
            cmd_pick(config, state)

        assert len(captured_games) == 1
        assert captured_games[0][0].completionist_hours == pytest.approx(7.5)


class TestResolveGameName:
    """Game names come from the snapshot first, then the Steam API."""

    def test_found_in_snapshot(self) -> None:
        """A snapshot entry supplies the name."""
        snapshot = [
            {
                "app_id": 440,
                "name": "TF2",
                "total_achievements": 0,
                "unlocked_achievements": 0,
                "playtime_minutes": 0,
            }
        ]
        with patch(
            "steam_backlog_enforcer._snapshot.load_snapshot", return_value=snapshot
        ):
            result = _resolve_game_name(Config(), 440)
        assert result == "TF2"

    def test_not_in_snapshot_found_via_api(self) -> None:
        """A game missing from the snapshot is named via the API."""
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 730, "name": "Counter-Strike 2"}
            ]
            result = _resolve_game_name(Config(), 730)
        assert result == "Counter-Strike 2"

    def test_api_raises_returns_none(self) -> None:
        """An API error resolves to None."""
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.side_effect = SteamAPIError("fail")
            result = _resolve_game_name(Config(), 999)
        assert result is None

    def test_not_found_anywhere_returns_none(self) -> None:
        """A game unknown to both sources resolves to None."""
        with (
            patch(f"{PKG}.load_snapshot", return_value=[{"app_id": 1, "name": "X"}]),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.return_value = [{"appid": 1}]
            result = _resolve_game_name(Config(), 999)
        assert result is None

    def test_no_snapshot_falls_through_to_api(self) -> None:
        """No snapshot at all falls back to the API."""
        with (
            patch(f"{PKG}.load_snapshot", return_value=None),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 440, "name": "TF2"}
            ]
            result = _resolve_game_name(Config(), 440)
        assert result == "TF2"
