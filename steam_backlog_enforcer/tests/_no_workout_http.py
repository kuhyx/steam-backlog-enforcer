"""Autouse stub for the earners-to-budget lookup.

``rules_for`` resolves the daily budget by asking the screen locker whether
today has a counted workout (loopback HTTP) and leetcode-guard whether a
problem was solved today (its ledger, then loopback HTTP). Left unstubbed,
every test that builds rules would make real requests and read the real
ledger: slow, and -- far worse -- answered differently depending on whether
those services happen to be running and whether the machine's owner has
trained or solved today. Tests would pass in the morning and fail in the
evening.

The stub returns the *fully earned* budget (base + both bonuses = 8h), which is
what every pre-coupling test was written against. Tests that care about a
coupling patch a level below this, at ``_workout_budget._fetch_workout_today``
or ``_leetcode_bonus.read_ledger_solved_today``.

Split out of ``conftest.py`` to keep every file inside the 250-line cap;
``conftest`` imports the fixture by name, which is what registers it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._budget_resolve import BudgetResolution

if TYPE_CHECKING:
    from collections.abc import Iterator

    from steam_backlog_enforcer.config import Config


def _earned_budget(config: Config) -> BudgetResolution:
    """Return the fully earned budget, as a day with both bonuses would.

    Args:
        config: Loaded user configuration.

    Returns:
        A resolution whose seconds are base plus both bonuses.
    """
    base = float(config.base_gaming_seconds)
    workout = float(config.workout_bonus_seconds)
    leetcode = float(config.leetcode_bonus_seconds)
    return BudgetResolution(
        seconds=base + workout + leetcode,
        base_seconds=base,
        workout_seconds=workout,
        leetcode_seconds=leetcode,
        reason="stubbed: fully earned",
    )


@pytest.fixture(autouse=True)
def _no_workout_http() -> Iterator[None]:
    """Stop rules_for from making a real HTTP call to the screen locker.

    Yields:
        None, with the budget resolver stubbed for the whole test.
    """
    with patch(
        "steam_backlog_enforcer._playtime_state.resolve_budget",
        side_effect=_earned_budget,
    ):
        yield
