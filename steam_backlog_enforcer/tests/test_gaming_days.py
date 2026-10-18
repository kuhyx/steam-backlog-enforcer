"""Tests for _gaming_days: the day boundary, the held budget, no carry-over."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._gaming_days import held_today
from steam_backlog_enforcer._playtime_budget import roll_over
from steam_backlog_enforcer._playtime_state import (
    PlaytimeRules,
    PlaytimeState,
    load_state,
    rules_for,
    state_path,
)
from steam_backlog_enforcer.config import Config

HOUR = 3600.0
LOCAL = timezone(timedelta(hours=2))
# 2026-10-01 is a Thursday.
THU, FRI, SAT, SUN, MON, TUE = (f"2026-10-{d:02d}" for d in range(1, 7))


class TestNoCarryOver:
    """Unspent time never moves to a later day (carry-over dropped 2026-10-18)."""

    def test_a_saturday_leftover_is_not_passed_on(self) -> None:
        sun = roll_over(
            PlaytimeState(day_key=SAT, seconds=HOUR, budget_seconds=8 * HOUR),
            day_key=SUN,
        )
        assert sun == PlaytimeState(day_key=SUN)
        assert "carry" not in vars(sun)

    def test_rules_have_no_carry(self) -> None:
        assert "carry_seconds" not in {f.name for f in fields(PlaytimeRules)}

    def test_a_legacy_carry_is_taken_out_of_todays_high_water(self) -> None:
        # The live file on 2026-10-18 held 6.0h earned + 9994s carried into the
        # day's high-water mark; held_today would otherwise keep paying it out.
        legacy = {
            "schema_version": 1,
            "day_key": SUN,
            "seconds": 6 * HOUR,
            "budget_seconds": 6 * HOUR + 9994.0,
            "carry": {SUN: 9994.0, MON: 9994.0},
        }
        state_path(demo=False).write_text(json.dumps(legacy), encoding="utf-8")
        stored = load_state(demo=False)
        assert stored is not None
        assert stored.budget_seconds == 6 * HOUR
        assert "carry" not in vars(stored)

    @pytest.mark.parametrize(
        "carry", [{MON: 9994.0}, {SUN: "9994"}, {SUN: 0.0}, [9994.0]]
    )
    def test_a_ledger_owing_today_nothing_leaves_the_budget(
        self, carry: object
    ) -> None:
        legacy = {
            "schema_version": 1,
            "day_key": SUN,
            "budget_seconds": 6 * HOUR,
            "carry": carry,
        }
        state_path(demo=False).write_text(json.dumps(legacy), encoding="utf-8")
        stored = load_state(demo=False)
        assert stored is not None
        assert stored.budget_seconds == 6 * HOUR


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
