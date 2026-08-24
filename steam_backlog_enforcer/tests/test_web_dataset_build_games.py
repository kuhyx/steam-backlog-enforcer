"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from steam_backlog_enforcer._web_dataset import (
    HOURS_PER_DAY_PRESETS,
    WebGame,
    _build_games,
    build_web_dataset,
)
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import GameInfo

_PKG = "steam_backlog_enforcer._web_dataset"


def _gi(**over: object) -> GameInfo:
    """Build a GameInfo with field overrides."""
    base = GameInfo(
        app_id=1,
        name="G",
        total_achievements=10,
        unlocked_achievements=0,
        playtime_minutes=60,
        completionist_hours=20.0,
        comp_100_count=5,
        count_comp=20,
    )
    return replace(base, **over)


def _wg(**over: object) -> WebGame:
    """Build a WebGame with field overrides."""
    base = WebGame(
        app_id=1,
        name="Game1",
        completion_pct=0.0,
        playtime_minutes=60,
        rush_hours=10.0,
        leisure_hours=20.0,
        worst_hours=25.0,
        count_comp=20,
        comp_100_count=5,
        hltb_game_id=0,
        protondb_tier="gold",
        protondb_trending_tier="gold",
        protondb_score=0.8,
    )
    return replace(base, **over)


def _complete_game(
    app_id: int = 1,
    playtime_minutes: int = 600,
) -> GameInfo:
    """Complete game (100 % achievements, has playtime)."""
    return GameInfo(
        app_id=app_id,
        name=f"Done{app_id}",
        total_achievements=10,
        unlocked_achievements=10,
        playtime_minutes=playtime_minutes,
        completionist_hours=0.0,
        comp_100_count=5,
        count_comp=20,
    )


class TestBuildGames:
    """Tests for _build_games (patches cache loaders, no file I/O)."""

    def _run(
        self,
        games: list[GameInfo],
        exclude: set[int],
        raw: dict[int, dict[str, object]] | None = None,
        protondb: dict[str, dict[str, object]] | None = None,
    ) -> list[WebGame]:
        """Test run."""
        with (
            patch(f"{_PKG}._read_raw_cache", return_value=raw or {}),
            patch(f"{_PKG}._load_cache", return_value=protondb or {}),
        ):
            return _build_games(games, exclude)

    def test_skips_complete_games(self) -> None:
        """Test skips complete games."""
        rows = self._run(
            [_gi(app_id=1, total_achievements=5, unlocked_achievements=5)], set()
        )
        assert rows == []

    def test_skips_excluded_games(self) -> None:
        """Test skips excluded games."""
        assert self._run([_gi(app_id=1)], {1}) == []

    def test_uses_cache_entry_when_present(self) -> None:
        """Test uses cache entry when present."""
        raw = {
            1: {
                "hours": 18.0,
                "polls": 7,
                "count_comp": 30,
                "rush_hours": 9.0,
                "leisure_100h": 22.0,
                "hltb_game_id": 555,
            }
        }
        proton = {"1": {"tier": "platinum", "trending_tier": "gold", "score": 0.9}}
        rows = self._run([_gi(app_id=1, completionist_hours=0.0)], set(), raw, proton)
        assert len(rows) == 1
        row = rows[0]
        assert row.rush_hours == 9.0
        assert row.leisure_hours == 22.0
        assert row.worst_hours == 22.0  # max(cache 18, leisure 22)
        assert row.count_comp == 30
        assert row.comp_100_count == 7
        assert row.hltb_game_id == 555
        assert row.protondb_tier == "platinum"
        assert row.protondb_trending_tier == "gold"

    def test_defaults_when_no_cache_entries(self) -> None:
        """Test defaults when no cache entries."""
        rows = self._run([_gi(app_id=1, completionist_hours=12.0)], set())
        assert len(rows) == 1
        row = rows[0]
        assert row.rush_hours == -1
        assert row.leisure_hours == -1
        assert row.worst_hours == 12.0  # completionist only
        assert row.protondb_tier == ""  # no protondb entry


class TestBuildWebDataset:
    """Tests for build_web_dataset (top-level projection)."""

    def test_no_snapshot_returns_empty_games(self) -> None:
        """Test no snapshot returns empty games."""
        with (
            patch(f"{_PKG}.load_snapshot", return_value=None),
            patch(f"{_PKG}._read_raw_cache", return_value={}),
            patch(f"{_PKG}._load_cache", return_value={}),
        ):
            ds = build_web_dataset(State())
        assert ds.games == []
        assert ds.state.games_done == 0
        assert ds.default_summary.qualifying == 0
        assert ds.defaults.hours_per_day_presets == list(HOURS_PER_DAY_PRESETS)

    def test_excludes_current_app_id(self) -> None:
        """Test excludes current app id."""
        snapshot = [_gi(app_id=1).to_snapshot(), _gi(app_id=2).to_snapshot()]
        raw = {
            aid: {
                "hours": -1,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 10.0,
                "leisure_100h": 25.0,
                "hltb_game_id": 0,
            }
            for aid in (1, 2)
        }
        proton = {str(a): {"tier": "gold", "trending_tier": "gold"} for a in (1, 2)}
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{_PKG}._read_raw_cache", return_value=raw),
            patch(f"{_PKG}._load_cache", return_value=proton),
        ):
            ds = build_web_dataset(State(current_app_id=1))
        assert [g.app_id for g in ds.games] == [2]

    def test_parity_mini_oracle(self) -> None:
        """A small hand-checked dataset reproduces qualifying + totals."""
        # g1 qualifies; g2 fails confidence; g3 is complete (excluded).
        snapshot = [
            _gi(app_id=1, completionist_hours=0.0).to_snapshot(),
            _gi(app_id=2, completionist_hours=0.0).to_snapshot(),
            _gi(app_id=3, total_achievements=5, unlocked_achievements=5).to_snapshot(),
        ]
        raw = {
            1: {
                "hours": -1,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 10.0,
                "leisure_100h": 25.0,
                "hltb_game_id": 0,
            },
            2: {
                "hours": -1,
                "polls": 5,
                "count_comp": 0,  # fails count_comp threshold
                "rush_hours": 10.0,
                "leisure_100h": 25.0,
                "hltb_game_id": 0,
            },
        }
        proton = {"1": {"tier": "gold", "trending_tier": "gold"}}
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{_PKG}._read_raw_cache", return_value=raw),
            patch(f"{_PKG}._load_cache", return_value=proton),
        ):
            ds = build_web_dataset(State())
        assert ds.state.games_done == 1  # g3 complete
        assert len(ds.games) == 2  # g1 + g2 candidates, g3 excluded
        assert ds.default_summary.qualifying == 1  # only g1
        assert ds.default_summary.rush_total == 10.0
        assert ds.default_summary.leisure_total == 25.0
        assert ds.default_summary.worst_total == 25.0
