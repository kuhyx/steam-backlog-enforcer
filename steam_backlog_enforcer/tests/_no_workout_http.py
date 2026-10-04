"""Autouse stub for the earners-to-budget lookup.

``rules_for`` resolves the daily budget by asking the screen locker whether
today has a counted workout (loopback HTTP) and leetcode-guard whether a
problem was solved today (its ledger, then loopback HTTP). Left unstubbed,
every test that builds rules would make real requests and read the real
ledger: slow, and -- far worse -- answered differently depending on whether
those services happen to be running and whether the machine's owner has
trained or solved today. Tests would pass in the morning and fail in the
evening.

The stub returns the *fully earned* budget (base + every registered earner,
capped at the 8h ceiling), which is what every pre-coupling test was written
against. Tests that need an exact budget use :func:`fixed_budget`; tests that
care about a coupling patch a level below this, at
``_workout_budget._fetch_workout_today`` or
``_leetcode_bonus.read_ledger_solved_today``.

Split out of ``conftest.py`` to keep every file inside the 250-line cap;
``conftest`` imports the fixture by name, which is what registers it.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import earned_time
import pytest

from steam_backlog_enforcer._budget_resolve import BudgetResolution

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from steam_backlog_enforcer.config import Config

_RESOLVER = "steam_backlog_enforcer._playtime_state.resolve_budget"
_MINUTE = 60.0


def earned_budget(_config: Config) -> BudgetResolution:
    """Return the fully earned budget, as a day with every bonus would.

    The numbers come from the ``earned_time`` registry: today's base plus every
    registered earner's term, capped at the gaming ceiling.

    Args:
        _config: Loaded user configuration (unused; the registry decides).

    Returns:
        A resolution whose seconds are base plus every bonus.
    """
    base = earned_time.base_for(datetime.now().astimezone().date()).gaming_minutes
    earned = {e.name: e.gaming_minutes * _MINUTE for e in earned_time.EARNERS}
    ceiling = earned_time.GAMING_CEILING_MINUTES * _MINUTE
    total = min(ceiling, base * _MINUTE + sum(earned.values()))
    return BudgetResolution(
        seconds=total,
        base_seconds=base * _MINUTE,
        workout_seconds=earned.get("workout", 0.0),
        leetcode_seconds=earned.get("leetcode", 0.0),
        reason="stubbed: fully earned",
        reading_seconds=earned.get("reading", 0.0),
        earned_seconds=earned,
    )


def fixed_budget(seconds: float) -> AbstractContextManager[object]:
    """Make ``rules_for`` resolve exactly ``seconds``, all of it base.

    For tests that need a budget the registry's whole minutes cannot express
    (100s, 0s, ...).

    Args:
        seconds: The budget to resolve.

    Returns:
        A patch context manager replacing the resolver ``rules_for`` calls.
    """
    resolution = BudgetResolution(
        seconds=seconds,
        base_seconds=seconds,
        workout_seconds=0.0,
        leetcode_seconds=0.0,
        reason="stubbed: fixed",
    )
    return patch(_RESOLVER, return_value=resolution)


@pytest.fixture(autouse=True)
def _no_workout_http() -> Iterator[None]:
    """Stop rules_for from making a real HTTP call to the screen locker.

    Yields:
        None, with the budget resolver stubbed for the whole test.
    """
    with patch(_RESOLVER, side_effect=earned_budget):
        yield
