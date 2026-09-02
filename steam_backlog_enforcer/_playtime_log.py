"""A structured audit trail for every decision the gaming budget makes.

Reconstructing the incident that prompted this module — two hours billed while
a screen locker covered the display — took cross-referencing journald against
the screen locker's own JSONL, and even then the accrual could only be inferred
from the spacing of two warning notifications. That is not an audit trail.

So every budget decision is recorded here as one JSON object per line, readable
without ``sudo`` (unlike the state file, whose ``PermissionError`` is swallowed
on load and silently reported as "no state recorded yet"). There is no
engagement gate any more, so the record is deliberately thin: it answers
"was a qualifying process running," not "why wasn't it billing."

Volume is controlled by only writing when something *changes*. At a three-second
tick, one line per tick would be 28 800 lines a day of almost entirely identical
records; instead a verdict is written when it differs from the last one, with a
periodic heartbeat so a long unchanging session still leaves a trace.

Nothing here may raise. A logging failure must not take down the enforcer, so
the sink degrades to a warning on the daemon's own logger and carries on.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
import logging.handlers
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState

logger = logging.getLogger(__name__)

BUDGET_LOG_FILE: Final = Path("/var/log/steam-backlog-enforcer/budget.jsonl")
BUDGET_DEMO_LOG_FILE: Final = Path("/var/log/steam-backlog-enforcer/budget-demo.jsonl")

_MAX_BYTES: Final = 5 * 1024 * 1024
_BACKUP_COUNT: Final = 5
_HEARTBEAT_SECONDS: Final = 300.0

EVENT_VERDICT_CHANGE: Final = "verdict_change"
EVENT_HEARTBEAT: Final = "heartbeat"
EVENT_MANUAL_ADJUSTMENT: Final = "manual_adjustment"

STATE_ENGAGED: Final = "engaged"
STATE_NOT_APPLICABLE: Final = "not_applicable"


def budget_log_path(*, demo: bool) -> Path:
    """Return the audit log for a demo or production run.

    Demo runs get their own file for the same reason they get their own state
    file: this log is the record used to reconstruct real incidents, and a run
    that carries no enforcement weight must not be able to plant records in it
    that describe a budget nobody was ever charged. A 60-second demo billing
    700 seconds is indistinguishable, after the fact, from the production
    daemon having done something inexplicable.

    Args:
        demo: Whether this is a demo run.

    Returns:
        The destination JSONL file.
    """
    return BUDGET_DEMO_LOG_FILE if demo else BUDGET_LOG_FILE


class BudgetLog:
    """Append-only JSONL sink, rotated by size."""

    def __init__(self, *, path: Path) -> None:
        """Prepare a sink; the file is opened on first write.

        *path* is required on purpose. It used to default to the production
        log, so a throwaway probe run as root — ``BudgetLog()`` in a scratch
        script — wrote invented records straight into the trail this module
        exists to keep trustworthy. Naming the destination is now unavoidable.

        Args:
            path: Destination JSONL file, from :func:`budget_log_path`.
        """
        self._path = path
        self._sink: logging.Logger | None = None

    def _open(self) -> logging.Logger | None:
        """Return the rotating sink, creating it on first use.

        Returns:
            The sink, or ``None`` if it could not be created.
        """
        if self._sink is not None:
            return self._sink
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                self._path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT
            )
        except OSError as exc:
            logger.warning("Budget log unavailable at %s: %s", self._path, exc)
            return None

        handler.setFormatter(logging.Formatter("%(message)s"))
        # Named per destination: a single shared logger would let two sinks
        # with different paths silently evict each other's handler.
        sink = logging.getLogger(f"{__name__}.sink.{self._path}")
        sink.setLevel(logging.INFO)
        sink.propagate = False
        for stale in sink.handlers:
            stale.close()
        sink.handlers = [handler]
        self._sink = sink
        return self._sink

    def close(self) -> None:
        """Close the underlying file handler."""
        if self._sink is None:
            return
        for handler in self._sink.handlers:
            handler.close()
        self._sink.handlers = []
        self._sink = None

    def record(self, event: str, **fields: object) -> None:
        """Append one record.

        Args:
            event: Event name.
            fields: Arbitrary JSON-serialisable payload.
        """
        sink = self._open()
        if sink is None:
            return
        payload = {
            "timestamp": datetime.now(UTC).astimezone().isoformat(),
            "event": event,
            **fields,
        }
        try:
            sink.info(json.dumps(payload, default=str))
        except (OSError, ValueError) as exc:
            logger.warning("Could not write budget log record %r: %s", event, exc)


class TickJournal:
    """Decides which ticks are worth recording, and records them."""

    def __init__(
        self, log: BudgetLog, *, heartbeat: float = _HEARTBEAT_SECONDS
    ) -> None:
        """Start with nothing observed.

        Args:
            log: Sink to write through.
            heartbeat: Seconds between heartbeats during an unchanged verdict.
        """
        self._log = log
        self._heartbeat = heartbeat
        self._last_reason: str | None = None
        self._last_written_at: float | None = None

    def observe(
        self,
        qualifying: set[int],
        state: PlaytimeState,
        *,
        rules: PlaytimeRules,
        now_monotonic: float,
    ) -> None:
        """Record this tick's qualifying set if it changed or is due a heartbeat.

        Args:
            qualifying: PIDs that qualified this tick.
            state: Accounting state after this tick.
            rules: Policy for this tick.
            now_monotonic: Monotonic timestamp for heartbeat spacing.
        """
        reason = STATE_ENGAGED if qualifying else STATE_NOT_APPLICABLE
        if reason != self._last_reason:
            self._last_reason = reason
            self._last_written_at = now_monotonic
            self._log.record(
                EVENT_VERDICT_CHANGE, **_snapshot(qualifying, state, rules)
            )
            return

        if reason == STATE_NOT_APPLICABLE:
            return
        # The change branch above always fires on the first observation and
        # sets both fields together, so by here this is never None.
        last = cast("float", self._last_written_at)
        if now_monotonic - last < self._heartbeat:
            return

        self._last_written_at = now_monotonic
        self._log.record(EVENT_HEARTBEAT, **_snapshot(qualifying, state, rules))


def _snapshot(
    qualifying: set[int], state: PlaytimeState, rules: PlaytimeRules
) -> dict[str, object]:
    """Flatten a tick into the fields every record carries.

    The qualifying PIDs are included deliberately: the accrual that continued
    after the last game exited could not be attributed without them.

    Args:
        qualifying: PIDs that qualified this tick.
        state: Accounting state after this tick.
        rules: Policy for this tick.

    Returns:
        The record body.
    """
    return {
        "state": STATE_ENGAGED if qualifying else STATE_NOT_APPLICABLE,
        "qualifying": sorted(qualifying),
        "day_key": state.day_key,
        "billed_seconds": round(state.seconds, 3),
        "remaining_seconds": round(rules.budget_seconds - state.seconds, 3),
    }
