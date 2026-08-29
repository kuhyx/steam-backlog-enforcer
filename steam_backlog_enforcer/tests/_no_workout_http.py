"""Autouse stub for the workout-to-budget lookup.

``rules_for`` resolves the daily budget by asking the screen locker whether
today has a counted workout, over loopback HTTP. Left unstubbed, every test
that builds rules would make a real request: slow, and -- far worse --
answered differently depending on whether ``screen-locker-web.service`` happens
to be running and whether the machine's owner has trained today. Tests would
pass in the morning and fail in the evening.

The stub returns the *earned* budget, which is what every pre-coupling test was
written against. Tests that care about the coupling patch a level below this,
at ``_workout_budget._fetch_workout_today``.

Split out of ``conftest.py`` to keep every file inside the 250-line cap;
``conftest`` imports the fixture by name, which is what registers it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from steam_backlog_enforcer.config import Config


def _earned_budget(config: Config) -> float:
    """Return the earned budget, as a day with a logged workout would.

    Args:
        config: Loaded user configuration.

    Returns:
        ``daily_gaming_seconds`` as a float.
    """
    return float(config.daily_gaming_seconds)


@pytest.fixture(autouse=True)
def _no_workout_http() -> Iterator[None]:
    """Stop rules_for from making a real HTTP call to the screen locker.

    Yields:
        None, with the budget resolver stubbed for the whole test.
    """
    with patch(
        "steam_backlog_enforcer._playtime_state.resolve_budget_seconds",
        side_effect=_earned_budget,
    ):
        yield
