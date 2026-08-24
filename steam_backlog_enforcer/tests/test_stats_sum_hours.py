"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from steam_backlog_enforcer._stats import (
    _format_completion_date,
    _GameTimes,
    _print_pace_scenario,
    _print_scenario,
    _sum_hours,
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


class TestSumHours:
    """Tests for _sum_hours."""

    def _make_entry(self, worst: float, rush: float, leisure: float) -> _GameTimes:
        """Test make entry."""
        return _GameTimes(
            game=_game(), worst_hours=worst, rush_hours=rush, leisure_100h=leisure
        )

    def test_empty_list(self) -> None:
        """Test empty list."""
        total, missing = _sum_hours([], "worst_hours")
        assert total == 0.0
        assert missing == 0

    def test_all_positive(self) -> None:
        """Test all positive."""
        entries = [
            self._make_entry(10.0, 8.0, 12.0),
            self._make_entry(20.0, 15.0, 25.0),
        ]
        total, missing = _sum_hours(entries, "worst_hours")
        assert total == 30.0
        assert missing == 0

    def test_some_negative(self) -> None:
        """Test some negative."""
        entries = [
            self._make_entry(10.0, -1.0, 12.0),
            self._make_entry(-1.0, 8.0, 25.0),
        ]
        total, missing = _sum_hours(entries, "worst_hours")
        assert total == 10.0
        assert missing == 1

    def test_all_negative(self) -> None:
        """Test all negative."""
        entries = [self._make_entry(-1.0, -1.0, -1.0)]
        total, missing = _sum_hours(entries, "rush_hours")
        assert total == 0.0
        assert missing == 1


class TestFormatCompletionDate:
    """Tests for _format_completion_date."""

    def test_zero_hours_returns_na(self) -> None:
        """Test zero hours returns na."""
        assert _format_completion_date(0.0, 4.0) == "N/A"

    def test_negative_hours_returns_na(self) -> None:
        """Test negative hours returns na."""
        assert _format_completion_date(-5.0, 4.0) == "N/A"

    def test_zero_daily_hours_returns_na(self) -> None:
        """Test zero daily hours returns na."""
        assert _format_completion_date(100.0, 0.0) == "N/A"

    def test_negative_daily_hours_returns_na(self) -> None:
        """Test negative daily hours returns na."""
        assert _format_completion_date(100.0, -1.0) == "N/A"

    def test_normal_returns_days_and_date(self) -> None:
        """Test normal returns days and date."""
        result = _format_completion_date(40.0, 4.0)
        # 40 / 4 = 10 days
        assert result.startswith("10 days (")
        assert ")" in result


class TestPrintScenario:
    """Tests for _print_scenario."""

    def test_no_data_prints_no_data_message(self) -> None:
        """Test no data prints no data message."""
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_scenario("2. RUSH", 0.0, 0, 5)
        assert any("No data available" in s for s in echoed)

    def test_with_data_no_missing(self) -> None:
        """Test with data no missing."""
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_scenario("2. RUSH", 100.0, 0, 5)
        assert any("Total:" in s for s in echoed)
        assert not any("had no data" in s for s in echoed)

    def test_with_data_and_missing(self) -> None:
        """Test with data and missing."""
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_scenario("2. RUSH", 100.0, 2, 5)
        assert any("had no data" in s for s in echoed)


class TestPrintPaceScenario:
    """Tests for _print_pace_scenario."""

    def test_no_start_date(self) -> None:
        """Test no start date."""
        state = State()
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_pace_scenario(state, 10, 0)
        assert any("No start date recorded" in s for s in echoed)

    def test_invalid_start_date(self) -> None:
        """Test invalid start date."""
        state = State(enforcement_started_at="not-a-date")
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_pace_scenario(state, 10, 0)
        assert any("Invalid enforcement_started_at" in s for s in echoed)

    def test_no_games_finished(self) -> None:
        """Test no games finished."""
        started = datetime.now(timezone.utc) - timedelta(days=30)
        state = State(enforcement_started_at=started.isoformat())
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_pace_scenario(state, 10, 0)
        assert any("No games finished yet" in s for s in echoed)

    def test_normal_pace(self) -> None:
        """Test normal pace."""
        started = datetime.now(timezone.utc) - timedelta(days=60)
        state = State(enforcement_started_at=started.isoformat())
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_pace_scenario(state, 5, 3)
        assert any("Pace:" in s for s in echoed)
        assert any("Est. complete:" in s for s in echoed)
