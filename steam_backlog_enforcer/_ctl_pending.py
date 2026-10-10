"""The two-phase gaming reset: arm, keep alive for 300 s, then commit.

The friction a typed phrase cannot give is *time*. Arming starts a countdown;
the caller must prove it is still there by heartbeating at least every
``HEARTBEAT_INTERVAL_SECONDS`` (the daemon tolerates ``LAPSE_AFTER_SECONDS``
of silence); only after ``ready_at`` may the reset commit. A closed tab, a dead
server or a crashed browser therefore cancels the reset instead of leaving it
armed for whoever shows up next.

Held in daemon memory on purpose: a daemon restart drops every pending reset,
which fails closed -- the caller just arms again and waits the full countdown.
Intervals use the monotonic clock so a wall-clock step cannot shorten the wait.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
import secrets
import threading
import time
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._ctl_protocol import (
    COUNTDOWN_RUNNING,
    PENDING_LAPSED,
    CtlError,
)
from steam_backlog_enforcer._friction import GAMING_RESET_COUNTDOWN_SECONDS

if TYPE_CHECKING:
    from collections.abc import Callable

HEARTBEAT_INTERVAL_SECONDS: Final = 10
LAPSE_AFTER_SECONDS: Final = 15

# TEST ONLY. Lets the disposable-VM verification run the flow in seconds. It can
# only SHORTEN the countdown (1..299 s), never lengthen it, and an unset or
# invalid value means the real 300 s. It lives in the root-owned unit's
# environment; the unprivileged caller cannot set it.
TEST_COUNTDOWN_ENV: Final = "SBE_CTL_TEST_COUNTDOWN_SECONDS"


def countdown_seconds() -> int:
    """The countdown to enforce: 300 s unless the VM-only override shortens it."""
    raw = os.environ.get(TEST_COUNTDOWN_ENV, "")
    if raw.isdecimal() and 0 < int(raw) < GAMING_RESET_COUNTDOWN_SECONDS:
        return int(raw)
    return GAMING_RESET_COUNTDOWN_SECONDS


def _same(left: str, right: str) -> bool:
    """Constant-time id comparison (bytes, so a non-ASCII id cannot raise)."""
    return secrets.compare_digest(left.encode(), right.encode())


@dataclass(frozen=True)
class Pending:
    """One armed reset.

    Attributes:
        pending_id: Unguessable handle the caller presents on every later call.
        armed_at: Wall-clock arm time, for display.
        ready_at: Wall-clock time the commit becomes allowed, for display.
        ready_mono: Monotonic deadline the commit is actually checked against.
        last_beat_mono: Monotonic time of the latest heartbeat (arm counts).
    """

    pending_id: str
    armed_at: datetime
    ready_at: datetime
    ready_mono: float
    last_beat_mono: float


class PendingResets:
    """At most one armed reset, with its countdown and heartbeat bookkeeping."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Start with nothing armed.

        Args:
            clock: Monotonic seconds source (injectable for tests).
            wall: Wall-clock source for the display timestamps.
        """
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        self._current: Pending | None = None

    def arm(self) -> Pending:
        """Arm a reset, or return the live one without restarting its countdown.

        Returning the existing one (rather than refusing or restarting) means a
        second arm -- a reloaded page, a retry -- can neither shorten nor
        extend the wait.
        """
        with self._lock:
            live = self._live()
            if live is not None:
                return live
            now = self._clock()
            wall = self._wall()
            wait = countdown_seconds()
            self._current = Pending(
                pending_id=secrets.token_hex(16),
                armed_at=wall,
                ready_at=wall + timedelta(seconds=wait),
                ready_mono=now + wait,
                last_beat_mono=now,
            )
            return self._current

    def beat(self, pending_id: str) -> Pending:
        """Record a heartbeat.

        Raises:
            CtlError: ``pending_lapsed`` if the id is unknown or already lapsed.
        """
        with self._lock:
            current = self._require(pending_id)
            self._current = Pending(
                current.pending_id,
                current.armed_at,
                current.ready_at,
                current.ready_mono,
                self._clock(),
            )
            return self._current

    def check_ready(self, pending_id: str) -> Pending:
        """Return the pending reset if it may commit now.

        Raises:
            CtlError: ``pending_lapsed`` if unknown or lapsed, or
                ``countdown_running`` (with ``retry_after_seconds``) if early.
        """
        with self._lock:
            current = self._require(pending_id)
            remaining = current.ready_mono - self._clock()
            if remaining > 0:
                raise CtlError(
                    COUNTDOWN_RUNNING,
                    f"the countdown has {remaining:.0f} s left",
                    {"retry_after_seconds": round(remaining, 1)},
                )
            return current

    def finish(self, pending_id: str) -> None:
        """Drop the pending reset after it committed or was cancelled.

        Idempotent: an id that is not (or no longer) armed is not an error.
        """
        with self._lock:
            current = self._current
            if current is not None and _same(current.pending_id, pending_id):
                self._current = None

    def _live(self) -> Pending | None:
        """The armed reset, or ``None`` -- dropping it first if it has lapsed."""
        current = self._current
        if current is not None and self._clock() - current.last_beat_mono > (
            LAPSE_AFTER_SECONDS
        ):
            self._current = None
            return None
        return current

    def _require(self, pending_id: str) -> Pending:
        """The live reset for *pending_id*; the lock must be held."""
        current = self._live()
        if current is None or not _same(current.pending_id, pending_id):
            raise CtlError(
                PENDING_LAPSED,
                "no such pending reset, or it lapsed: arm it again",
            )
        return current
