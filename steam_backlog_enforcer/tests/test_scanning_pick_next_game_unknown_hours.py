"""Tests for scanning module."""

from __future__ import annotations

from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.scanning import (
    pick_next_game,
)
from steam_backlog_enforcer.tests._scanning_games import (
    make_config,
    make_game,
    pick_env,
)


class TestPickNextGameGroup2:
    """Tests for pick_next_game."""

    def test_unknown_hours(self) -> None:
        """Test unknown hours."""
        g1 = make_game(app_id=1, name="G1", hours=-1)
        g2 = make_game(app_id=2, name="G2", hours=10.0)
        state = State()
        with pick_env():
            pick_next_game([g1, g2], state, make_config())
            assert state.current_app_id == 2

    def test_picks_game_no_hours(self) -> None:
        """Chosen game has no HLTB hours — covers no-hours output branch."""
        g1 = make_game(app_id=1, name="G1", hours=-1)
        state = State()
        with pick_env():
            pick_next_game([g1], state, make_config())
            assert state.current_app_id == 1

    def test_skips_low_confidence_and_picks_next(self) -> None:
        """Test skips low confidence and picks next."""
        low = make_game(app_id=1, name="LowConfidence", hours=1.0)
        low.comp_100_count = 1
        low.count_comp = 5
        valid = make_game(app_id=2, name="ValidConfidence", hours=2.0)
        valid.comp_100_count = 3
        valid.count_comp = 15
        echoed: list[str] = []
        state = State()
        with pick_env(echo=("scanning", "_scanning_confidence"), echoed=echoed):
            pick_next_game([low, valid], state, make_config())
        assert state.current_app_id == 2
        assert any("Skipping LowConfidence" in line for line in echoed)
        assert any("comp_100 polls 1 < 3" in line for line in echoed)

    def test_all_candidates_filtered_by_confidence(self) -> None:
        """Test all candidates filtered by confidence."""
        low_a = make_game(app_id=1, name="LowA", hours=1.0)
        low_a.comp_100_count = 2
        low_a.count_comp = 15
        low_b = make_game(app_id=2, name="LowB", hours=2.0)
        low_b.comp_100_count = 3
        low_b.count_comp = 14
        echoed: list[str] = []
        state = State()
        # The "nothing assignable" line is spoken where the slot is cleared.
        with pick_env(
            echo=("scanning", "_scanning_confidence", "_scanning_assign"),
            echoed=echoed,
            playable=lambda _c: None,
        ) as mocks:
            pick_next_game([low_a, low_b], state, make_config())
        assert state.current_app_id is None
        mocks.pick.assert_not_called()
        assert any("No assignable games found" in line for line in echoed)
