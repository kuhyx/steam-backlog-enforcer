"""Tests for _budget_resolve: the floor plus what today earned.

The matrix is the point of this file. Two independent earners give four days,
and the two properties that must hold across all of them are that the sum is
additive (never a choice between two absolutes) and that *not knowing* an
answer is worth exactly as much as a "no" -- never more.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _leetcode_bonus, _workout_budget
from steam_backlog_enforcer._budget_resolve import resolve_budget
from steam_backlog_enforcer.config import Config

if TYPE_CHECKING:
    from collections.abc import Iterator

_WORKOUT = "steam_backlog_enforcer._workout_budget._fetch_workout_today"
_LEETCODE = "steam_backlog_enforcer._leetcode_bonus.read_ledger_solved_today"
_LEETCODE_HTTP = "steam_backlog_enforcer._leetcode_bonus._fetch_leetcode_today"

_HOUR = 3600.0


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


class TestTheFourDays:
    """Every combination of the two earners, in hours."""

    @pytest.mark.parametrize(
        ("earners", "expected_hours"),
        [
            ((False, False), 5.0),
            ((False, True), 6.0),
            ((True, False), 7.0),
            ((True, True), 8.0),
        ],
    )
    def test_the_budget_is_the_sum(
        self,
        earners: tuple[bool, bool],
        expected_hours: float,
    ) -> None:
        """5h floor, +2h for a workout, +1h for a solve, in every combination.

        Args:
            earners: Whether the workout and the LeetCode solve happened.
            expected_hours: The budget those two should produce.
        """
        workout, leetcode = earners
        with (
            patch(_WORKOUT, return_value=workout),
            patch(_LEETCODE, return_value=leetcode),
        ):
            resolved = resolve_budget(Config())
        assert resolved.seconds == expected_hours * _HOUR

    def test_the_breakdown_matches_the_total(self) -> None:
        """The parts a caller displays must add up to the number enforced."""
        with patch(_WORKOUT, return_value=True), patch(_LEETCODE, return_value=True):
            resolved = resolve_budget(Config())
        assert (
            resolved.base_seconds + resolved.workout_seconds + resolved.leetcode_seconds
            == resolved.seconds
        )


class TestFailingClosed:
    """An answer that could not be obtained is worth nothing, and says so."""

    def test_an_unreachable_locker_costs_only_the_workout_bonus(self) -> None:
        """A dead screen locker must not also cost the LeetCode hour."""
        with (
            patch(_WORKOUT, side_effect=OSError("refused")),
            patch(_LEETCODE, return_value=True),
        ):
            resolved = resolve_budget(Config())
        assert resolved.seconds == 6.0 * _HOUR
        assert resolved.leetcode_seconds == _HOUR

    def test_an_unreadable_ledger_costs_only_the_leetcode_bonus(self) -> None:
        """The whole point of the split: LeetCode failing leaves 7h, not 5h."""
        with (
            patch(_WORKOUT, return_value=True),
            patch(_LEETCODE, return_value=None),
            patch(_LEETCODE_HTTP, side_effect=OSError("refused")),
        ):
            resolved = resolve_budget(Config())
        assert resolved.seconds == 7.0 * _HOUR
        assert resolved.workout_seconds == 2 * _HOUR

    def test_both_unavailable_leaves_the_bare_floor(self) -> None:
        """Neither earner answering can never grant more than the floor."""
        with (
            patch(_WORKOUT, side_effect=OSError("refused")),
            patch(_LEETCODE, return_value=None),
            patch(_LEETCODE_HTTP, side_effect=OSError("refused")),
        ):
            resolved = resolve_budget(Config())
        assert resolved.seconds == 5.0 * _HOUR

    def test_unknown_is_reported_differently_from_no(self) -> None:
        """ "Could not check" and "not earned" must not read the same."""
        with (
            patch(_WORKOUT, return_value=False),
            patch(_LEETCODE, return_value=None),
            patch(_LEETCODE_HTTP, side_effect=OSError("refused")),
        ):
            unknown = resolve_budget(Config()).reason
        _leetcode_bonus.reset_cache()
        _workout_budget.reset_cache()
        with patch(_WORKOUT, return_value=False), patch(_LEETCODE, return_value=False):
            answered = resolve_budget(Config()).reason
        assert unknown != answered
        assert "unknown" in unknown
        assert "unknown" not in answered


class TestMisconfiguration:
    """Config that would invert the incentive is refused, not enforced."""

    def test_a_negative_bonus_is_clamped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Earning something must never *cost* gaming time.

        Args:
            caplog: pytest's log capture.
        """
        config = Config(workout_bonus_seconds=-3600)
        with (
            caplog.at_level(logging.ERROR),
            patch(_WORKOUT, return_value=True),
            patch(_LEETCODE, return_value=False),
        ):
            resolved = resolve_budget(config)
        assert resolved.seconds == 5.0 * _HOUR
        assert "workout_bonus_seconds is negative" in caplog.text

    def test_the_budget_is_explained(self, caplog: pytest.LogCaptureFixture) -> None:
        """A three-hour swing between days should never be silent.

        Args:
            caplog: pytest's log capture.
        """
        with (
            caplog.at_level(logging.INFO),
            patch(_WORKOUT, return_value=False),
            patch(_LEETCODE, return_value=False),
        ):
            resolve_budget(Config())
        assert "5.0h" in caplog.text
        assert "no counted workout" in caplog.text
        assert "no LeetCode solve recorded" in caplog.text
