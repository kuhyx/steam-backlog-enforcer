"""Tests for the reading term, the 8h ceiling and the dated 5h -> 4h base cut.

Split from ``test_budget_resolve.py`` to keep both inside the 250-line cap.
The reading earner is overridden at the consumer binding, the same seam the
autouse ``_isolate_reading`` fixture stubs to "no reading".
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import earned_time
import pytest

from steam_backlog_enforcer import _budget_view as view
from steam_backlog_enforcer import _leetcode_bonus, _workout_budget
from steam_backlog_enforcer._budget_resolve import (
    BudgetResolution,
    resolve_budget,
)
from steam_backlog_enforcer._ledger_earners import registry_for
from steam_backlog_enforcer._playtime_state import rules_for
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._budget_dates import (
    AFTER_CUT,
    BEFORE_CUT,
    pin_today,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import date

_WORKOUT = "steam_backlog_enforcer._workout_budget._fetch_workout_today"
_LEETCODE = "steam_backlog_enforcer._leetcode_bonus.read_ledger_solved_today"
_READING = "steam_backlog_enforcer._budget_resolve.read_today"

_HOUR = 3600.0


def _later_penalised(day: date) -> list[earned_time.Earner]:
    """Earners in force on ``day`` whose penalty starts after reading's cut."""
    cut = earned_time.READING.penalty_from
    assert cut is not None
    return [
        e
        for e in registry_for(day)
        if e.penalty_from is not None and cut < e.penalty_from <= day
    ]


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    """Keep both module memos from leaking answers between tests.

    Yields:
        None, with both caches empty before and after.
    """
    _workout_budget.reset_cache()
    _leetcode_bonus.reset_cache()
    yield
    _workout_budget.reset_cache()
    _leetcode_bonus.reset_cache()


def _resolve(*, earners: tuple[bool, bool, bool | None]) -> BudgetResolution:
    """Resolve with the workout, LeetCode and reading answers fixed.

    Args:
        earners: The workout, LeetCode and reading answers.

    Returns:
        The resolved budget.
    """
    workout, leetcode, reading = earners
    with (
        patch(_WORKOUT, return_value=workout),
        patch(_LEETCODE, return_value=leetcode),
        patch(_READING, return_value=reading),
    ):
        return resolve_budget(Config())


class TestTheBase:
    """The floor carries the old extra hour until book-guard's gate starts."""

    def test_the_day_before_the_cut_keeps_the_old_floor(self) -> None:
        """The day before still gets the hour reading cannot yet earn back."""
        with pin_today(BEFORE_CUT):
            resolved = _resolve(earners=(False, False, False))
        assert resolved.base_seconds == 5 * _HOUR

    def test_the_cut_day_itself_uses_the_lower_floor(self) -> None:
        """The boundary is inclusive: the penalty start is the first 4h day."""
        with pin_today(AFTER_CUT):
            resolved = _resolve(earners=(False, False, False))
        assert resolved.base_seconds == 4 * _HOUR

    def test_every_later_day_uses_the_lower_floor(self) -> None:
        """No drift back to 5h once the cut has happened.

        A year on, every later earner's cut in force that day is applied too --
        summed from that day's registry, so a new or waived earner needs no
        edit here.
        """
        day = AFTER_CUT + timedelta(days=400)
        with pin_today(day):
            resolved = _resolve(earners=(False, False, False))
        later_cuts = 60 * sum(e.gaming_minutes for e in _later_penalised(day))
        assert resolved.base_seconds == 4 * _HOUR - later_cuts


class TestTheReadingTerm:
    """Reading adds one hour, and an unknown answer adds nothing."""

    def test_credited_reading_adds_the_hour(self) -> None:
        with pin_today(AFTER_CUT):
            resolved = _resolve(earners=(False, False, True))
        assert resolved.reading_seconds == _HOUR
        assert resolved.seconds == 5 * _HOUR
        assert "reading credited" in resolved.reason

    def test_no_reading_adds_nothing(self) -> None:
        with pin_today(AFTER_CUT):
            resolved = _resolve(earners=(False, False, False))
        assert resolved.reading_seconds == 0.0
        assert resolved.seconds == 4 * _HOUR
        assert "no reading credited" in resolved.reason

    def test_an_unreadable_ledger_costs_only_the_reading_hour(self) -> None:
        """Fail closed, independently: the other terms are untouched."""
        with pin_today(AFTER_CUT):
            resolved = _resolve(earners=(True, True, None))
        assert resolved.reading_seconds == 0.0
        assert resolved.workout_seconds == 2 * _HOUR
        assert resolved.leetcode_seconds == _HOUR
        assert resolved.seconds == 7 * _HOUR
        assert "reading unknown (book-guard ledger unreadable)" in resolved.reason


class TestTheCeiling:
    """Whatever the terms add up to, the budget never exceeds the maximum."""

    def test_before_the_cut_a_full_day_is_capped_at_eight_hours(self) -> None:
        """5h + 2h + 1h + 1h is 9h; 8h is what gets enforced."""
        with pin_today(BEFORE_CUT):
            resolved = _resolve(earners=(True, True, True))
        assert resolved.base_seconds == 5 * _HOUR
        assert resolved.seconds == 8 * _HOUR
        assert resolved.reason.startswith("8.0h: ")

    def test_before_the_cut_an_idle_day_keeps_five_hours(self) -> None:
        with pin_today(BEFORE_CUT):
            resolved = _resolve(earners=(False, False, False))
        assert resolved.seconds == 5 * _HOUR

    def test_a_lower_registry_ceiling_binds(self) -> None:
        """The ceiling is the registry's, read when the budget resolves."""
        with (
            pin_today(AFTER_CUT),
            # resolve() binds the ceiling from _policy by name, so patch there.
            patch("earned_time._resolve.GAMING_CEILING_MINUTES", 6 * 60),
        ):
            resolved = _resolve(earners=(True, True, True))
        assert resolved.seconds == 6 * _HOUR

    def test_after_the_cut_a_full_day_is_exactly_the_ceiling(self) -> None:
        with pin_today(AFTER_CUT):
            resolved = _resolve(earners=(True, True, True))
        ceiling = earned_time.GAMING_CEILING_MINUTES * 60
        assert resolved.seconds == ceiling == 8 * _HOUR


class TestReadingReachesTheRulesAndTheView:
    """The resolved reading hour is carried, never re-resolved."""

    def test_rules_and_bonuses_carry_the_reading_seconds(self) -> None:
        resolution = BudgetResolution(
            seconds=5 * _HOUR,
            base_seconds=4 * _HOUR,
            workout_seconds=0.0,
            leetcode_seconds=0.0,
            reason="stub",
            reading_seconds=_HOUR,
        )
        with patch(
            "steam_backlog_enforcer._playtime_state.resolve_budget",
            return_value=resolution,
        ):
            rules = rules_for(Config(), demo=False)
        assert rules.reading_seconds == _HOUR
        with patch.object(view, "mounted_targets", return_value=set()):
            bonuses = view.build_rules(rules)["bonuses"]
        assert bonuses["reading"] == _HOUR

    def test_a_demo_run_earns_no_reading(self) -> None:
        assert rules_for(Config(), demo=True).reading_seconds == 0.0

    def test_a_resolution_defaults_to_no_reading(self) -> None:
        resolution = BudgetResolution(
            seconds=0.0,
            base_seconds=0.0,
            workout_seconds=0.0,
            leetcode_seconds=0.0,
            reason="",
        )
        assert resolution.reading_seconds == 0.0
