"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._stats import (
    _filter_qualifying_games,
    _GameTimes,
)
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.protondb import ProtonDBRating
from steam_backlog_enforcer.steam_api import GameInfo

_PKG = "steam_backlog_enforcer._stats"


def _game(
    app_id: int = 1,
    name: str = "G",
    hours: float = 10.0,
    total: int = 10,
    unlocked: int = 0,
) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
        comp_100_count=5,
        count_comp=20,
    )


def _unplayable_rating(app_id: int) -> ProtonDBRating:
    return ProtonDBRating(app_id=app_id, tier="borked")


class TestFilterQualifyingGames:
    """Tests for _filter_qualifying_games."""

    def _run(
        self,
        games: list[GameInfo],
        state: State,
        rush_cache: dict[int, float] | None = None,
        leisure_cache: dict[int, float] | None = None,
        game_id_cache: dict[int, int] | None = None,
    ) -> tuple[list[_GameTimes], int, int, int]:
        """Test run."""
        with (
            patch(f"{_PKG}.load_hltb_rush_cache", return_value=rush_cache or {}),
            patch(
                f"{_PKG}.load_hltb_leisure_100h_cache",
                return_value=leisure_cache or {},
            ),
            patch(
                f"{_PKG}.load_hltb_game_id_cache",
                return_value=game_id_cache or {},
            ),
            patch(f"{_PKG}._apply_cached_confidence_to_candidates"),
            patch(f"{_PKG}._refresh_candidate_confidence_batch"),
            patch(f"{_PKG}._confidence_fail_reasons", return_value=[]),
            patch(f"{_PKG}.fetch_protondb_ratings", return_value={}),
        ):
            return _filter_qualifying_games(games, state)

    def test_current_app_id_excluded(self) -> None:
        """Test current app id excluded."""
        state = State(current_app_id=1)
        g1 = _game(app_id=1)
        g2 = _game(app_id=2)
        qualified, _, _, _ = self._run([g1, g2], state)
        ids = [e.game.app_id for e in qualified]
        assert 1 not in ids
        assert 2 in ids

    def test_no_current_app_id_branch(self) -> None:
        """current_app_id is None — the exclude.add branch is not taken."""
        state = State(current_app_id=None)
        g = _game(app_id=3)
        qualified, _, _, _ = self._run([g], state)
        assert len(qualified) == 1

    def test_finished_app_ids_excluded(self) -> None:
        """Test finished app ids excluded."""
        state = State()
        state.finished_app_ids = [1]
        g1 = _game(app_id=1)
        g2 = _game(app_id=2)
        qualified, _, _, _ = self._run([g1, g2], state)
        assert all(e.game.app_id != 1 for e in qualified)

    def test_complete_games_excluded(self) -> None:
        """Games where is_complete is True are excluded from candidates."""
        state = State()
        complete = _game(app_id=1, total=5, unlocked=5)
        incomplete = _game(app_id=2, total=5, unlocked=0)
        qualified, _, _, _ = self._run([complete, incomplete], state)
        assert len(qualified) == 1
        assert qualified[0].game.app_id == 2

    def test_low_confidence_counts_hltb_skipped(self) -> None:
        """Test low confidence counts hltb skipped."""
        state = State()
        g = _game(app_id=1)
        with (
            patch(f"{_PKG}.load_hltb_rush_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{_PKG}._apply_cached_confidence_to_candidates"),
            patch(f"{_PKG}._refresh_candidate_confidence_batch"),
            patch(f"{_PKG}._confidence_fail_reasons", return_value=["low"]),
            patch(f"{_PKG}.fetch_protondb_ratings", return_value={}),
        ):
            qualified, hltb_skip, _, _ = _filter_qualifying_games([g], state)
        assert hltb_skip == 1
        assert len(qualified) == 0

    def test_no_candidates_skips_protondb_call(self) -> None:
        """When confidence filters all out, fetch_protondb_ratings is not called."""
        state = State()
        g = _game(app_id=1)
        with (
            patch(f"{_PKG}.load_hltb_rush_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{_PKG}._apply_cached_confidence_to_candidates"),
            patch(f"{_PKG}._refresh_candidate_confidence_batch"),
            patch(f"{_PKG}._confidence_fail_reasons", return_value=["low"]),
            patch(f"{_PKG}.fetch_protondb_ratings") as mock_proton,
        ):
            _filter_qualifying_games([g], state)
        mock_proton.assert_not_called()
