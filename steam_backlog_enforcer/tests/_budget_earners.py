"""Shared seams for the budget tests: the earner patch targets and a resolver.

Each earner is overridden where ``resolve_budget`` reads it, so a test can fix
the workout, LeetCode and reading answers without any network or ledger.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._budget_resolve import BudgetResolution, resolve_budget
from steam_backlog_enforcer.config import Config

WORKOUT = "steam_backlog_enforcer._workout_budget._fetch_workout_today"
LEETCODE = "steam_backlog_enforcer._leetcode_bonus.read_ledger_solved_today"
READING = "steam_backlog_enforcer._budget_resolve.read_today"

HOUR = 3600.0


def resolve_with(
    *,
    workout: bool,
    leetcode: bool,
    reading: bool | None,
) -> BudgetResolution:
    """Resolve the default config's budget with all three earners fixed.

    Args:
        workout: Whether today's workout happened.
        leetcode: Whether today's LeetCode solve happened.
        reading: Whether today's reading happened (None: unknown).

    Returns:
        The resolved budget.
    """
    with (
        patch(WORKOUT, return_value=workout),
        patch(LEETCODE, return_value=leetcode),
        patch(READING, return_value=reading),
    ):
        return resolve_budget(Config())
