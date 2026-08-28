"""The verdict describing whether this tick should bill the gaming budget.

Split from :mod:`_playtime_engagement` so the decision *record* stays a plain
frozen value with no probes attached: everything that writes it is testable
without an X server, and everything that reads it — the accumulator and the
audit log — sees the same shape.

The verdict deliberately records *every* cause rather than short-circuiting on
the first one. The idle backdate only fires when idle is the sole cause, and a
log that recorded just the first-matching reason could not answer "was the
screen also locked?" after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

STATE_ENGAGED: Final = "engaged"
STATE_PAUSED: Final = "paused"
STATE_NOT_APPLICABLE: Final = "not_applicable"

CAUSE_IDLE: Final = "idle"
CAUSE_SCREEN_HELD: Final = "screen_held"
CAUSE_FOCUS: Final = "focus"

PROBE_IDLE: Final = "idle"
PROBE_SCREEN_HELD: Final = "screen_held"
PROBE_FOCUS: Final = "focus"


@dataclass
class CauseTally:
    """Pause causes and probe failures accumulated across one tick's probes.

    Passed to each probe instead of two parallel lists: it keeps the probe
    signatures short, and it makes "this probe appends to both" a single idea
    rather than a convention two arguments have to remember.
    """

    causes: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EngagementVerdict:
    """Why this tick did or did not count against the budget."""

    state: str
    causes: tuple[str, ...] = ()
    degraded: tuple[str, ...] = ()
    idle_seconds: float | None = None
    controller_idle_seconds: float | None = None
    screen_held: bool | None = None
    holder_pid: int | None = None
    focus_pid: int | None = None
    qualifying: tuple[int, ...] = field(default_factory=tuple)

    @property
    def engaged(self) -> bool:
        """Whether this tick should be billed.

        ``not_applicable`` counts as engaged: nothing qualifies, so the
        accumulator will credit nothing regardless, and calling it "paused"
        would fill the audit log with a pause reason during ordinary desktop
        use.

        Returns:
            Whether the tick bills.
        """
        return self.state != STATE_PAUSED

    @property
    def reason(self) -> str:
        """A short human-readable summary of *causes*.

        Returns:
            The joined causes, or the state when there are none.
        """
        return "+".join(self.causes) if self.causes else self.state

    def idle_only(self) -> bool:
        """Whether idleness is the sole reason this tick was paused.

        The backdate refunds the idle grace period, which is only correct when
        nothing else would have paused the tick anyway.

        Returns:
            Whether *causes* is exactly ``(CAUSE_IDLE,)``.
        """
        return self.causes == (CAUSE_IDLE,)
