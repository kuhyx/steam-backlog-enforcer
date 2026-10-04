"""Tests for the Friday-Monday carry-over in _gaming_days."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from steam_backlog_enforcer._gaming_days import (
    carry_due,
    carry_into,
    held_today,
    pass_on,
)
from steam_backlog_enforcer._playtime_budget import roll_over
from steam_backlog_enforcer._playtime_state import PlaytimeState, rules_for
from steam_backlog_enforcer.config import Config

HOUR = 3600.0
LOCAL = timezone(timedelta(hours=2))
# 2026-10-01 is a Thursday.
THU, FRI, SAT, SUN, MON, TUE = (f"2026-10-{d:02d}" for d in range(1, 7))


def _leftover(day: str, *, budget: float, spent: float, new_day: str) -> dict:
    return pass_on({}, outgoing_day=day, budget=budget, spent=spent, new_day=new_day)


class TestPassOn:
    """Who inherits a day's unspent budget."""

    def test_friday_splits_three_ways(self) -> None:
        owed = _leftover(FRI, budget=8 * HOUR, spent=7 * HOUR, new_day=SAT)
        assert owed == {SAT: 1200.0, SUN: 1200.0, MON: 1200.0}

    def test_saturday_splits_two_ways(self) -> None:
        owed = _leftover(SAT, budget=8 * HOUR, spent=7 * HOUR, new_day=SUN)
        assert owed == {SUN: 1800.0, MON: 1800.0}

    def test_sunday_goes_to_monday(self) -> None:
        assert _leftover(SUN, budget=HOUR, spent=0.0, new_day=MON) == {MON: HOUR}

    def test_monday_and_weekdays_drop_their_leftover(self) -> None:
        assert _leftover(MON, budget=HOUR, spent=0.0, new_day=TUE) == {}
        assert _leftover(THU, budget=HOUR, spent=0.0, new_day=FRI) == {}

    def test_overspent_day_carries_nothing(self) -> None:
        owed = _leftover(SUN, budget=HOUR, spent=2 * HOUR, new_day=MON)
        assert owed == {MON: 0.0}

    def test_no_outgoing_day_keeps_only_future_shares(self) -> None:
        owed = pass_on(
            {FRI: 5.0, SUN: 7.0}, outgoing_day="", budget=0.0, spent=0.0, new_day=SAT
        )
        assert owed == {SUN: 7.0}

    def test_a_skipped_day_forfeits_its_share(self) -> None:
        owed = _leftover(FRI, budget=3 * HOUR, spent=0.0, new_day=SUN)
        assert owed == {SUN: HOUR, MON: HOUR}

    def test_shares_accumulate_with_earlier_ones(self) -> None:
        owed = pass_on(
            {SUN: 600.0, MON: 600.0},
            outgoing_day=SAT,
            budget=HOUR,
            spent=0.0,
            new_day=SUN,
        )
        assert owed == {SUN: 2400.0, MON: 2400.0}


class TestCarryDue:
    """Today's share, whether or not the stored record has rolled over."""

    def test_same_day_reads_the_ledger(self) -> None:
        due = carry_due({SAT: 60.0}, stored_day=SAT, budget=0.0, spent=0.0, today=SAT)
        assert due == 60.0

    def test_stale_record_is_projected_forward(self) -> None:
        due = carry_due({}, stored_day=FRI, budget=4 * HOUR, spent=HOUR, today=SAT)
        assert due == HOUR


class TestCarryInto:
    """Reading the carry off a stored state."""

    def test_no_state_means_no_carry(self) -> None:
        assert carry_into(None, datetime(2026, 10, 3, 10, tzinfo=LOCAL)) == 0.0

    def test_reads_the_projected_share(self) -> None:
        stored = PlaytimeState(day_key=FRI, seconds=HOUR, budget_seconds=4 * HOUR)
        assert carry_into(stored, datetime(2026, 10, 3, 10, tzinfo=LOCAL)) == HOUR


class TestRollOverCarry:
    """roll_over threads the ledger across the 06:00 boundary."""

    def test_unspent_carry_moves_on(self) -> None:
        sat = roll_over(
            PlaytimeState(day_key=FRI, seconds=7 * HOUR, budget_seconds=8 * HOUR),
            day_key=SAT,
        )
        sat = replace(sat, seconds=8 * HOUR, budget_seconds=8 * HOUR + 1200.0)
        sun = roll_over(sat, day_key=SUN)
        assert sun.carry == {SUN: 1800.0, MON: 1800.0}


class TestRulesCarry:
    """rules_for adds the carry above the cap and says so."""

    def test_carry_lands_in_budget_and_reason(self) -> None:
        with patch(
            "steam_backlog_enforcer._playtime_state.carry_into", return_value=1200.0
        ):
            rules = rules_for(Config(), demo=False)
        assert rules.carry_seconds == 1200.0
        assert rules.budget_reason.endswith(", +20m carried over")

    def test_demo_never_carries(self) -> None:
        with patch(
            "steam_backlog_enforcer._playtime_state.carry_into", return_value=1200.0
        ):
            assert rules_for(Config(), demo=True).carry_seconds == 0.0


class TestHeldToday:
    """The day's high-water budget, and only for the day it was recorded."""

    NOW = datetime(2026, 10, 5, 0, 30, tzinfo=LOCAL)  # still gaming day SUN

    def test_no_state_holds_nothing(self) -> None:
        assert held_today(None, self.NOW) == 0.0

    def test_same_gaming_day_returns_the_high_water(self) -> None:
        stored = PlaytimeState(day_key=SUN, budget_seconds=8 * HOUR)
        assert held_today(stored, self.NOW) == 8 * HOUR

    def test_yesterdays_record_holds_nothing(self) -> None:
        stored = PlaytimeState(day_key=SAT, budget_seconds=8 * HOUR)
        assert held_today(stored, self.NOW) == 0.0


class TestRulesHold:
    """rules_for never prices the day below what it already granted."""

    def test_midnight_reset_is_held_and_says_so(self) -> None:
        with patch(
            "steam_backlog_enforcer._playtime_state.held_today",
            return_value=10 * HOUR,
        ):
            rules = rules_for(Config(), demo=False)
        assert rules.budget_seconds == 10 * HOUR
        assert rules.budget_reason.endswith("; held at 10.0h (earned earlier today)")

    def test_a_higher_live_answer_wins_silently(self) -> None:
        with patch(
            "steam_backlog_enforcer._playtime_state.held_today", return_value=HOUR
        ):
            rules = rules_for(Config(), demo=False)
        assert rules.budget_seconds > HOUR
        assert "held at" not in rules.budget_reason
