"""Tests for _budget_resolve: the floor plus what today earned.

The matrix is the point of this file. Three independent earners give eight
days, and the two properties that must hold across all of them are that the sum is
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
from steam_backlog_enforcer.tests._budget_dates import AFTER_CUT, pin_today

if TYPE_CHECKING:
    from collections.abc import Iterator

_WORKOUT = "steam_backlog_enforcer._workout_budget._fetch_workout_today"
_LEETCODE = "steam_backlog_enforcer._leetcode_bonus.read_ledger_solved_today"
_LEETCODE_HTTP = "steam_backlog_enforcer._leetcode_bonus._fetch_leetcode_today"
_READING = "steam_backlog_enforcer._budget_resolve.read_today"

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


@pytest.fixture(autouse=True)
def _after_the_cut() -> Iterator[None]:
    """Resolve as on a day past the 5h -> 4h cut, whatever the real date.

    Yields:
        None, with today's date pinned inside ``_budget_resolve``.
    """
    with pin_today(AFTER_CUT):
        yield


class TestTheEightDays:
    """Every combination of the three earners, in hours."""

    @pytest.mark.parametrize(
        ("earners", "expected_hours"),
        [
            ((False, False, False), 4.0),
            ((False, False, True), 5.0),
            ((False, True, False), 5.0),
            ((False, True, True), 6.0),
            ((True, False, False), 6.0),
            ((True, False, True), 7.0),
            ((True, True, False), 7.0),
            ((True, True, True), 8.0),
        ],
    )
    def test_the_budget_is_the_sum(
        self,
        earners: tuple[bool, bool, bool],
        expected_hours: float,
    ) -> None:
        """4h floor, +2h workout, +1h solve, +1h reading, in every combination.

        Args:
            earners: Whether the workout, the solve and the reading happened.
            expected_hours: The budget those three should produce.
        """
        workout, leetcode, reading = earners
        with (
            patch(_WORKOUT, return_value=workout),
            patch(_LEETCODE, return_value=leetcode),
            patch(_READING, return_value=reading),
        ):
            resolved = resolve_budget(Config())
        assert resolved.seconds == expected_hours * _HOUR

    def test_the_breakdown_matches_the_total(self) -> None:
        """The parts a caller displays must add up to the number enforced."""
        with (
            patch(_WORKOUT, return_value=True),
            patch(_LEETCODE, return_value=True),
            patch(_READING, return_value=True),
        ):
            resolved = resolve_budget(Config())
        assert (
            resolved.base_seconds
            + resolved.workout_seconds
            + resolved.leetcode_seconds
            + resolved.reading_seconds
            == resolved.seconds
        )

    def test_every_earner_is_in_the_generic_breakdown(self) -> None:
        """``earned_seconds`` carries the same terms as the named fields."""
        with (
            patch(_WORKOUT, return_value=True),
            patch(_LEETCODE, return_value=False),
            patch(_READING, return_value=True),
        ):
            resolved = resolve_budget(Config())
        assert resolved.earned_seconds == {
            "workout": 2 * _HOUR,
            "leetcode": 0.0,
            "reading": _HOUR,
        }


class TestFailingClosed:
    """An answer that could not be obtained is worth nothing, and says so."""

    def test_an_unreachable_locker_costs_only_the_workout_bonus(self) -> None:
        """A dead screen locker must not also cost the LeetCode hour."""
        with (
            patch(_WORKOUT, side_effect=OSError("refused")),
            patch(_LEETCODE, return_value=True),
        ):
            resolved = resolve_budget(Config())
        assert resolved.seconds == 5.0 * _HOUR
        assert resolved.leetcode_seconds == _HOUR

    def test_an_unreadable_ledger_costs_only_the_leetcode_bonus(self) -> None:
        """The whole point of the split: LeetCode failing leaves 6h, not 4h."""
        with (
            patch(_WORKOUT, return_value=True),
            patch(_LEETCODE, return_value=None),
            patch(_LEETCODE_HTTP, side_effect=OSError("refused")),
        ):
            resolved = resolve_budget(Config())
        assert resolved.seconds == 6.0 * _HOUR
        assert resolved.workout_seconds == 2 * _HOUR

    def test_both_unavailable_leaves_the_bare_floor(self) -> None:
        """Neither earner answering can never grant more than the floor."""
        with (
            patch(_WORKOUT, side_effect=OSError("refused")),
            patch(_LEETCODE, return_value=None),
            patch(_LEETCODE_HTTP, side_effect=OSError("refused")),
        ):
            resolved = resolve_budget(Config())
        assert resolved.seconds == 4.0 * _HOUR

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


class TestTheExplanation:
    """The reason string and the per-earner breakdown."""

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
        assert "4.0h" in caplog.text
        assert "no counted workout" in caplog.text
        assert "no LeetCode solve recorded" in caplog.text
        assert "no reading credited" in caplog.text
