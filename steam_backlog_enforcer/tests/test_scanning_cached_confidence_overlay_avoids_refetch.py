"""Tests for scanning module (part 3): TestPickNextGame continued."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.scanning import pick_next_game
from steam_backlog_enforcer.tests._scanning_games import (
    first_candidate,
    make_config,
    make_game,
    pick_env,
    pick_without_batch_refresh,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo

_CONFIDENCE = "steam_backlog_enforcer._scanning_confidence"
# The retry messages come from the CLI prompter now.
_PROMPT_ECHO = ("_scanning_assign", "_prompter")


class TestPickNextGameGroup2:
    """Tests for pick_next_game (continued from test_scanning.py)."""

    def test_cached_confidence_overlay_avoids_refetch_for_zero_snapshot_fields(
        self,
    ) -> None:
        """Use cached confidence before deciding whether refresh is needed."""
        low = make_game(app_id=1, name="Low", hours=1.0)
        low.comp_100_count = 0
        low.count_comp = 0
        fallback = make_game(app_id=2, name="Fallback", hours=2.0)
        fallback.comp_100_count = 3
        fallback.count_comp = 20

        with (
            patch(
                f"{_CONFIDENCE}.load_hltb_polls_cache",
                return_value={1: 1, 2: 3},
            ),
            patch(
                f"{_CONFIDENCE}.load_hltb_count_comp_cache",
                return_value={1: 8, 2: 20},
            ),
        ):
            state = pick_without_batch_refresh([low, fallback])
        assert state.current_app_id == 2

    def test_stops_collecting_after_n_qualified(self) -> None:
        """Collection stops once _PICK_LIST_SIZE candidates are qualified."""
        # Create 11 games that all pass filters; only the first 10 should be
        # presented and the 11th should never trigger a ProtonDB call.
        games = [
            make_game(app_id=i, name=f"G{i}", hours=float(i)) for i in range(1, 12)
        ]
        protondb_call_count = 0

        def playable_side_effect(c: list[GameInfo]) -> GameInfo | None:
            """Test playable side effect."""
            nonlocal protondb_call_count
            protondb_call_count += 1
            return first_candidate(c)

        state = State()

        with pick_env(playable=playable_side_effect):
            pick_next_game(games, state, make_config())

        assert state.current_app_id == 1
        assert protondb_call_count == 10

    def test_user_picks_second_candidate(self) -> None:
        """User can select a game other than the shortest one."""
        g1 = make_game(app_id=1, name="Short", hours=5.0)
        g2 = make_game(app_id=2, name="Medium", hours=15.0)
        state = State()
        with pick_env(answers="2"):
            pick_next_game([g1, g2], state, make_config())
        assert state.current_app_id == 2

    def test_invalid_input_then_valid(self) -> None:
        """Non-numeric input prints error and loops until valid input."""
        g1 = make_game(app_id=1, name="G1", hours=5.0)
        state = State()
        echoed: list[str] = []
        with pick_env(echo=_PROMPT_ECHO, echoed=echoed, answers=["abc", "1"]):
            pick_next_game([g1], state, make_config())
        assert state.current_app_id == 1
        assert any("Invalid input" in line for line in echoed)

    def test_out_of_range_then_valid(self) -> None:
        """Out-of-range number prints error and loops until valid input."""
        g1 = make_game(app_id=1, name="G1", hours=5.0)
        state = State()
        echoed: list[str] = []
        with pick_env(echo=_PROMPT_ECHO, echoed=echoed, answers=["99", "1"]):
            pick_next_game([g1], state, make_config())
        assert state.current_app_id == 1
        assert any("Out of range" in line for line in echoed)
