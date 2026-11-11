"""Shared ``cmd_done`` cases, run against each public import path of it.

``main.cmd_done`` re-exports ``_cmd_done_finalize.cmd_done``; each test module
subclasses :class:`CmdDoneCases` and binds :meth:`run_done` to its import.
"""

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done_finalize"


class CmdDoneCases:
    """Verdict and HLTB-estimate cases for cmd_done (not collected itself)."""

    def run_done(self, config: Config, state: State) -> None:
        """Call the cmd_done under test."""
        raise NotImplementedError

    def test_no_game_assigned(self) -> None:
        """With no assigned game cmd_done says so and stops."""
        with patch(f"{CMD_DONE_PKG}._echo") as mock_echo:
            self.run_done(Config(), State())
        assert any("No game" in str(c) for c in mock_echo.call_args_list)

    def test_fetch_fails(self) -> None:
        """A failed Steam refresh ends cmd_done without raising."""
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = None
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            self.run_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_not_complete_enforces(self) -> None:
        """An incomplete game goes back to enforcement."""
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
            self.run_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_complete_finalizes(self) -> None:
        """A fully completed game is finalised."""
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
            self.run_done(Config(steam_api_key="k", steam_id="i"), state)
        mock_final.assert_called_once()

    def test_hltb_cache_miss_fetches(self) -> None:
        """A game missing from the HLTB cache gets its time fetched."""
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
            self.run_done(Config(steam_api_key="k", steam_id="i"), state)

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
            self.run_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_reassign_returns_true(self) -> None:
        """A completed game is finalised even with a long HLTB estimate."""
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
            self.run_done(Config(steam_api_key="k", steam_id="i"), state)
