"""The cross-tick state the daily budget carries, and how it is built.

The audit journal only writes on change, so it needs the previous record. That
lives on a session that the enforce loop creates once and threads through,
rather than in module globals.

The session's fields are typed by :class:`Protocol` so a test can supply an
honest stub. A ``MagicMock`` would satisfy every attribute lookup — including
the ones a refactor forgot to update — which is exactly the failure a type
would otherwise have caught.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from steam_backlog_enforcer._playtime_history import HistoryWriter
from steam_backlog_enforcer._playtime_log import (
    BudgetLog,
    TickJournal,
    budget_log_path,
)
from steam_backlog_enforcer._shadow_log import ShadowJournal

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState
    from steam_backlog_enforcer._shadow import ShadowVerdict


class TickRecorder(Protocol):
    """What the budget tick needs from the audit journal."""

    def observe(
        self,
        qualifying: set[int],
        state: PlaytimeState,
        *,
        rules: PlaytimeRules,
        now_monotonic: float,
    ) -> None:
        """Record this tick if it is worth recording."""


class HistoryRecorder(Protocol):
    """What the budget tick needs from the per-day history writer."""

    def observe(self, state: PlaytimeState, *, demo: bool) -> None:
        """Record today's running total if it has moved far enough."""


class ShadowRecorder(Protocol):
    """What the budget tick needs from the shadow verdict journal."""

    def observe(self, verdict: ShadowVerdict, state: PlaytimeState) -> None:
        """Record the shadow verdict if it changed."""


@dataclass(frozen=True)
class PlaytimeSession:
    """Per-daemon logging state."""

    journal: TickRecorder
    history: HistoryRecorder
    shadow: ShadowRecorder


def new_session(*, demo: bool = False) -> PlaytimeSession:
    """Build the session the enforce loop threads through every tick.

    Args:
        demo: Whether this is a short-budget demo run. Demo runs journal to
            their own file, so they cannot plant records in the production
            audit trail.

    Returns:
        A session for this daemon run.
    """
    log = BudgetLog(path=budget_log_path(demo=demo))
    return PlaytimeSession(
        journal=TickJournal(log),
        history=HistoryWriter(),
        shadow=ShadowJournal(log),
    )
