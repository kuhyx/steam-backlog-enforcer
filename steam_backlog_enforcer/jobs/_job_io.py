"""Turn a command's output and progress into job events.

Inside a job the command code is unchanged: it still calls ``_echo``,
``current_progress()`` and ``logging``. The runner installs the three
adapters here, which write ``log`` and ``progress`` events instead of a
terminal.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Literal

from steam_backlog_enforcer._progress import eta_seconds

if TYPE_CHECKING:
    from steam_backlog_enforcer.jobs._events import EventWriter

LogLevel = Literal["info", "warning", "error"]

# At most this many progress events per second, plus every phase start and
# the final step: enough for a smooth bar, cheap for SSE and the event fold.
_MIN_PROGRESS_INTERVAL = 0.2
_CONTROL = re.compile(r"(\r|\n)")


def _level_for(line: str) -> LogLevel:
    """Guess a CLI line's severity from how the commands phrase it."""
    lowered = line.lower()
    if lowered.startswith(("error", "failed")):
        return "error"
    if lowered.startswith(("warning", "⚠")) or "⚠" in line:
        return "warning"
    return "info"


class JobLogSink:
    """An ``_echo`` sink that behaves like a terminal, one event per line.

    A carriage return discards the unfinished line, exactly as a terminal
    overwrites it, so the CLI's carriage-return progress meters collapse into the
    single line they finally show instead of thousands of events.
    """

    def __init__(self, writer: EventWriter) -> None:
        """Bind to the job's event writer."""
        self._writer = writer
        self._buffer = ""
        self.last_line: str | None = None
        """The last line with any text: the job's default summary."""
        self.last_error: str | None = None
        """The last error-level line, if any: a printed failure."""

    def __call__(self, text: str) -> None:
        """Consume raw ``_echo`` output (message plus ``end``)."""
        for part in _CONTROL.split(text):
            if part == "\n":
                self.flush()
            elif part == "\r":
                self._buffer = ""
            else:
                self._buffer += part

    def flush(self) -> None:
        """Emit the buffered line, if it has any visible text."""
        line = self._buffer.strip()
        self._buffer = ""
        if line:
            if any(ch.isalnum() for ch in line):  # Not a "────" rule.
                self.last_line = line
            level = _level_for(line)
            if level == "error":
                self.last_error = line
            self._writer.emit("log", level=level, message=line)


class JobProgress:
    """A :class:`~steam_backlog_enforcer._progress.Progress` writing events."""

    def __init__(self, writer: EventWriter) -> None:
        """Bind to the job's event writer."""
        self._writer = writer
        self._label = ""
        self._total: int | None = None
        self._step = 0
        self._item: str | None = None
        self._started = time.monotonic()
        self._last_emit = 0.0

    def phase(self, label: str, total: int | None = None) -> None:
        """Start a phase and announce it at once."""
        self._label, self._total, self._step, self._item = label, total, 0, None
        self._started = time.monotonic()
        self._emit(force=True)

    def advance(self, item: str | None = None, *, step: int | None = None) -> None:
        """Record a step; emitted unless one went out a moment ago."""
        self._step = self._step + 1 if step is None else step
        self._item = item
        done = self._total is not None and self._step >= self._total
        self._emit(force=done)

    def _emit(self, *, force: bool) -> None:
        """Write a ``progress`` event, throttled unless *force*."""
        now = time.monotonic()
        if not force and now - self._last_emit < _MIN_PROGRESS_INTERVAL:
            return
        self._last_emit = now
        fields: dict[str, object] = {
            "step": self._step,
            "total": self._total,
            "label": self._label,
        }
        if self._item:
            fields["item"] = self._item
        eta = eta_seconds(now - self._started, self._step, self._total)
        if eta is not None:
            fields["eta_seconds"] = eta
        self._writer.emit("progress", **fields)


class EventLogHandler(logging.Handler):
    """Forwards WARNING-and-above log records as ``log`` events.

    INFO chatter stays in the job's ``output.log``; what a user should see
    (a failed uninstall, an unreachable Steam) reaches the UI.
    """

    def __init__(self, writer: EventWriter) -> None:
        """Bind to the job's event writer."""
        super().__init__(level=logging.WARNING)
        self._writer = writer

    def emit(self, record: logging.LogRecord) -> None:
        """Write one record as a ``log`` event."""
        level: LogLevel = "error" if record.levelno >= logging.ERROR else "warning"
        try:
            message = record.getMessage()
        except TypeError, ValueError:
            message = str(record.msg)
        self._writer.emit("log", level=level, message=message)
