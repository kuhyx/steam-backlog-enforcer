"""A :class:`PlaytimeSession` stub for tests that are not about engagement.

Most budget tests predate the engagement gate and care only about accounting,
warnings and the cutoff. They get a session that always says "engaged", which
reproduces the pre-gate behaviour exactly, so those tests keep asserting what
they were written to assert.

Deliberately hand-written rather than ``MagicMock``: a mock satisfies every
attribute lookup, including ones a later refactor renamed, so a stub that must
actually match the protocol is the point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._engagement_types import (
    STATE_ENGAGED,
    STATE_PAUSED,
    EngagementVerdict,
)
from steam_backlog_enforcer._playtime_session import PlaytimeSession

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState


class StubTracker:
    """An engagement tracker with a fixed answer and no probes."""

    def __init__(self, *, engaged: bool = True) -> None:
        """Record the answer this tracker always gives.

        Args:
            engaged: Whether every tick should count.
        """
        self.engaged = engaged
        self.verdicts: list[EngagementVerdict] = []

    def assess(
        self,
        rules: PlaytimeRules,
        *,
        qualifying: set[int],
        now_monotonic: float,
    ) -> EngagementVerdict:
        """Return the fixed verdict.

        Args:
            rules: Ignored.
            qualifying: PIDs recorded on the verdict.
            now_monotonic: Ignored.

        Returns:
            The verdict.
        """
        del rules, now_monotonic
        verdict = EngagementVerdict(
            state=STATE_ENGAGED if self.engaged else STATE_PAUSED,
            causes=() if self.engaged else ("focus",),
            qualifying=tuple(sorted(qualifying)),
        )
        self.verdicts.append(verdict)
        return verdict

    def backdate(
        self,
        state: PlaytimeState,
        verdict: EngagementVerdict,
        *,
        rules: PlaytimeRules,
    ) -> PlaytimeState:
        """Return *state* untouched.

        Args:
            state: Accounting state.
            verdict: Ignored.
            rules: Ignored.

        Returns:
            The unchanged state.
        """
        del verdict, rules
        return state


class StubJournal:
    """A journal that keeps records in memory instead of on disk."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.observed: list[EngagementVerdict] = []

    def observe(
        self,
        verdict: EngagementVerdict,
        state: PlaytimeState,
        *,
        rules: PlaytimeRules,
        now_monotonic: float,
    ) -> None:
        """Remember *verdict*.

        Args:
            verdict: This tick's verdict.
            state: Ignored.
            rules: Ignored.
            now_monotonic: Ignored.
        """
        del state, rules, now_monotonic
        self.observed.append(verdict)


class StubHistory:
    """A per-day history writer that records in memory instead of on disk."""

    def __init__(self) -> None:
        self.recorded: list[tuple[str, float]] = []

    def observe(self, state: PlaytimeState, *, demo: bool) -> None:
        """Remember the day and total.

        Args:
            state: This tick's state.
            demo: Ignored; the real writer skips demo runs.
        """
        del demo
        self.recorded.append((state.day_key, state.seconds))


def fake_session(*, engaged: bool = True) -> PlaytimeSession:
    """Build a session that never touches X, /proc/locks or the log file.

    Args:
        engaged: Whether every tick should count against the budget.

    Returns:
        The session.
    """
    return PlaytimeSession(
        tracker=StubTracker(engaged=engaged),
        journal=StubJournal(),
        history=StubHistory(),
    )
