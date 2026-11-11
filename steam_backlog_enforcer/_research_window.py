"""The total-block research window: validity, lock binding and how it opens.

kuhy 2026-11-11: to research a game by playing it ("Librarian: Tidy Up the
Arcane Library", app 4197610) he needs Steam during a total block. This module
is the one bounded way to get it, and the rules are all here:

* **At most 48 hours**, as an explicit expiry (``--until``), never an
  open-ended switch; a rerun never extends it.
* **Once per lock**: the record names the lock it was spent on (that lock's
  ``started_at``/``until``) and stays after the window ends.
* **Fail closed**: a missing, unreadable, unparsable or out-of-policy record
  (:mod:`steam_backlog_enforcer._research_record`) is "no window", i.e. the full
  total block. A corrupt record also refuses a new window instead of resetting
  the once-per-lock memory.
* **Never shortens the lock**: nothing here touches the guard-lib lock file or
  its pacman hook. The window ends by the clock, then the daemon re-applies the
  whole block (see :mod:`steam_backlog_enforcer._research_tick`).
"""

from __future__ import annotations

from datetime import datetime
import logging
import time
from typing import Final

from steam_backlog_enforcer import _research_record as store
from steam_backlog_enforcer._research_record import (
    MAX_WINDOW_SECONDS,
    ResearchRecord,
    ResearchStateError,
    read_record,
    write_record,
)
from steam_backlog_enforcer._total_block import get_total_block_status

logger = logging.getLogger(__name__)

LIBRARIAN_APP_ID: Final = 4197610
LIBRARIAN_NAME: Final = "Librarian: Tidy Up the Arcane Library!"

# Same-lock comparison tolerance: the lock file holds whole seconds, but the
# status goes through a datetime and back.
_LOCK_TOLERANCE_SECONDS: Final = 1.0

# Corrupt-record reports already made; cleared by the next healthy read so a
# record that breaks again is reported again, but not every 3 s tick.
LOGGED: Final[set[str]] = set()


class ResearchRefusedError(Exception):
    """A window may not be opened; the message says why."""


def now() -> float:
    """The wall clock in epoch seconds (a seam for tests)."""
    return time.time()


def current_lock(at: float) -> tuple[float, float] | None:
    """``(started_at, until)`` of the total block in force at *at*, else ``None``."""
    status = get_total_block_status()
    if status.started_at is None or status.until is None:
        return None
    until = status.until.timestamp()
    if at >= until:
        return None
    return status.started_at.timestamp(), until


def _same_lock(record: ResearchRecord, lock: tuple[float, float]) -> bool:
    """Whether *record* was spent on the lock identified by *lock*."""
    return (
        abs(record.lock_started_at - lock[0]) < _LOCK_TOLERANCE_SECONDS
        and abs(record.lock_until - lock[1]) < _LOCK_TOLERANCE_SECONDS
    )


def live_record(at: float | None = None) -> ResearchRecord | None:
    """The record for the lock in force, failing closed to ``None``.

    ``None`` covers: no lock, no record, a record for an earlier lock, and a
    record that cannot be trusted (reported once, not every tick).
    """
    when = now() if at is None else at
    lock = current_lock(when)
    if lock is None:
        return None
    try:
        record = read_record()
    except ResearchStateError as exc:
        message = f"research record ignored, full block stays: {exc}"
        if message not in LOGGED:
            LOGGED.add(message)
            logger.exception(message)
        return None
    LOGGED.clear()
    if record is None or not _same_lock(record, lock):
        return None
    return record


def parse_until(raw: str) -> datetime:
    """Parse ``--until``: ISO 8601, local time unless it carries an offset.

    Raises:
        ValueError: If *raw* is not an ISO date-time.
    """
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        msg = f"--until {raw!r} is not an ISO date-time (e.g. 2026-11-13T00:00)"
        raise ValueError(msg) from exc
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def open_research_window(until: datetime) -> ResearchRecord:
    """Record a research window ending at *until* for the lock in force.

    Args:
        until: The expiry (timezone-aware).

    Returns:
        The stored record.

    Raises:
        ResearchRefusedError: With the reason: no active total block, an
            unreadable record (fail closed), a window already spent on this
            lock, an expiry that is past, over 48 h away or beyond the lock's
            end, or a record that cannot be written.
    """
    at = now()
    lock = current_lock(at)
    if lock is None:
        msg = "no active total block; nothing to research"
        raise ResearchRefusedError(msg)
    try:
        previous = read_record()
    except ResearchStateError as exc:
        msg = f"research record unreadable ({exc}); refusing (fail closed)"
        raise ResearchRefusedError(msg) from exc
    if previous is not None and _same_lock(previous, lock):
        ended = datetime.fromtimestamp(previous.until).astimezone()
        msg = f"a window was already used for this lock (until {ended:%F %H:%M})"
        raise ResearchRefusedError(msg)
    deadline = until.timestamp()
    if deadline <= at:
        msg = "--until must be in the future"
    elif deadline - at > MAX_WINDOW_SECONDS:
        msg = "--until is more than 48 h from now"
    elif deadline > lock[1]:
        msg = "--until is after the end of the total block"
    else:
        return _store(ResearchRecord(lock[0], lock[1], at, deadline))
    raise ResearchRefusedError(msg)


def _store(record: ResearchRecord) -> ResearchRecord:
    """Write *record*, turning a write failure into a refusal."""
    try:
        write_record(record)
    except OSError as exc:
        msg = f"cannot write {store.RESEARCH_FILE}: {exc}"
        raise ResearchRefusedError(msg) from exc
    return record
