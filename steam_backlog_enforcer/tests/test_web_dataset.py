"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from steam_backlog_enforcer._web_dataset import (
    HOURS_PER_DAY_PRESETS,
    PaceVsHLTB,
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
    compute_pace_vs_hltb,
    count_complete_since_start,
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


class TestCountCompleteSinceStart:
    """Tests for count_complete_since_start."""

    def _ach(self, ts: int, *, achieved: bool = True) -> object:
        from steam_backlog_enforcer.steam_api import AchievementInfo

        return AchievementInfo(
            api_name="A", display_name="A", achieved=achieved, unlock_time=ts
        )

    def _complete_game(self, app_id: int, unlock_ts: int) -> GameInfo:
        achs = [self._ach(unlock_ts)] * 5
        return _gi(
            app_id=app_id,
            total_achievements=5,
            unlocked_achievements=5,
            achievements=achs,
        )

    def test_empty_started_at_returns_zero(self) -> None:
        games = [self._complete_game(1, 1_000_000)]
        assert count_complete_since_start(games, "") == 0

    def test_invalid_started_at_returns_zero(self) -> None:
        games = [self._complete_game(1, 1_000_000)]
        assert count_complete_since_start(games, "not-a-date") == 0

    def test_counts_game_completed_after_start(self) -> None:
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        after_ts = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
        games = [self._complete_game(1, after_ts)]
        assert count_complete_since_start(games, started.isoformat()) == 1

    def test_excludes_game_completed_before_start(self) -> None:
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        before_ts = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp())
        games = [self._complete_game(1, before_ts)]
        assert count_complete_since_start(games, started.isoformat()) == 0

    def test_excludes_incomplete_game(self) -> None:
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        after_ts = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
        incomplete = _gi(
            app_id=1,
            total_achievements=5,
            unlocked_achievements=3,
            achievements=[self._ach(after_ts)] * 3,
        )
        assert count_complete_since_start([incomplete], started.isoformat()) == 0

    def test_excludes_game_with_no_achievement_timestamps(self) -> None:
        """Complete game with unlock_time=0 on all achievements is excluded."""
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        no_ts = _gi(
            app_id=1,
            total_achievements=5,
            unlocked_achievements=5,
            achievements=[self._ach(0)] * 5,
        )
        assert count_complete_since_start([no_ts], started.isoformat()) == 0

    def test_mixed_games_counts_only_post_start(self) -> None:
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        after_ts = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
        before_ts = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp())
        games = [
            self._complete_game(1, after_ts),
            self._complete_game(2, before_ts),
            self._complete_game(3, after_ts),
        ]
        assert count_complete_since_start(games, started.isoformat()) == 2

    def test_uses_max_unlock_time_across_achievements(self) -> None:
        """Game counts if its LAST achievement was unlocked after start."""
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        before_ts = int(datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp())
        after_ts = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp())
        # Mix of before/after timestamps — max is after start, so should count
        achs = [self._ach(before_ts)] * 4 + [self._ach(after_ts)]
        game = _gi(
            app_id=1, total_achievements=5, unlocked_achievements=5, achievements=achs
        )
        assert count_complete_since_start([game], started.isoformat()) == 1


class TestStateInfo:
    """Tests for _state_info pace calculation."""

    def test_no_start_date(self) -> None:
        info = _state_info(State(), games_done=5, games_done_since_start=5)
        assert info.days_elapsed == 0
        assert info.pace_games_per_day == 0.0
        assert info.games_done == 5
        assert info.games_done_since_start == 5

    def test_invalid_start_date(self) -> None:
        info = _state_info(
            State(enforcement_started_at="not-a-date"),
            games_done=5,
            games_done_since_start=5,
        )
        assert info.days_elapsed == 0
        assert info.pace_games_per_day == 0.0

    def test_valid_start_with_games(self) -> None:
        started = datetime.now(timezone.utc) - timedelta(days=50)
        info = _state_info(
            State(enforcement_started_at=started.isoformat()),
            games_done=12,
            games_done_since_start=10,
        )
        assert info.days_elapsed >= 49
        assert info.pace_games_per_day > 0.0
        assert info.games_done == 12
        assert info.games_done_since_start == 10

    def test_valid_start_zero_since_start_keeps_zero_pace(self) -> None:
        """games_done_since_start=0 → pace stays 0 even if total games_done > 0."""
        started = datetime.now(timezone.utc) - timedelta(days=50)
        info = _state_info(
            State(enforcement_started_at=started.isoformat()),
            games_done=5,
            games_done_since_start=0,
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
            "pace_vs_hltb",
            "generated_at",
        }
        assert isinstance(payload["games"], list)
        assert isinstance(payload["state"], dict)


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


class TestComputePaceVsHLTB:
    """Tests for compute_pace_vs_hltb — 100 % branch coverage."""

    def test_no_completed_games_returns_none(self) -> None:
        incomplete = _gi(app_id=1, total_achievements=10, unlocked_achievements=0)
        assert compute_pace_vs_hltb([incomplete], {}) is None

    def test_complete_but_zero_playtime_ignored(self) -> None:
        game = _complete_game(playtime_minutes=0)
        assert compute_pace_vs_hltb([game], {}) is None

    def test_no_rush_data_in_cache_returns_none(self) -> None:
        game = _complete_game(app_id=1)
        # cache has hours but no rush_hours
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": -1,
                "leisure_100h": -1,
                "hltb_game_id": 0,
            }
        }
        assert compute_pace_vs_hltb([game], cache) is None

    def test_rush_only_ratio_computed(self) -> None:
        """With rush but no leisure, ratio_vs_rush is computed, interpolation_t = -1."""
        game = _complete_game(app_id=1, playtime_minutes=600)  # 10h actual
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": -1,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.calibration_count == 1
        assert result.ratio_vs_rush == round(10.0 / 8.0, 3)
        assert result.ratio_vs_leisure == -1.0
        assert result.interpolation_t == -1.0

    def test_rush_only_style_faster_than_rush_when_ratio_below_one(self) -> None:
        """Plays faster than rush (actual < rush) → style = faster_than_rush."""
        game = _complete_game(app_id=1, playtime_minutes=300)  # 5h actual
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": -1,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.player_style == "faster_than_rush"

    def test_rush_only_style_unknown_when_ratio_at_or_above_one(self) -> None:
        """Without leisure data and ratio >= 1 → style = unknown."""
        game = _complete_game(app_id=1, playtime_minutes=600)  # 10h
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": -1,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.player_style == "unknown"

    def test_both_rush_and_leisure_interpolation_computed(self) -> None:
        """With both rush + leisure, interpolation_t is computed."""
        # actual=10h, rush=8h, leisure=20h → t = (10-8)/(20-8) = 2/12 ≈ 0.167
        game = _complete_game(app_id=1, playtime_minutes=600)
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 20.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.interpolation_t == round((10.0 - 8.0) / (20.0 - 8.0), 3)
        assert result.ratio_vs_leisure == round(10.0 / 20.0, 3)
        assert result.player_style == "rush_to_leisure"

    def test_style_faster_than_rush_when_t_negative(self) -> None:
        """t < 0 means faster than rush."""
        game = _complete_game(app_id=1, playtime_minutes=300)  # 5h actual
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 20.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.interpolation_t < 0
        assert result.player_style == "faster_than_rush"

    def test_style_slower_than_leisure_when_t_above_one(self) -> None:
        """t > 1 means slower than leisure."""
        game = _complete_game(app_id=1, playtime_minutes=1500)  # 25h actual
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 20.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.interpolation_t > 1.0
        assert result.player_style == "slower_than_leisure"

    def test_interpolation_t_minus_one_when_leisure_not_greater_than_rush(self) -> None:
        """Edge case: leisure <= rush, can't divide, interpolation_t = -1."""
        game = _complete_game(app_id=1, playtime_minutes=600)
        # leisure == rush → denominator = 0
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 8.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.interpolation_t == -1.0

    def test_pace_vs_hltb_is_dataclass(self) -> None:
        """Return type is PaceVsHLTB."""
        game = _complete_game(app_id=1)
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 20.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert isinstance(result, PaceVsHLTB)
