"""Tests for ``jobs._job_io``: echo, progress and logging as job events."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer.jobs._events import EventWriter, read_events
from steam_backlog_enforcer.jobs._job_io import (
    EventLogHandler,
    JobLogSink,
    JobProgress,
    _level_for,
)

if TYPE_CHECKING:
    from pathlib import Path

_CLOCK = "steam_backlog_enforcer.jobs._job_io.time.monotonic"


class TestLevelFor:
    """Severity guessed from CLI phrasing."""

    def test_levels(self) -> None:
        """Error/failed prefixes, warning markers, else info."""
        assert _level_for("Error: boom") == "error"
        assert _level_for("failed to x") == "error"
        assert _level_for("Warning: careful") == "warning"
        assert _level_for("  ⚠ odd") == "warning"
        assert _level_for("x ⚠ y") == "warning"
        assert _level_for("all fine") == "info"


class TestJobLogSink:
    """The terminal-like line buffer."""

    def test_one_event_per_line(self, tmp_path: Path) -> None:
        """Newlines flush; partial text waits for its newline."""
        sink = JobLogSink(EventWriter(tmp_path))
        sink("hel")
        sink("lo\nworld")
        assert [e["message"] for e in read_events(tmp_path)] == ["hello"]
        sink.flush()
        assert [e["message"] for e in read_events(tmp_path)] == ["hello", "world"]
        assert sink.last_line == "world"

    def test_carriage_return_discards_unfinished_line(self, tmp_path: Path) -> None:
        """A progress meter collapses into the final line."""
        sink = JobLogSink(EventWriter(tmp_path))
        sink("10%\r50%\r100%\n")
        assert [e["message"] for e in read_events(tmp_path)] == ["100%"]

    def test_blank_line_emits_nothing(self, tmp_path: Path) -> None:
        """Whitespace-only lines are not events."""
        sink = JobLogSink(EventWriter(tmp_path))
        sink("   \n")
        assert read_events(tmp_path) == []
        assert sink.last_line is None

    def test_rule_line_is_not_the_summary(self, tmp_path: Path) -> None:
        """A line of box-drawing has no alphanumerics: logged, not remembered."""
        sink = JobLogSink(EventWriter(tmp_path))
        sink("Done\n────\n")
        assert sink.last_line == "Done"
        assert len(read_events(tmp_path)) == 2

    def test_remembers_last_error(self, tmp_path: Path) -> None:
        """Error-level lines are kept for the job verdict."""
        sink = JobLogSink(EventWriter(tmp_path))
        sink("Error: bad\nok\n")
        assert sink.last_error == "Error: bad"
        events = read_events(tmp_path)
        assert [e["level"] for e in events] == ["error", "info"]


class TestJobProgress:
    """Throttled progress events."""

    def test_phase_announces_at_once(self, tmp_path: Path) -> None:
        """A phase start always emits, with its total."""
        progress = JobProgress(EventWriter(tmp_path))
        progress.phase("Scanning", 4)
        (event,) = read_events(tmp_path)
        assert event["label"] == "Scanning"
        assert event["total"] == 4
        assert event["step"] == 0
        assert "item" not in event
        assert "eta_seconds" not in event

    def test_advance_is_throttled_but_final_step_forced(self, tmp_path: Path) -> None:
        """Steps inside the interval are dropped; reaching the total is not."""
        with patch(_CLOCK, return_value=100.0):
            progress = JobProgress(EventWriter(tmp_path))
            progress.phase("Scanning", 3)
            progress.advance("a")  # Throttled.
            progress.advance("b")  # Throttled.
            progress.advance("c")  # Final step: forced.
        events = read_events(tmp_path)
        assert [e["step"] for e in events] == [0, 3]
        assert events[-1]["item"] == "c"

    def test_explicit_step_and_eta(self, tmp_path: Path) -> None:
        """An explicit step is used; elapsed time yields an ETA."""
        times = iter([0.0, 0.0, 0.0, 10.0])  # init, phase (x2), advance
        with patch(_CLOCK, side_effect=lambda: next(times)):
            progress = JobProgress(EventWriter(tmp_path))
            progress.phase("Fetching", 10)
            progress.advance(step=5)
        last = read_events(tmp_path)[-1]
        assert last["step"] == 5
        assert last["eta_seconds"] == 10

    def test_indeterminate_total_is_not_forced(self, tmp_path: Path) -> None:
        """Without a total, ``advance`` never counts as the final step."""
        with patch(_CLOCK, return_value=100.0):
            progress = JobProgress(EventWriter(tmp_path))
            progress.phase("Working")
            progress.advance("x")
        assert len(read_events(tmp_path)) == 1


class TestEventLogHandler:
    """WARNING-and-above log records reach the UI."""

    def _handler(self, tmp_path: Path) -> EventLogHandler:
        return EventLogHandler(EventWriter(tmp_path))

    def test_warning_and_error_levels(self, tmp_path: Path) -> None:
        """Warning and error records map to their levels."""
        handler = self._handler(tmp_path)
        for level, text in ((logging.WARNING, "w"), (logging.CRITICAL, "e")):
            handler.emit(logging.LogRecord("x", level, "f", 1, text, None, None))
        events = read_events(tmp_path)
        assert [(e["level"], e["message"]) for e in events] == [
            ("warning", "w"),
            ("error", "e"),
        ]

    def test_bad_format_args_fall_back_to_raw_message(self, tmp_path: Path) -> None:
        """A record whose %-formatting fails still logs its template."""
        handler = self._handler(tmp_path)
        record = logging.LogRecord("x", logging.ERROR, "f", 1, "n=%d", ("a",), None)
        handler.emit(record)
        assert read_events(tmp_path)[0]["message"] == "n=%d"

    def test_ignores_info(self, tmp_path: Path) -> None:
        """The handler's own level filters INFO out."""
        logger = logging.getLogger("jobs_io_test")
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = self._handler(tmp_path)
        logger.addHandler(handler)
        try:
            logger.info("chatter")
            logger.warning("careful")
        finally:
            logger.removeHandler(handler)
        assert [e["message"] for e in read_events(tmp_path)] == ["careful"]
