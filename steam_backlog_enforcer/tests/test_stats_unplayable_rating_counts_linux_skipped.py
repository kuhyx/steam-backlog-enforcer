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

_PKG = "steam_backlog_enforcer._stats_gathering"


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


class TestFilterQualifyingGamesGroup2:
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

    def test_unplayable_rating_counts_linux_skipped(self) -> None:
        """Test unplayable rating counts linux skipped."""
        state = State()
        g = _game(app_id=1)
        ratings = {1: _unplayable_rating(1)}
        with (
            patch(f"{_PKG}.load_hltb_rush_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{_PKG}._apply_cached_confidence_to_candidates"),
            patch(f"{_PKG}._refresh_candidate_confidence_batch"),
            patch(f"{_PKG}._confidence_fail_reasons", return_value=[]),
            patch(f"{_PKG}.fetch_protondb_ratings", return_value=ratings),
        ):
            qualified, _, linux_skip, _ = _filter_qualifying_games([g], state)
        assert linux_skip == 1
        assert len(qualified) == 0

    def test_no_data_counts_no_data_skipped(self) -> None:
        """Game with all -1 hours is counted as no_data_skipped."""
        state = State()
        g = _game(app_id=1, hours=-1.0)
        qualified, _, _, no_data_skip = self._run([g], state)
        assert no_data_skip == 1
        assert len(qualified) == 0

    def test_worst_hours_positive_when_completionist_hours_positive(self) -> None:
        """Test worst hours positive when completionist hours positive."""
        state = State()
        g = _game(app_id=1, hours=25.0)
        qualified, _, _, _ = self._run([g], state, rush_cache={1: 10.0})
        assert qualified[0].worst_hours == 25.0

    def test_worst_hours_from_leisure_when_completionist_zero(self) -> None:
        """worst_hours falls back to leisure_100h when completionist_hours is zero."""
        state = State()
        g = _game(app_id=1, hours=0.0)
        qualified, _, _, _ = self._run(
            [g], state, rush_cache={1: 5.0}, leisure_cache={1: 6.0}
        )
        assert qualified[0].worst_hours == 6.0

    def test_worst_hours_is_max_when_leisure_exceeds_completionist(self) -> None:
        """worst_hours is max(completionist, leisure_100h) when leisure is higher."""
        state = State()
        g = _game(app_id=1, hours=25.0)
        qualified, _, _, _ = self._run(
            [g], state, rush_cache={1: 10.0}, leisure_cache={1: 40.0}
        )
        assert qualified[0].worst_hours == 40.0

    def test_worst_hours_negative_when_all_zero(self) -> None:
        """worst_hours = -1 when both completionist_hours and leisure_100h are zero."""
        state = State()
        g = _game(app_id=1, hours=0.0)
        qualified, _, _, _ = self._run([g], state, rush_cache={1: 5.0})
        assert qualified[0].worst_hours == -1

    def test_rush_and_leisure_from_cache(self) -> None:
        """Test rush and leisure from cache."""
        state = State()
        g = _game(app_id=1, hours=30.0)
        qualified, _, _, _ = self._run(
            [g], state, rush_cache={1: 12.0}, leisure_cache={1: 40.0}
        )
        assert qualified[0].rush_hours == 12.0
        assert qualified[0].leisure_100h == 40.0

    def test_missing_cache_entry_defaults_to_minus_one(self) -> None:
        """Test missing cache entry defaults to minus one."""
        state = State()
        g = _game(app_id=1, hours=20.0)
        qualified, _, _, _ = self._run([g], state)
        assert qualified[0].rush_hours == -1
        assert qualified[0].leisure_100h == -1

    def test_only_rush_nonzero_qualifies(self) -> None:
        """Game qualifies if only rush_hours is positive (worst <= 0, leisure <= 0)."""
        state = State()
        g = _game(app_id=1, hours=-1.0)
        qualified, _, _, no_data_skip = self._run([g], state, rush_cache={1: 8.0})
        assert no_data_skip == 0
        assert len(qualified) == 1

    def test_game_id_populated_from_cache(self) -> None:
        """hltb_game_id is taken from game_id_cache."""
        state = State()
        g = _game(app_id=1, hours=20.0)
        qualified, _, _, _ = self._run([g], state, game_id_cache={1: 57514})
        assert qualified[0].hltb_game_id == 57514

    def test_game_id_defaults_to_zero_when_not_in_cache(self) -> None:
        """hltb_game_id defaults to 0 when not in cache."""
        state = State()
        g = _game(app_id=1, hours=20.0)
        qualified, _, _, _ = self._run([g], state)
        assert qualified[0].hltb_game_id == 0
