"""Deciding whether the user is actually playing, not just leaving a game open.

A running game process is not evidence of play. The budget was previously billed
for two hours during which a screen locker covered the display and the machine
could not be touched at all — the game was simply still resident.

Three signals gate a tick, evaluated together rather than short-circuited, so
that the log can answer "was the screen *also* locked?" after the fact and the
backdate can tell an idle-only pause from a compound one. The probes themselves
live in :mod:`_engagement_probes`.

This module owns the per-tick verdict and the one piece of state a pure function
cannot hold: the previous verdict, which the idle backdate needs to recognise an
engaged-to-paused edge.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._controller_input import ControllerActivity
from steam_backlog_enforcer._engagement_probes import (
    assess_focus,
    assess_idle,
    assess_screen,
)
from steam_backlog_enforcer._engagement_types import (
    STATE_ENGAGED,
    STATE_NOT_APPLICABLE,
    STATE_PAUSED,
    CauseTally,
    EngagementVerdict,
)
from steam_backlog_enforcer._screen_hold import holder_lock_path
from steam_backlog_enforcer._x_probe import XProbe

if TYPE_CHECKING:
    from pathlib import Path

    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState

logger = logging.getLogger(__name__)


class EngagementTracker:
    """Assesses engagement per tick and owns the state the backdate needs."""

    def __init__(
        self,
        *,
        uid: int,
        probe: XProbe | None = None,
        controller: ControllerActivity | None = None,
        holder_path: Path | None = None,
    ) -> None:
        """Build a tracker over the desktop session owned by *uid*.

        Args:
            uid: Owner of the desktop session.
            probe: X probe, injected by tests.
            controller: Controller-activity watcher, injected by tests.
            holder_path: gatelock holder lock, injected by tests.
        """
        self._probe = probe if probe is not None else XProbe()
        self._controller = (
            controller if controller is not None else ControllerActivity()
        )
        self._holder_path = (
            holder_path if holder_path is not None else holder_lock_path(uid)
        )
        self._previous: EngagementVerdict | None = None
        self._previous_day: str | None = None

    def close(self) -> None:
        """Release the X connection and controller devices."""
        self._probe.close()
        self._controller.close()

    def assess(
        self,
        rules: PlaytimeRules,
        *,
        qualifying: set[int],
        now_monotonic: float,
    ) -> EngagementVerdict:
        """Judge whether this tick counts against the budget.

        Args:
            rules: Policy for this tick.
            qualifying: PIDs that would otherwise count.
            now_monotonic: Monotonic timestamp, for controller-activity ages.

        Returns:
            The verdict for this tick.
        """
        if not qualifying:
            return EngagementVerdict(state=STATE_NOT_APPLICABLE)

        pids = tuple(sorted(qualifying))
        if not rules.engagement_gate:
            return EngagementVerdict(state=STATE_ENGAGED, qualifying=pids)

        tally = CauseTally()

        held, holder_pid = assess_screen(self._holder_path, tally)
        focus_pid = assess_focus(self._probe, rules, qualifying, tally)
        idle, controller_idle = assess_idle(
            self._probe, self._controller, rules, tally, now_monotonic
        )

        return EngagementVerdict(
            state=STATE_PAUSED if tally.causes else STATE_ENGAGED,
            causes=tuple(tally.causes),
            degraded=tuple(tally.degraded),
            idle_seconds=idle,
            controller_idle_seconds=controller_idle,
            screen_held=held,
            holder_pid=holder_pid,
            focus_pid=focus_pid,
            qualifying=pids,
        )

    def backdate(
        self,
        state: PlaytimeState,
        verdict: EngagementVerdict,
        *,
        rules: PlaytimeRules,
    ) -> PlaytimeState:
        """Refund the idle grace period once per walk-away.

        Time billed *before* the idle threshold tripped was not play either, so
        the first paused tick of an idle-only spell gives it back. Deliberately
        conservative: it fires only on the engaged-to-paused edge, only when
        idleness is the sole cause, and never across a day rollover — and after
        a daemon restart there is no previous verdict, so nothing is refunded.

        Args:
            state: Accounting state after this tick's accumulation.
            verdict: This tick's verdict.
            rules: Policy for this tick.

        Returns:
            The state, with the grace period deducted when all of that holds.
        """
        previous, previous_day = self._previous, self._previous_day
        self._previous, self._previous_day = verdict, state.day_key

        if previous is None or previous.state != STATE_ENGAGED:
            return state
        if previous_day != state.day_key:
            return state
        if not verdict.idle_only():
            return state

        refunded = max(0.0, state.seconds - rules.idle_grace_seconds)
        amount = state.seconds - refunded
        logger.info(
            "Idle for %.0fs; refunding the %.0fs grace period.",
            verdict.idle_seconds or 0.0,
            amount,
        )
        # The refund must come off the same key it was billed to, or the
        # per-game parts drift above the whole on every walk-away — which is
        # many times a day, and would render as segments overflowing the bar.
        per_game = dict(state.per_game)
        key = state.last_credited_key
        if key and key in per_game:
            per_game[key] = max(0.0, per_game[key] - amount)
        return replace(state, seconds=refunded, per_game=per_game)
