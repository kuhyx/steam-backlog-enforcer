"""Today's gaming budget: a floor, plus whatever today earned.

The budget is a sum, not a choice between values, capped at
``max_gaming_seconds`` (8h):

    base (4h) + workout bonus (2h) + LeetCode bonus (1h) + reading bonus (1h)

so a day earns anything from 4h to 8h. The earners are read **independently**
-- :mod:`steam_backlog_enforcer._workout_budget`,
:mod:`steam_backlog_enforcer._leetcode_bonus` and
:mod:`steam_backlog_enforcer._reading_bonus` share no state and none can fail
in a way that changes another's term. That is what "the LeetCode bonus
must not interfere with the workout" means in code.

**Fail closed.** An answer that could not be obtained contributes nothing, the
same as a "no". The difference is only in what gets reported: an unreadable
LeetCode ledger raises an incident, an honest "not solved yet" does not.

**Rising, in normal use -- but not guaranteed.** Both earners only ever go
false->true within a day, so in the ordinary case the budget starts at the floor
and rises. That is a property of the *inputs*, not something enforced here:
nothing persists a per-day high-water mark, so anything that changes a resolved
answer mid-day -- editing the config, or deploying a change onto a day already
in progress -- lowers the budget immediately and re-prices time already spent.
Seconds already accrued are then measured against the new, smaller budget, and
the cutoff fires on the next tick with no warning first, because
``warned_seconds`` records thresholds by seconds *remaining* and remaining has
already gone negative.

That was a deliberate call (2026-08-29): the alternative is a persisted
``granted_budget_seconds`` on ``PlaytimeState`` taking ``max(resolved,
granted)``. If a mid-day drop ever bites, that is the fix -- not a nudge to
these numbers.

**One seam.** :func:`resolve_budget` is called from ``rules_for`` and nowhere
else, so the enforcing daemon and the read-only HTTP/MCP views resolve the same
number. The daemon holds its ``Config`` for the process lifetime while
``_budget_view`` reloads it per request, so anything resolved at only one of
those two sites would let the UI report a budget the daemon was not enforcing.
Callers that want the breakdown read it off ``PlaytimeRules``, never by
resolving a second time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._leetcode_bonus import leetcode_solved_today
from steam_backlog_enforcer._reading_bonus import read_today
from steam_backlog_enforcer._workout_budget import workout_logged_today

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

_SECONDS_PER_HOUR: Final = 3600.0

# The 5h -> 4h base cut belongs to book-guard's reading hour, and book-guard's
# gate starts on 2026-10-01. Until then the old 5h floor stands: cutting an
# hour a reader cannot yet earn back was a same-day loss (2026-09-26).
READING_BASE_FROM: Final = date(2026, 10, 1)
_PRE_READING_EXTRA: Final = 3600.0


def base_for(configured: float, today: date) -> float:
    """The floor for ``today``: the configured base, +1h before the cut."""
    return configured + (_PRE_READING_EXTRA if today < READING_BASE_FROM else 0.0)


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
    """

    seconds: float
    base_seconds: float
    workout_seconds: float
    leetcode_seconds: float
    reason: str
    reading_seconds: float = 0.0


def _bonus_seconds(configured: int, label: str) -> float:
    """A configured bonus, refusing a negative one.

    Args:
        configured: The configured value.
        label: The config field name, for the error message.

    Returns:
        The bonus in seconds, clamped at zero. A negative bonus would mean
        earning something *cost* time, which is never what was meant.
    """
    if configured < 0:
        logger.error(
            "%s is negative (%d); clamping to 0 so earning something can never "
            "cost gaming time.",
            label,
            configured,
        )
        return 0.0
    return float(configured)


def _describe(*, answer: bool | None, earned: str, missed: str, unknown: str) -> str:
    """Render one earner's answer for the reason string.

    Args:
        answer: True, False, or None for "could not check".
        earned: Phrase for True.
        missed: Phrase for False.
        unknown: Phrase for None.

    Returns:
        The matching phrase.
    """
    if answer is None:
        return unknown
    return earned if answer else missed


def resolve_budget(config: Config) -> BudgetResolution:
    """Return today's gaming budget, and what earned it.

    Args:
        config: Loaded user configuration.

    Returns:
        The floor plus a bonus for each of today's earners. An answer that
        could not be obtained contributes nothing, exactly as a "no" does --
        the difference is only in what gets logged and reported.
    """
    base = base_for(
        _bonus_seconds(config.base_gaming_seconds, "base_gaming_seconds"),
        datetime.now().astimezone().date(),
    )
    workout = workout_logged_today(config)
    leetcode = leetcode_solved_today(config)
    reading = read_today(config)

    workout_seconds = (
        _bonus_seconds(config.workout_bonus_seconds, "workout_bonus_seconds")
        if workout
        else 0.0
    )
    leetcode_seconds = (
        _bonus_seconds(config.leetcode_bonus_seconds, "leetcode_bonus_seconds")
        if leetcode
        else 0.0
    )
    reading_seconds = (
        _bonus_seconds(config.reading_bonus_seconds, "reading_bonus_seconds")
        if reading
        else 0.0
    )
    ceiling = _bonus_seconds(config.max_gaming_seconds, "max_gaming_seconds")
    total = min(ceiling, base + workout_seconds + leetcode_seconds + reading_seconds)

    workout_part = _describe(
        answer=workout,
        earned="workout counted",
        missed="no counted workout",
        unknown="workout unknown (screen-locker unreachable)",
    )
    leetcode_part = _describe(
        answer=leetcode,
        earned="LeetCode solve recorded",
        missed="no LeetCode solve recorded",
        unknown="LeetCode unknown (ledger and status API both unreadable)",
    )
    reading_part = _describe(
        answer=reading,
        earned="reading credited",
        missed="no reading credited",
        unknown="reading unknown (book-guard ledger unreadable)",
    )
    reason = (
        f"{total / _SECONDS_PER_HOUR:.1f}h: {workout_part}, {leetcode_part}, "
        f"{reading_part}"
    )
    logger.info("Gaming budget %s", reason)
    return BudgetResolution(
        seconds=total,
        base_seconds=base,
        workout_seconds=workout_seconds,
        leetcode_seconds=leetcode_seconds,
        reason=reason,
        reading_seconds=reading_seconds,
    )
