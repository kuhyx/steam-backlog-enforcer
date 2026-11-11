"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from steam_backlog_enforcer._stats import (
    _filter_qualifying_games,
)
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.tests._stats_games import (
    FilterInputs,
    filter_env,
    make_game,
    run_filter,
)

_PKG = "steam_backlog_enforcer._stats_gathering"


class TestFilterQualifyingGames:
    """Tests for _filter_qualifying_games."""

    def test_current_app_id_excluded(self) -> None:
        """Test current app id excluded."""
        state = State(current_app_id=1)
        g1 = make_game(app_id=1)
        g2 = make_game(app_id=2)
        qualified, _, _, _ = run_filter([g1, g2], state)
        ids = [e.game.app_id for e in qualified]
        assert 1 not in ids
        assert 2 in ids

    def test_no_current_app_id_branch(self) -> None:
        """current_app_id is None — the exclude.add branch is not taken."""
        state = State(current_app_id=None)
        g = make_game(app_id=3)
        qualified, _, _, _ = run_filter([g], state)
        assert len(qualified) == 1

    def test_finished_app_ids_excluded(self) -> None:
        """Test finished app ids excluded."""
        state = State()
        state.finished_app_ids = [1]
        g1 = make_game(app_id=1)
        g2 = make_game(app_id=2)
        qualified, _, _, _ = run_filter([g1, g2], state)
        assert all(e.game.app_id != 1 for e in qualified)

    def test_complete_games_excluded(self) -> None:
        """Games where is_complete is True are excluded from candidates."""
        state = State()
        complete = make_game(app_id=1, total=5, unlocked=5)
        incomplete = make_game(app_id=2, total=5, unlocked=0)
        qualified, _, _, _ = run_filter([complete, incomplete], state)
        assert len(qualified) == 1
        assert qualified[0].game.app_id == 2

    def test_low_confidence_counts_hltb_skipped(self) -> None:
        """Test low confidence counts hltb skipped."""
        state = State()
        g = make_game(app_id=1)
        with filter_env(FilterInputs(fail_reasons=["low"])):
            qualified, hltb_skip, _, _ = _filter_qualifying_games([g], state)
        assert hltb_skip == 1
        assert len(qualified) == 0

    def test_no_candidates_skips_protondb_call(self) -> None:
        """When confidence filters all out, fetch_protondb_ratings is not called."""
        state = State()
        g = make_game(app_id=1)
        with filter_env(FilterInputs(fail_reasons=["low"])) as mock_proton:
            _filter_qualifying_games([g], state)
        mock_proton.assert_not_called()
