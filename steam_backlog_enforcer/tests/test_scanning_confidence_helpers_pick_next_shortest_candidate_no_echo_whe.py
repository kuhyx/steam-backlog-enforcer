"""Scanning tests (part 4): collect_top_candidates, do_check, confidence."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import (
    _pick_next_shortest_candidate,
    do_check,
)
from steam_backlog_enforcer.steam_api import GameInfo


def _game(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 0,
    hours: float = -1,
) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
        comp_100_count=3,
        count_comp=15,
    )


class TestConfidenceHelpersGroup2:
    """Coverage-focused tests for scanning confidence helper branches."""

    def test_pick_next_shortest_candidate_no_echo_when_linux_skipped_zero(
        self,
    ) -> None:
        """Covers 419->423: no echo printed when linux_skipped == 0."""
        good = _game(app_id=51, name="Good", hours=2.0)
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=good,
            ),
            patch("steam_backlog_enforcer.scanning._echo") as mock_echo,
        ):
            picked, _skipped_low_conf, skipped_linux = _pick_next_shortest_candidate(
                [good],
            )
        assert picked is good
        assert skipped_linux == 0
        mock_echo.assert_not_called()

    def test_pick_next_shortest_candidate_skips_low_confidence(self) -> None:
        """Covers lines 413-414: confidence_skipped += 1; continue."""
        low_conf = _game(app_id=10, name="Low", hours=1.0)
        low_conf.comp_100_count = 0
        low_conf.count_comp = 0
        with (
            patch(
                "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence"
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            picked, skipped_low_conf, skipped_linux = _pick_next_shortest_candidate(
                [low_conf],
            )
        assert picked is None
        assert skipped_low_conf == 1
        assert skipped_linux == 0

    def test_pick_next_shortest_candidate_all_protondb_fail(self) -> None:
        """Covers lines 426-428: linux_skipped > 0 after loop, return None."""
        g1 = _game(app_id=10, name="Borked", hours=1.0)
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=None,
            ),
            patch("steam_backlog_enforcer.scanning._echo") as mock_echo,
        ):
            picked, _skipped_low_conf, skipped_linux = _pick_next_shortest_candidate(
                [g1],
            )
        assert picked is None
        assert skipped_linux == 1
        assert any(
            "Skipped 1 game(s) with poor Linux compatibility" in str(call)
            for call in mock_echo.call_args_list
        )

        game = _game(app_id=440, name="TF2", total=5, unlocked=5)
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        snap = [game.to_snapshot()]
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch(
                "steam_backlog_enforcer.scanning.send_notification",
            ),
            patch(
                "steam_backlog_enforcer.scanning.load_snapshot",
                return_value=snap,
            ),
            patch(
                "steam_backlog_enforcer.scanning.pick_next_game",
            ),
            patch("steam_backlog_enforcer.scanning.detect_tampering"),
        ):
            state = State(current_app_id=440, current_game_name="TF2")
            do_check(Config(steam_api_key="k", steam_id="i"), state)
            assert 440 in state.finished_app_ids

    def test_complete_no_snapshot(self) -> None:
        """Test complete no snapshot."""
        game = _game(app_id=440, name="TF2", total=5, unlocked=5)
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch(
                "steam_backlog_enforcer.scanning.send_notification",
            ),
            patch(
                "steam_backlog_enforcer.scanning.load_snapshot",
                return_value=None,
            ),
            patch("steam_backlog_enforcer.scanning.detect_tampering"),
        ):
            state = State(current_app_id=440, current_game_name="TF2")
            do_check(Config(steam_api_key="k", steam_id="i"), state)

    def test_not_complete(self) -> None:
        """Test not complete."""
        game = _game(app_id=440, name="TF2", total=10, unlocked=5)
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch("steam_backlog_enforcer.scanning.detect_tampering"),
        ):
            state = State(current_app_id=440, current_game_name="TF2")
            do_check(Config(steam_api_key="k", steam_id="i"), state)
