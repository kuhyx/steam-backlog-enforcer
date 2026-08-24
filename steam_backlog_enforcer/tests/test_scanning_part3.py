"""Tests for scanning module (part 3): TestPickNextGame continued."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import pick_next_game
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


class TestPickNextGame:
    """Tests for pick_next_game (continued from test_scanning.py)."""

    def test_zero_confidence_is_refreshed_before_skipping(self) -> None:
        """Missing confidence fields are refreshed once before final skip decision."""
        stale = _game(app_id=1, name="Celeste", hours=1.0)
        stale.comp_100_count = 0
        stale.count_comp = 0
        fallback = _game(app_id=2, name="Fallback", hours=2.0)

        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []

        def refresh_side_effect(game: GameInfo) -> None:
            """Test refresh side effect."""
            if game.app_id == 1:
                game.comp_100_count = 899
                game.count_comp = 14055

        with (
            patch(
                "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence",
                side_effect=refresh_side_effect,
            ) as mock_refresh,
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([stale, fallback], state, config)

        assert state.current_app_id == 1
        mock_refresh.assert_called_once_with(stale)
        assert not any("Skipping Celeste" in line for line in echoed)

    def test_nonzero_low_confidence_does_not_force_refetch(self) -> None:
        """Non-zero low-confidence entries are skipped using cached values."""
        low = _game(app_id=1, name="Low", hours=1.0)
        low.comp_100_count = 1
        low.count_comp = 8
        fallback = _game(app_id=2, name="Fallback", hours=2.0)

        config = Config(steam_api_key="k", steam_id="i")
        state = State()

        with (
            patch(
                "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence_batch"
            ) as mock_refresh_batch,
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([low, fallback], state, config)

        assert state.current_app_id == 2
        mock_refresh_batch.assert_not_called()
