"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from steam_backlog_enforcer._web_dataset import (
    HOURS_PER_DAY_PRESETS,
    WebGame,
    _build_games,
    _default_qualifying,
    _default_summary,
    _has_any_time,
    _passes_default_confidence,
    _state_info,
    _sum_positive,
    _worst_hours,
    build_web_dataset,
    dataset_to_payload,
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


class TestWorstHours:
    """Tests for _worst_hours (mirrors _stats worst-case selection)."""

    def test_completionist_dominates(self) -> None:
        game = _gi(completionist_hours=30.0)
        assert _worst_hours(game, cache_hours=10.0, leisure=20.0) == 30.0

    def test_falls_back_to_cache_and_leisure_when_completionist_zero(self) -> None:
        game = _gi(completionist_hours=0.0)
        assert _worst_hours(game, cache_hours=15.0, leisure=8.0) == 15.0

    def test_minus_one_when_all_non_positive(self) -> None:
        game = _gi(completionist_hours=0.0)
        assert _worst_hours(game, cache_hours=-1.0, leisure=-1.0) == -1.0


class TestPassesDefaultConfidence:
    """Tests for _passes_default_confidence."""

    def test_fail_low_comp_100(self) -> None:
        assert _passes_default_confidence(_wg(comp_100_count=2)) is False

    def test_fail_low_count_comp(self) -> None:
        assert _passes_default_confidence(_wg(comp_100_count=5, count_comp=10)) is False

    def test_pass_when_all_thresholds_met(self) -> None:
        assert _passes_default_confidence(_wg(comp_100_count=5, count_comp=20)) is True


class TestHasAnyTime:
    """Tests for _has_any_time."""

    def test_true_when_some_positive(self) -> None:
        assert _has_any_time(_wg(rush_hours=-1, leisure_hours=-1, worst_hours=5.0))

    def test_false_when_all_non_positive(self) -> None:
        game = _wg(rush_hours=-1, leisure_hours=-1, worst_hours=-1)
        assert _has_any_time(game) is False


class TestDefaultQualifying:
    """Tests for _default_qualifying — each filter rejection branch."""

    def test_rejects_low_confidence(self) -> None:
        assert _default_qualifying([_wg(count_comp=0)]) == []

    def test_rejects_unplayable(self) -> None:
        game = _wg(protondb_tier="borked", protondb_trending_tier="borked")
        assert _default_qualifying([game]) == []

    def test_rejects_no_time(self) -> None:
        game = _wg(rush_hours=-1, leisure_hours=-1, worst_hours=-1)
        assert _default_qualifying([game]) == []

    def test_accepts_qualifying_game(self) -> None:
        assert len(_default_qualifying([_wg()])) == 1


class TestSumPositive:
    """Tests for _sum_positive."""

    def test_sums_only_positive(self) -> None:
        rows = [_wg(rush_hours=10.0), _wg(rush_hours=-1.0), _wg(rush_hours=5.5)]
        assert _sum_positive(rows, "rush_hours") == 15.5

    def test_empty(self) -> None:
        assert _sum_positive([], "rush_hours") == 0.0


class TestDefaultSummary:
    """Tests for _default_summary."""

    def test_totals(self) -> None:
        rows = [_wg(rush_hours=10.0, leisure_hours=20.0, worst_hours=25.0)]
        summary = _default_summary(rows)
        assert summary.qualifying == 1
        assert summary.rush_total == 10.0
        assert summary.leisure_total == 20.0
        assert summary.worst_total == 25.0


class TestStateInfo:
    """Tests for _state_info pace calculation."""

    def test_no_start_date(self) -> None:
        info = _state_info(State(), games_done=5)
        assert info.days_elapsed == 0
        assert info.pace_games_per_day == 0.0

    def test_invalid_start_date(self) -> None:
        info = _state_info(State(enforcement_started_at="not-a-date"), games_done=5)
        assert info.days_elapsed == 0
        assert info.pace_games_per_day == 0.0

    def test_valid_start_with_games(self) -> None:
        started = datetime.now(timezone.utc) - timedelta(days=50)
        info = _state_info(
            State(enforcement_started_at=started.isoformat()), games_done=10
        )
        assert info.days_elapsed >= 49
        assert info.pace_games_per_day > 0.0

    def test_valid_start_zero_games_keeps_zero_pace(self) -> None:
        started = datetime.now(timezone.utc) - timedelta(days=50)
        info = _state_info(
            State(enforcement_started_at=started.isoformat()), games_done=0
        )
        assert info.days_elapsed >= 49
        assert info.pace_games_per_day == 0.0


class TestBuildGames:
    """Tests for _build_games (patches cache loaders, no file I/O)."""

    def _run(
        self,
        games: list[GameInfo],
        exclude: set[int],
        raw: dict[int, dict[str, object]] | None = None,
        protondb: dict[str, dict[str, object]] | None = None,
    ) -> list[WebGame]:
        with (
            patch(f"{_PKG}._read_raw_cache", return_value=raw or {}),
            patch(f"{_PKG}._load_cache", return_value=protondb or {}),
        ):
            return _build_games(games, exclude)

    def test_skips_complete_games(self) -> None:
        rows = self._run(
            [_gi(app_id=1, total_achievements=5, unlocked_achievements=5)], set()
        )
        assert rows == []

    def test_skips_excluded_games(self) -> None:
        assert self._run([_gi(app_id=1)], {1}) == []

    def test_uses_cache_entry_when_present(self) -> None:
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


class TestDatasetToPayload:
    """Tests for dataset_to_payload."""

    def test_serializes_to_dict(self) -> None:
        with (
            patch(f"{_PKG}.load_snapshot", return_value=None),
            patch(f"{_PKG}._read_raw_cache", return_value={}),
            patch(f"{_PKG}._load_cache", return_value={}),
        ):
            payload = dataset_to_payload(build_web_dataset(State()))
        assert set(payload) == {
            "games",
            "state",
            "defaults",
            "default_summary",
            "generated_at",
        }
        assert isinstance(payload["games"], list)
        assert isinstance(payload["state"], dict)
