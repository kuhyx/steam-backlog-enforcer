"""Tests for scanning module (part 3): TestPickNextGame continued."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.scanning import pick_next_game
from steam_backlog_enforcer.tests._scanning_games import (
    make_config,
    make_game,
    pick_env,
    pick_without_batch_refresh,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo

_CONFIDENCE = "steam_backlog_enforcer._scanning_confidence"


class TestPickNextGame:
    """Tests for pick_next_game (continued from test_scanning.py)."""

    def test_zero_confidence_is_refreshed_before_skipping(self) -> None:
        """Missing confidence fields are refreshed once before final skip decision."""
        stale = make_game(app_id=1, name="Celeste", hours=1.0)
        stale.comp_100_count = 0
        stale.count_comp = 0
        fallback = make_game(app_id=2, name="Fallback", hours=2.0)

        state = State()
        echoed: list[str] = []

        def refresh_side_effect(game: GameInfo) -> None:
            """Test refresh side effect."""
            if game.app_id == 1:
                game.comp_100_count = 899
                game.count_comp = 14055

        with (
            patch(
                f"{_CONFIDENCE}._refresh_candidate_confidence",
                side_effect=refresh_side_effect,
            ) as mock_refresh,
            pick_env(echo=("scanning", "_scanning_confidence"), echoed=echoed),
        ):
            pick_next_game([stale, fallback], state, make_config())

        assert state.current_app_id == 1
        mock_refresh.assert_called_once_with(stale)
        assert not any("Skipping Celeste" in line for line in echoed)

    def test_nonzero_low_confidence_does_not_force_refetch(self) -> None:
        """Non-zero low-confidence entries are skipped using cached values."""
        low = make_game(app_id=1, name="Low", hours=1.0)
        low.comp_100_count = 1
        low.count_comp = 8
        fallback = make_game(app_id=2, name="Fallback", hours=2.0)

        state = pick_without_batch_refresh([low, fallback])
        assert state.current_app_id == 2
