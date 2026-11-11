"""Shared stand-in earner (``piano``) and patch targets for the ledger-earner tests."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import earned_time

from steam_backlog_enforcer import _ledger_earners, _leetcode_bonus, _workout_budget

if TYPE_CHECKING:
    from collections.abc import Iterator

WORKOUT = "steam_backlog_enforcer._workout_budget._fetch_workout_today"
LEETCODE = "steam_backlog_enforcer._leetcode_bonus.read_ledger_solved_today"
ANSWER = "steam_backlog_enforcer._budget_resolve.ledger_answer"
HOUR = 3600.0


def any_credit(_row: dict[str, object], _window: tuple[float, float]) -> bool:
    """Count every verified credit: the reader's own dating is earned_time's."""
    return True


# A hypothetical earner: the real registry already holds anki, so the stand-in
# needs a name no gate uses.
PIANO = earned_time.Earner(
    name="piano",
    label="Piano",
    gaming_minutes=30,
    shutdown_minutes=30,
    ledger=".local/share/piano_guard/ledger.json",
    match=any_credit,
)


def _reset_earner_caches() -> None:
    """Empty every earner memo resolve_budget consults."""
    for module in (_ledger_earners, _workout_budget, _leetcode_bonus):
        module.reset_cache()


@contextmanager
def earner_caches_cleared() -> Iterator[None]:
    """Keep every earner memo from leaking answers into or out of the block."""
    _reset_earner_caches()
    yield
    _reset_earner_caches()
