"""The total-block research window: validity, lock binding and how it opens.

kuhy 2026-11-11: to research a game by playing it ("Librarian: Tidy Up the
Arcane Library", app 4197610) he needs Steam during a total block. This module
is the one bounded way to get it, and the rules are all here:

* **Bounded by the lock**: an explicit expiry (``--until``) no later than the
  lock's end, never an open-ended switch. While open, the window may be
  extended once (to the lock's end at most); nothing shortens it.
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

from dataclasses import replace
from datetime import datetime
import logging
import time
from typing import Final

from steam_backlog_enforcer import _research_record as store
from steam_backlog_enforcer._research_record import (
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
    """Record a research window ending at *until*, or extend the one in force.

    The first call for a lock opens the window. While that window is open, one
    later call may extend it, to the lock's end at most. Nothing else reopens,
    lengthens or shortens it.

    Args:
        until: The expiry (timezone-aware).

    Returns:
        The stored record.

    Raises:
        ResearchRefusedError: With the reason: no active total block, an
            unreadable record (fail closed), an expiry that is past (or, for
            an extension, not later than the current one) or beyond the lock's
            end, a window already ended or already extended once, or a record
            that cannot be written.
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
    deadline = until.timestamp()
    if previous is not None and _same_lock(previous, lock):
        return _store(_extend(previous, deadline, at, lock[1]))
    if deadline <= at:
        msg = "--until must be in the future"
    elif deadline > lock[1]:
        msg = "--until is after the end of the total block"
    else:
        return _store(ResearchRecord(lock[0], lock[1], at, deadline))
    raise ResearchRefusedError(msg)


def _extend(
    previous: ResearchRecord, deadline: float, at: float, lock_end: float
) -> ResearchRecord:
    """*previous* with its single extension, or a refusal saying why not."""
    if previous.extended_until is not None:
        msg = "the window was already extended once"
    elif not previous.is_open(at):
        msg = "a window was already used for this lock and it has ended"
    elif deadline <= previous.until:
        msg = "--until must be later than the window's current end"
    elif deadline > lock_end:
        msg = "--until is after the end of the total block"
    else:
        return replace(previous, extended_until=deadline)
    raise ResearchRefusedError(msg)


def research_used(at: float | None = None) -> bool:
    """Whether a research window was spent on the lock in force.

    Gates the one irreversible step of the block, the purge of the Steam
    folder. A record that cannot be read counts as used: when the answer is
    unknown, nothing is deleted (the block itself stays fully applied).
    """
    lock = current_lock(now() if at is None else at)
    if lock is None:
        return False
    try:
        record = read_record()
    except ResearchStateError:
        return True
    return record is not None and _same_lock(record, lock)


def _store(record: ResearchRecord) -> ResearchRecord:
    """Write *record*, turning a write failure into a refusal."""
    try:
        write_record(record)
    except OSError as exc:
        msg = f"cannot write {store.RESEARCH_FILE}: {exc}"
        raise ResearchRefusedError(msg) from exc
    return record
