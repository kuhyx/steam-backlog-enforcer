"""Reading the last recorded verdict back out of the budget audit log.

``_playtime_log`` writes the daemon's own view of whether a qualifying process
was running and which PIDs qualified. That is exactly what a live status
display wants, and reading it back beats having the web server re-derive it
itself: a second opinion that disagreed with the daemon's would be worse than
no opinion at all.

The log is append-only and can reach 5 MB before rotating, so only its tail is
read. One record is all anyone needs and a status endpoint polled every few
seconds must not parse megabytes to find it.

Callers must treat what they get as a *recent* verdict, not a current one:
``TickJournal`` only writes on a change of verdict or a five-minute heartbeat,
so this record can be up to that old. ``observed_at`` is carried through so the
display can say how stale it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any, Final

from steam_backlog_enforcer._playtime_log import budget_log_path
from steam_backlog_enforcer._playtime_procs import process_name

logger = logging.getLogger(__name__)

# Enough for several records at any plausible size, small enough to read on
# every poll without thinking about it.
_TAIL_BYTES: Final = 64 * 1024


@dataclass(frozen=True)
class RunningGame:
    """A qualifying process that is still alive."""

    pid: int
    name: str


@dataclass(frozen=True)
class SessionView:
    """The most recently logged tick observation."""

    observed_at: str = ""
    """ISO-8601 timestamp the daemon recorded, ``""`` if unknown."""
    state: str = ""
    games: list[RunningGame] = field(default_factory=list)
    available: bool = False
    """Whether a record was found at all."""


def _last_record(*, demo: bool) -> dict[str, Any] | None:
    """Return the last parseable JSON object in the audit log.

    Args:
        demo: Whether to read the demo log.

    Returns:
        The decoded record, or ``None`` if the log is missing, unreadable or
        holds no complete record in its tail.
    """
    path = budget_log_path(demo=demo)
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - _TAIL_BYTES))
            chunk = handle.read()
    except OSError:
        return None

    # The first line of the tail is usually a fragment of a longer record; it is
    # discarded naturally by walking backwards to the first line that parses.
    for line in reversed(chunk.decode("utf-8", errors="replace").splitlines()):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            return record
    return None


def _live_games(record: dict[str, Any]) -> list[RunningGame]:
    """Resolve the record's qualifying PIDs to names, dropping dead ones.

    Args:
        record: A decoded audit-log record.

    Returns:
        One entry per PID that still exists.
    """
    qualifying = record.get("qualifying")
    if not isinstance(qualifying, list):
        return []
    games = []
    for pid in qualifying:
        if not isinstance(pid, int):
            continue
        name = process_name(pid)
        if name is not None:
            games.append(RunningGame(pid=pid, name=name))
    return games


def last_verdict(*, demo: bool) -> SessionView:
    """Return the most recently logged tick observation.

    Args:
        demo: Whether to read the demo log.

    Returns:
        The verdict, or an empty view with ``available=False``.
    """
    record = _last_record(demo=demo)
    if record is None:
        return SessionView()

    return SessionView(
        observed_at=str(record.get("timestamp") or ""),
        state=str(record.get("state") or ""),
        games=_live_games(record),
        available=True,
    )
