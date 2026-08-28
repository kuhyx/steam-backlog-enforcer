"""A structured audit trail for every decision the gaming budget makes.

Reconstructing the incident that prompted this module — two hours billed while
a screen locker covered the display — took cross-referencing journald against
the screen locker's own JSONL, and even then the accrual could only be inferred
from the spacing of two warning notifications. That is not an audit trail.

So every budget decision is recorded here as one JSON object per line, readable
without ``sudo`` (unlike the state file, whose ``PermissionError`` is swallowed
on load and silently reported as "no state recorded yet").

Volume is controlled by only writing when something *changes*. At a three-second
tick, one line per tick would be 28 800 lines a day of almost entirely identical
records; instead a verdict is written when it differs from the last one, with a
periodic heartbeat so a long unchanging session still leaves a trace.

Nothing here may raise. A logging failure must not take down the enforcer, so
the sink degrades to a warning on the daemon's own logger and carries on.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import logging.handlers
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from steam_backlog_enforcer._engagement_types import STATE_NOT_APPLICABLE

if TYPE_CHECKING:
    from steam_backlog_enforcer._engagement_types import EngagementVerdict
    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState

logger = logging.getLogger(__name__)

BUDGET_LOG_FILE: Final = Path("/var/log/steam-backlog-enforcer/budget.jsonl")

_MAX_BYTES: Final = 5 * 1024 * 1024
_BACKUP_COUNT: Final = 5
_HEARTBEAT_SECONDS: Final = 300.0

EVENT_VERDICT_CHANGE: Final = "verdict_change"
EVENT_HEARTBEAT: Final = "heartbeat"
EVENT_DETECTOR_FAILURE: Final = "detector_failure"
EVENT_MANUAL_ADJUSTMENT: Final = "manual_adjustment"


class BudgetLog:
    """Append-only JSONL sink, rotated by size."""

    def __init__(self, *, path: Path = BUDGET_LOG_FILE) -> None:
        """Prepare a sink; the file is opened on first write.

        Args:
            path: Destination JSONL file.
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
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
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
        verdict: EngagementVerdict,
        state: PlaytimeState,
        *,
        rules: PlaytimeRules,
        now_monotonic: float,
    ) -> None:
        """Record *verdict* if it changed, failed, or is due a heartbeat.

        Args:
            verdict: This tick's verdict.
            state: Accounting state after this tick.
            rules: Policy for this tick.
            now_monotonic: Monotonic timestamp for heartbeat spacing.
        """
        if verdict.degraded:
            self._log.record(
                EVENT_DETECTOR_FAILURE,
                degraded=list(verdict.degraded),
                billed=True,
                **_snapshot(verdict, state, rules),
            )

        if verdict.reason != self._last_reason:
            self._last_reason = verdict.reason
            self._last_written_at = now_monotonic
            self._log.record(EVENT_VERDICT_CHANGE, **_snapshot(verdict, state, rules))
            return

        if verdict.state == STATE_NOT_APPLICABLE:
            return
        # The change branch above always fires on the first observation and
        # sets both fields together, so by here this is never None.
        last = cast("float", self._last_written_at)
        if now_monotonic - last < self._heartbeat:
            return

        self._last_written_at = now_monotonic
        self._log.record(EVENT_HEARTBEAT, **_snapshot(verdict, state, rules))


def _snapshot(
    verdict: EngagementVerdict, state: PlaytimeState, rules: PlaytimeRules
) -> dict[str, object]:
    """Flatten a tick into the fields every record carries.

    The qualifying PIDs are included deliberately: the accrual that continued
    after the last game exited could not be attributed without them.

    Args:
        verdict: This tick's verdict.
        state: Accounting state after this tick.
        rules: Policy for this tick.

    Returns:
        The record body.
    """
    return {
        "state": verdict.state,
        "reason": verdict.reason,
        "causes": list(verdict.causes),
        "idle_seconds": verdict.idle_seconds,
        "controller_idle_seconds": verdict.controller_idle_seconds,
        "screen_held": verdict.screen_held,
        "holder_pid": verdict.holder_pid,
        "focus_pid": verdict.focus_pid,
        "qualifying": list(verdict.qualifying),
        "day_key": state.day_key,
        "billed_seconds": round(state.seconds, 3),
        "remaining_seconds": round(rules.budget_seconds - state.seconds, 3),
    }
