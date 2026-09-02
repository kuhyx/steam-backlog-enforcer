"""A :class:`PlaytimeSession` stub for tests that are not about the log.

Most budget tests care only about accounting, warnings and the cutoff, not
about what the audit journal records. They get a session with an in-memory
journal and history so nothing touches the log file or disk.

Deliberately hand-written rather than ``MagicMock``: a mock satisfies every
attribute lookup, including ones a later refactor renamed, so a stub that must
actually match the protocol is the point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._playtime_session import PlaytimeSession

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState


class StubJournal:
    """A journal that keeps records in memory instead of on disk."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.observed: list[set[int]] = []

    def observe(
        self,
        qualifying: set[int],
        state: PlaytimeState,
        *,
        rules: PlaytimeRules,
        now_monotonic: float,
    ) -> None:
        """Remember *qualifying*.

        Args:
            qualifying: This tick's qualifying PIDs.
            state: Ignored.
            rules: Ignored.
            now_monotonic: Ignored.
        """
        del state, rules, now_monotonic
        self.observed.append(qualifying)


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


def fake_session() -> PlaytimeSession:
    """Build a session that never touches the log file or disk.

    Returns:
        The session.
    """
    return PlaytimeSession(
        journal=StubJournal(),
        history=StubHistory(),
    )
