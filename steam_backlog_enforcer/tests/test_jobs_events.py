"""Tests for ``jobs._events``: the JSONL log and its gap-free writer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from steam_backlog_enforcer.jobs._events import (
    EVENTS_NAME,
    EventWriter,
    append_jsonl,
    now_iso,
    read_events,
    read_jsonl,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestNowIso:
    """The timestamp format."""

    def test_second_precision_with_z(self) -> None:
        """ISO-8601, UTC, ``Z`` suffix."""
        stamp = now_iso()
        assert len(stamp) == len("2026-10-10T12:00:00Z")
        assert stamp.endswith("Z")


class TestReadJsonl:
    """Parsing tolerates torn and damaged lines."""

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        """No file, no entries."""
        assert read_jsonl(tmp_path / "nope.jsonl") == []

    def test_skips_torn_final_line(self, tmp_path: Path) -> None:
        """A line without its newline is still being written."""
        path = tmp_path / "x.jsonl"
        path.write_text('{"a": 1}\n{"b": 2', encoding="utf-8")
        assert read_jsonl(path) == [{"a": 1}]

    def test_skips_bad_and_non_object_lines(self, tmp_path: Path) -> None:
        """Garbage and non-dict JSON are dropped."""
        path = tmp_path / "x.jsonl"
        path.write_text('{"a": 1}\nnot json\n[1, 2]\n{"c": 3}\n', encoding="utf-8")
        assert read_jsonl(path) == [{"a": 1}, {"c": 3}]

    def test_whole_file_without_newline_is_incomplete(self, tmp_path: Path) -> None:
        """A single unterminated line yields nothing."""
        path = tmp_path / "x.jsonl"
        path.write_text('{"a": 1}', encoding="utf-8")
        assert read_jsonl(path) == []


class TestAppendJsonl:
    """Appending one object per line."""

    def test_appends_lines(self, tmp_path: Path) -> None:
        """Each call adds one parseable line."""
        path = tmp_path / "x.jsonl"
        append_jsonl(path, {"a": 1})
        append_jsonl(path, {"b": 2})
        assert read_jsonl(path) == [{"a": 1}, {"b": 2}]


class TestReadEvents:
    """Filtering by ``seq``."""

    def test_after_seq_and_non_int_seq(self, tmp_path: Path) -> None:
        """Only int ``seq`` greater than the cursor is returned."""
        lines = [{"seq": 1}, {"seq": 2}, {"seq": "3"}, {"type": "x"}]
        (tmp_path / EVENTS_NAME).write_text(
            "".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8"
        )
        assert read_events(tmp_path) == [{"seq": 1}, {"seq": 2}]
        assert read_events(tmp_path, after_seq=1) == [{"seq": 2}]


class TestEventWriter:
    """Gap-free sequence numbers, even with another writer around."""

    def test_sequence_and_fields(self, tmp_path: Path) -> None:
        """Events number from 1 and carry type, timestamp and fields."""
        writer = EventWriter(tmp_path)
        first = writer.emit("state", state="running")
        second = writer.emit("log", level="info", message="hi")
        assert (first["seq"], second["seq"]) == (1, 2)
        assert second["type"] == "log"
        assert second["message"] == "hi"
        assert "ts" in second
        assert read_events(tmp_path) == [first, second]

    def test_continues_after_foreign_append(self, tmp_path: Path) -> None:
        """A write by someone else makes the writer recompute ``seq``."""
        writer = EventWriter(tmp_path)
        writer.emit("state", state="queued")
        other = EventWriter(tmp_path)
        other.emit("log", level="info", message="from the server")
        third = writer.emit("state", state="running")
        assert third["seq"] == 3
        assert [e["seq"] for e in read_events(tmp_path)] == [1, 2, 3]

    def test_new_writer_resumes_existing_file(self, tmp_path: Path) -> None:
        """The first emit of a fresh writer reads the last ``seq`` on disk."""
        EventWriter(tmp_path).emit("state", state="queued")
        assert EventWriter(tmp_path).emit("state", state="running")["seq"] == 2
