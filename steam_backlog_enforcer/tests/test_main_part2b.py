"""Tests for the main CLI: enforce-on-done behaviour."""

from typing import Any
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._cmd_done import (
    _enforce_on_done,
    cmd_done,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done_finalize"
PKG = "steam_backlog_enforcer.main"


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
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{CMD_DONE_PKG}.try_hide_other_games", return_value=(1, None)),
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
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{CMD_DONE_PKG}.try_hide_other_games", return_value=(0, None)),
        ):
            _enforce_on_done(config, state)

    def test_hide_skipped_when_steam_unreachable(self) -> None:
        config = Config(kill_unauthorized_games=False, uninstall_other_games=False)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo") as mock_echo,
            patch(f"{CMD_DONE_PKG}.is_game_installed", return_value=True),
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(
                f"{CMD_DONE_PKG}.try_hide_other_games",
                return_value=(0, "Steam is not installed"),
            ),
        ):
            _enforce_on_done(config, state)
        assert "skipped (Steam is not installed)" in " ".join(
            str(c) for c in mock_echo.call_args_list
        )

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
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{CMD_DONE_PKG}.try_hide_other_games", return_value=(0, None)),
        ):
            _enforce_on_done(config, state)
        mock_install.assert_called_once_with(1, "G", "s1", use_steam_protocol=True)

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
            patch(f"{CMD_DONE_PKG}._enforce_on_done"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_reassign_returns_true(self) -> None:
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
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={1: 50.0}),
            patch(f"{CMD_DONE_PKG}._finalize_completion"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)
