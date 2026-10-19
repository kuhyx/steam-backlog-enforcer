"""The shadow verdict in the budget audit log: one record per change.

The game journal (:class:`~steam_backlog_enforcer._playtime_log.TickJournal`)
only writes when the *game* verdict changes, so browsing with no game running
would never show up there. Shadow changes get their own event in the same
``budget.jsonl``, written only when the verdict (paused/leisure/free plus the
billed sources) changes -- no heartbeat; the state file has the running total.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_log import BudgetLog
    from steam_backlog_enforcer._playtime_state import PlaytimeState
    from steam_backlog_enforcer._shadow import ShadowVerdict

EVENT_SHADOW_CHANGE: Final = "shadow_change"


class ShadowJournal:
    """Records the shadow verdict whenever it changes."""

    def __init__(self, log: BudgetLog) -> None:
        """Start with nothing observed.

        Args:
            log: Sink to write through (the game journal's own trail).
        """
        self._log = log
        self._last: ShadowVerdict | None = None

    def observe(self, verdict: ShadowVerdict, state: PlaytimeState) -> None:
        """Record *verdict* with the shadow totals if it differs from the last.

        Args:
            verdict: This tick's shadow verdict.
            state: Accounting state after this tick.
        """
        if verdict == self._last:
            return
        self._last = verdict
        remaining = state.shadow_budget_seconds - state.shadow_seconds
        self._log.record(
            EVENT_SHADOW_CHANGE,
            shadow_state=verdict.state,
            paused_by=verdict.paused_by,
            sources=list(verdict.keys),
            day_key=state.day_key,
            shadow_seconds=round(state.shadow_seconds, 3),
            shadow_budget_seconds=round(state.shadow_budget_seconds, 3),
            shadow_remaining_seconds=round(remaining, 3),
            shadow_paused_seconds=round(state.shadow_paused_seconds, 3),
            shadow_per_source={
                k: round(v, 3) for k, v in state.shadow_per_source.items()
            },
        )
