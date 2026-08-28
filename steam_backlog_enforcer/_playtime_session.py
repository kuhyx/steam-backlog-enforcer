"""The cross-tick state the daily budget carries, and how it is built.

Two things cannot be recomputed from scratch each tick. The engagement backdate
must recognise an engaged-to-paused *edge*, so it needs the previous verdict;
and the audit journal only writes on change, so it needs the previous record.
Both live on a session that the enforce loop creates once and threads through,
rather than in module globals.

The session's fields are typed by :class:`Protocol` so a test can supply an
honest stub. A ``MagicMock`` would satisfy every attribute lookup — including
the ones a refactor forgot to update — which is exactly the failure a type
would otherwise have caught.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from steam_backlog_enforcer._desktop_env import desktop_uid, resolve_desktop_user
from steam_backlog_enforcer._playtime_engagement import EngagementTracker
from steam_backlog_enforcer._playtime_log import (
    BudgetLog,
    TickJournal,
    budget_log_path,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer._engagement_types import EngagementVerdict
    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState


class EngagementSource(Protocol):
    """What the budget tick needs from an engagement tracker."""

    def assess(
        self,
        rules: PlaytimeRules,
        *,
        qualifying: set[int],
        now_monotonic: float,
    ) -> EngagementVerdict:
        """Judge whether this tick counts against the budget."""

    def backdate(
        self,
        state: PlaytimeState,
        verdict: EngagementVerdict,
        *,
        rules: PlaytimeRules,
    ) -> PlaytimeState:
        """Refund the idle grace period on an engaged-to-idle edge."""


class TickRecorder(Protocol):
    """What the budget tick needs from the audit journal."""

    def observe(
        self,
        verdict: EngagementVerdict,
        state: PlaytimeState,
        *,
        rules: PlaytimeRules,
        now_monotonic: float,
    ) -> None:
        """Record this tick if it is worth recording."""


@dataclass(frozen=True)
class PlaytimeSession:
    """Per-daemon engagement and logging state."""

    tracker: EngagementSource
    journal: TickRecorder


def new_session(*, demo: bool = False) -> PlaytimeSession:
    """Build the session the enforce loop threads through every tick.

    Args:
        demo: Whether this is a short-budget demo run. Demo runs journal to
            their own file, so they cannot plant records in the production
            audit trail.

    Returns:
        A session bound to the desktop user's X display and runtime dir.
    """
    uid = desktop_uid(resolve_desktop_user())
    return PlaytimeSession(
        tracker=EngagementTracker(uid=uid),
        journal=TickJournal(BudgetLog(path=budget_log_path(demo=demo))),
    )
