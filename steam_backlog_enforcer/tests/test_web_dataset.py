"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from dataclasses import replace

from steam_backlog_enforcer._web_dataset import (
    WebGame,
    _default_qualifying,
    _default_summary,
    _has_any_time,
    _passes_default_confidence,
    _sum_positive,
    _worst_hours,
)
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


class TestWorstHours:
    """Tests for _worst_hours (mirrors _stats worst-case selection)."""

    def test_completionist_dominates(self) -> None:
        """Test completionist dominates."""
        game = _gi(completionist_hours=30.0)
        assert _worst_hours(game, cache_hours=10.0, leisure=20.0) == 30.0

    def test_falls_back_to_cache_and_leisure_when_completionist_zero(self) -> None:
        """Test falls back to cache and leisure when completionist zero."""
        game = _gi(completionist_hours=0.0)
        assert _worst_hours(game, cache_hours=15.0, leisure=8.0) == 15.0

    def test_minus_one_when_all_non_positive(self) -> None:
        """Test minus one when all non positive."""
        game = _gi(completionist_hours=0.0)
        assert _worst_hours(game, cache_hours=-1.0, leisure=-1.0) == -1.0


class TestPassesDefaultConfidence:
    """Tests for _passes_default_confidence."""

    def test_fail_low_comp_100(self) -> None:
        """Test fail low comp 100."""
        assert _passes_default_confidence(_wg(comp_100_count=2)) is False

    def test_fail_low_count_comp(self) -> None:
        """Test fail low count comp."""
        assert _passes_default_confidence(_wg(comp_100_count=5, count_comp=10)) is False

    def test_pass_when_all_thresholds_met(self) -> None:
        """Test pass when all thresholds met."""
        assert _passes_default_confidence(_wg(comp_100_count=5, count_comp=20)) is True


class TestHasAnyTime:
    """Tests for _has_any_time."""

    def test_true_when_some_positive(self) -> None:
        """Test true when some positive."""
        assert _has_any_time(_wg(rush_hours=-1, leisure_hours=-1, worst_hours=5.0))

    def test_false_when_all_non_positive(self) -> None:
        """Test false when all non positive."""
        game = _wg(rush_hours=-1, leisure_hours=-1, worst_hours=-1)
        assert _has_any_time(game) is False


class TestDefaultQualifying:
    """Tests for _default_qualifying — each filter rejection branch."""

    def test_rejects_low_confidence(self) -> None:
        """Test rejects low confidence."""
        assert _default_qualifying([_wg(count_comp=0)]) == []

    def test_rejects_unplayable(self) -> None:
        """Test rejects unplayable."""
        game = _wg(protondb_tier="borked", protondb_trending_tier="borked")
        assert _default_qualifying([game]) == []

    def test_rejects_no_time(self) -> None:
        """Test rejects no time."""
        game = _wg(rush_hours=-1, leisure_hours=-1, worst_hours=-1)
        assert _default_qualifying([game]) == []

    def test_accepts_qualifying_game(self) -> None:
        """Test accepts qualifying game."""
        assert len(_default_qualifying([_wg()])) == 1


class TestSumPositive:
    """Tests for _sum_positive."""

    def test_sums_only_positive(self) -> None:
        """Test sums only positive."""
        rows = [_wg(rush_hours=10.0), _wg(rush_hours=-1.0), _wg(rush_hours=5.5)]
        assert _sum_positive(rows, "rush_hours") == 15.5

    def test_empty(self) -> None:
        """Test empty."""
        assert _sum_positive([], "rush_hours") == 0.0


class TestDefaultSummary:
    """Tests for _default_summary."""

    def test_totals(self) -> None:
        """Test totals."""
        rows = [_wg(rush_hours=10.0, leisure_hours=20.0, worst_hours=25.0)]
        summary = _default_summary(rows)
        assert summary.qualifying == 1
        assert summary.rush_total == 10.0
        assert summary.leisure_total == 20.0
        assert summary.worst_total == 25.0
