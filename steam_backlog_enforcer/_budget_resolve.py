"""Today's gaming budget: a floor, plus whatever today earned.

Every number lives in the shared earner registry (``earned_time``,
kuhyx/utils), which screen-locker reads for the shutdown time too. The budget
is its sum, capped at the gaming ceiling (8h):

    base (4h) + workout (2h) + LeetCode (1h) + reading (1h) + ...

The base is 5h minus every penalised earner's cut once its day arrives
(book-guard's reading hour, from 2026-10-01) -- and, from earned_time 0.6, not
before the day after the gate's first real credit
(:func:`steam_backlog_enforcer._ledger_earners.first_credits`). The earners are read
**independently** -- :mod:`steam_backlog_enforcer._workout_budget`,
:mod:`steam_backlog_enforcer._leetcode_bonus`,
:mod:`steam_backlog_enforcer._reading_bonus` and, for any earner registered
later, :mod:`steam_backlog_enforcer._ledger_earners` share no state and none
can fail in a way that changes another's term. That is what "the LeetCode
bonus must not interfere with the workout" means in code.

**Fail closed.** An answer that could not be obtained contributes nothing, the
same as a "no". The difference is only in what gets reported: an unreadable
LeetCode ledger raises an incident, an honest "not solved yet" does not.

**Rising, and held there.** Every earner only ever goes false->true within a
day, so in the ordinary case the budget starts at the floor and rises. This
resolution alone does not guarantee it: earners reset at calendar midnight
while the gaming day runs to 05:59, and a cold restart resolves with empty
answer caches, so a live answer can come in lower than one given hours ago.
That bit twice (2026-10-03 and 2026-10-04 00:00, 8h -> 4h, unwarned cutoff).
``PlaytimeState.budget_seconds`` is the day's high-water mark, and
``rules_for`` applies ``max(resolved + carry, held)`` via
``_gaming_days.held_today`` -- so the daemon, ``/api/budget`` and MCP all see
the held figure. Only the 06:00 roll-over lowers it.

**One seam.** :func:`resolve_budget` is called from ``rules_for`` and nowhere
else, so the enforcing daemon and the read-only HTTP/MCP views resolve the same
number. Callers that want the breakdown read it off ``PlaytimeRules``, never by
resolving a second time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Final

import earned_time

from steam_backlog_enforcer._ledger_earners import (
    first_credits,
    ledger_answer,
    ledger_units,
    registry_for,
)
from steam_backlog_enforcer._leetcode_bonus import leetcode_solved_today
from steam_backlog_enforcer._reading_bonus import read_today
from steam_backlog_enforcer._workout_budget import workout_logged_today

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

_SECONDS_PER_MINUTE: Final = 60.0
_SECONDS_PER_HOUR: Final = 3600.0

# How each earner reads in the reason string: (earned, missed, unknown).
# An earner registered later without an entry here gets a generic phrase.
_PHRASES: Final[dict[str, tuple[str, str, str]]] = {
    "workout": (
        "workout counted",
        "no counted workout",
        "workout unknown (screen-locker unreachable)",
    ),
    "leetcode": (
        "LeetCode solve recorded",
        "no LeetCode solve recorded",
        "LeetCode unknown (ledger and status API both unreadable)",
    ),
    "reading": (
        "reading credited",
        "no reading credited",
        "reading unknown (book-guard ledger unreadable)",
    ),
}


@dataclass(frozen=True)
class BudgetResolution:
    """Today's budget, and what earned it.

    Attributes:
        seconds: The budget to enforce.
        base_seconds: The floor before any bonus.
        workout_seconds: Seconds added by a counted workout, or 0.
        leetcode_seconds: Seconds added by a LeetCode solve, or 0.
        reason: A human-readable account, for the journal and ``/api/budget``.
        reading_seconds: Seconds added by a credited reading session, or 0.
        earned_seconds: Seconds added per earner name, every registered earner
            included -- the generic form of the three fields above.
    """

    seconds: float
    base_seconds: float
    workout_seconds: float
    leetcode_seconds: float
    reason: str
    reading_seconds: float = 0.0
    earned_seconds: dict[str, float] = field(default_factory=dict)


def _describe(name: str, label: str, answer: int | None) -> str:
    """Render one earner's answer (units, for a counted gate) for the reason."""
    earned, missed, unknown = _PHRASES.get(
        name, (f"{label} credited", f"no {label} credited", f"{label} unknown")
    )
    if answer is None:
        return unknown
    if not answer:
        return missed
    return earned if answer == 1 else f"{earned} x{answer}"


def _answers(
    config: Config, registry: tuple[earned_time.Earner, ...]
) -> dict[str, int | bool | None]:
    """Every registered earner's answer for today, each read independently.

    A counted gate (the Automation tutor) answers with its units today.
    """
    answers: dict[str, int | bool | None] = {
        "workout": workout_logged_today(config),
        "leetcode": leetcode_solved_today(config),
        "reading": read_today(config),
    }
    for earner in registry:
        if earner.name not in answers:
            answers[earner.name] = (
                ledger_units(earner)
                if earner.kind == "counted"
                else ledger_answer(earner)
            )
    return answers


def resolve_budget(config: Config) -> BudgetResolution:
    """Return today's gaming budget, and what earned it.

    Args:
        config: Loaded user configuration (for the earners' transports).

    Returns:
        The floor plus a bonus for each of today's earners. An answer that
        could not be obtained contributes nothing, exactly as a "no" does --
        the difference is only in what gets logged and reported.
    """
    # The registry is passed explicitly: _answers iterated this same tuple, so
    # the earners asked and the earners summed can never differ.
    today = datetime.now().astimezone().date()
    registry = registry_for(today)
    answers = _answers(config, registry)
    # Maturity only delays a penalty: a gate that never paid out costs nothing.
    first_paid = first_credits(registry, today)
    day = (
        earned_time.resolve(answers, today, registry)
        if first_paid is None
        else earned_time.resolve(answers, today, registry, first_credits=first_paid)
    )
    earned = {t.earner.name: t.gaming_minutes * _SECONDS_PER_MINUTE for t in day.terms}
    total = day.gaming_minutes * _SECONDS_PER_MINUTE
    parts = ", ".join(
        _describe(t.earner.name, t.earner.label, t.answer) for t in day.terms
    )
    reason = f"{total / _SECONDS_PER_HOUR:.1f}h: {parts}"
    logger.info("Gaming budget %s", reason)
    return BudgetResolution(
        seconds=total,
        base_seconds=day.base.gaming_minutes * _SECONDS_PER_MINUTE,
        workout_seconds=earned.get("workout", 0.0),
        leetcode_seconds=earned.get("leetcode", 0.0),
        reason=reason,
        reading_seconds=earned.get("reading", 0.0),
        earned_seconds=earned,
    )
