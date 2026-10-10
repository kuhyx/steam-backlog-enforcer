"""The files of one job directory and the JSONL event log inside it.

``events.jsonl`` is append-only, one ``JobEvent`` per line, ``seq`` strictly
increasing. Normally only the job subprocess appends; the server appends
too in two cases (the initial ``queued`` state, and the ``failed`` verdict
for a job whose process died), so every append takes an exclusive ``flock``
and recomputes ``seq`` whenever someone else wrote since.

Readers only ever parse complete, newline-terminated lines: a line still
being written is invisible until it is whole.
"""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import json
import os
import threading
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from pathlib import Path

REQUEST_NAME: Final = "request.json"
EVENTS_NAME: Final = "events.jsonl"
ANSWERS_NAME: Final = "answers.jsonl"
# Touched by the server to cancel a job that is blocked on a prompt.
CANCEL_NAME: Final = "cancel.request"
RESULT_NAME: Final = "result.json"
PID_NAME: Final = "pid"
OUTPUT_NAME: Final = "output.log"

TERMINAL_STATES: Final = frozenset({"succeeded", "failed", "cancelled"})


def now_iso() -> str:
    """Current UTC time as ISO-8601 with a ``Z`` suffix, second precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse every complete line of a JSONL file; skip torn or bad lines."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    complete = raw if raw.endswith("\n") else raw[: raw.rfind("\n") + 1]
    out: list[dict[str, Any]] = []
    for line in complete.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    """Append one object as a line, under an exclusive lock."""
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(obj) + "\n")
        fh.flush()


def read_events(job_dir: Path, after_seq: int = 0) -> list[dict[str, Any]]:
    """Return the job's events with ``seq`` greater than *after_seq*."""
    return [
        event
        for event in read_jsonl(job_dir / EVENTS_NAME)
        if isinstance(event.get("seq"), int) and event["seq"] > after_seq
    ]


class EventWriter:
    """Appends events to one job's ``events.jsonl`` with gap-free ``seq``."""

    def __init__(self, job_dir: Path) -> None:
        """Bind to *job_dir*; the file is created on the first event."""
        self._path = job_dir / EVENTS_NAME
        self._seq = 0
        self._size = -1  # File size after our last write; -1 = never wrote.
        self._lock = threading.Lock()

    def _last_seq(self) -> int:
        """The highest ``seq`` already in the file (0 if none)."""
        seqs = [
            e["seq"] for e in read_jsonl(self._path) if isinstance(e.get("seq"), int)
        ]
        return max(seqs, default=0)

    def emit(self, event_type: str, **fields: object) -> dict[str, Any]:
        """Append one event and return it.

        Args:
            event_type: ``state``, ``log``, ``progress``, ``prompt`` or
                ``result``.
            **fields: The type-specific fields from the contract.
        """
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            if os.fstat(fh.fileno()).st_size != self._size:
                # First write, or another process appended since our last one.
                self._seq = self._last_seq()
            self._seq += 1
            event: dict[str, Any] = {
                "seq": self._seq,
                "ts": now_iso(),
                "type": event_type,
                **fields,
            }
            fh.write(json.dumps(event) + "\n")
            fh.flush()
            self._size = os.fstat(fh.fileno()).st_size
        return event
