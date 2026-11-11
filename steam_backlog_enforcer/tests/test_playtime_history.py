"""Tests for _playtime_history module — 100% branch coverage."""

from __future__ import annotations

import json
from unittest.mock import patch

from steam_backlog_enforcer import _playtime_history as history_mod
from steam_backlog_enforcer._playtime_history import (
    HistoryWriter,
    load_history,
    record_day,
)
from steam_backlog_enforcer._playtime_state import PlaytimeState
from steam_backlog_enforcer.tests._playtime_history_files import stored

_PKG = "steam_backlog_enforcer._playtime_history"


class TestRecordDay:
    """Tests for record_day."""

    def test_creates_and_upserts(self) -> None:
        """record_day creates the file and overwrites a day it already has."""
        record_day("2026-08-27", 100.0, {})
        record_day("2026-08-28", 200.0, {})
        record_day("2026-08-28", 250.0, {})
        assert stored() == {"2026-08-27": 100.0, "2026-08-28": 250.0}

    def test_written_world_readable(self) -> None:
        """The history file is written mode 0644."""
        record_day("2026-08-28", 1.0, {})
        assert history_mod.HISTORY_FILE.stat().st_mode & 0o777 == 0o644

    def test_trims_to_the_retention_window(self) -> None:
        """Days beyond the retention window are dropped."""
        with patch(f"{_PKG}._MAX_DAYS", 2):
            for day in ("2026-08-26", "2026-08-27", "2026-08-28"):
                record_day(day, 1.0, {})
        assert sorted(stored()) == ["2026-08-27", "2026-08-28"]


class TestLoadHistory:
    """Tests for load_history and its guards."""

    def test_missing_file_is_empty(self) -> None:
        """A missing file loads as no history."""
        assert load_history() == []

    def test_returns_oldest_first_and_limited(self) -> None:
        """load_history returns the newest days up to the limit, oldest first."""
        for day, seconds in (
            ("2026-08-26", 1.0),
            ("2026-08-27", 2.0),
            ("2026-08-28", 3.0),
        ):
            record_day(day, seconds, {})
        days = load_history(2)
        assert [d.day for d in days] == ["2026-08-27", "2026-08-28"]
        assert days[0].seconds == 2.0

    def test_zero_limit_returns_nothing(self) -> None:
        """A zero limit returns nothing."""
        record_day("2026-08-28", 1.0, {})
        assert load_history(0) == []

    def test_unparseable_file_is_ignored(self) -> None:
        """A corrupt file loads as no history."""
        history_mod.HISTORY_FILE.write_text("{not json", encoding="utf-8")
        assert load_history() == []

    def test_unreadable_file_is_ignored(self) -> None:
        """An unreadable file loads as no history."""
        record_day("2026-08-28", 1.0, {})
        with patch("pathlib.Path.read_text", side_effect=PermissionError):
            assert load_history() == []

    def test_unknown_schema_is_ignored(self) -> None:
        """An unknown schema version loads as no history."""
        history_mod.HISTORY_FILE.write_text(
            json.dumps({"schema_version": 99, "days": {}}), encoding="utf-8"
        )
        assert load_history() == []

    def test_non_mapping_payload_is_ignored(self) -> None:
        """A non-object payload loads as no history."""
        history_mod.HISTORY_FILE.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        assert load_history() == []

    def test_non_mapping_days_is_ignored(self) -> None:
        """A non-object days field loads as no history."""
        history_mod.HISTORY_FILE.write_text(
            json.dumps({"schema_version": 1, "days": ["nope"]}), encoding="utf-8"
        )
        assert load_history() == []

    def test_bad_entries_are_dropped(self) -> None:
        """Malformed day entries are dropped, good ones kept."""
        # The file is neither root-owned nor immutable, so anything can be in it.
        history_mod.HISTORY_FILE.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "days": {"2026-08-28": 5, "2026-08-27": "x", "9": None},
                }
            ),
            encoding="utf-8",
        )
        assert [(d.day, d.seconds) for d in load_history()] == [("2026-08-28", 5.0)]


class TestHistoryWriter:
    """Tests for the throttled writer."""

    def test_records_a_new_day_immediately(self) -> None:
        """The first observation of a day is written at once."""
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False)
        assert stored() == {"2026-08-28": 10.0}

    def test_skips_a_small_move(self) -> None:
        """A small change since the last write is not written."""
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False)
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=12.0), demo=False)
        assert stored() == {"2026-08-28": 10.0}

    def test_records_a_large_move(self) -> None:
        """A large change since the last write is written."""
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False)
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=90.0), demo=False)
        assert stored() == {"2026-08-28": 90.0}

    def test_records_a_refund(self) -> None:
        """A downward move (idle refund) is written."""
        # backdate() can move the counter *down* by the idle grace.
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=400.0), demo=False)
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=100.0), demo=False)
        assert stored() == {"2026-08-28": 100.0}

    def test_records_the_new_day_after_rollover(self) -> None:
        """A new day after rollover is written beside the old one."""
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-27", seconds=500.0), demo=False)
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=0.0), demo=False)
        assert stored() == {"2026-08-27": 500.0, "2026-08-28": 0.0}

    def test_demo_runs_are_not_recorded(self) -> None:
        """Demo observations never touch the file."""
        HistoryWriter().observe(
            PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=True
        )
        assert not history_mod.HISTORY_FILE.exists()

    def test_stateless_record_is_not_written(self) -> None:
        """A state without a day key is not written."""
        HistoryWriter().observe(PlaytimeState(day_key="", seconds=10.0), demo=False)
        assert not history_mod.HISTORY_FILE.exists()

    def test_write_failure_does_not_raise(self) -> None:
        """A failed write is swallowed."""
        writer = HistoryWriter()
        with patch(f"{_PKG}.record_day", side_effect=OSError("read-only")):
            writer.observe(
                PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False
            )
        assert not history_mod.HISTORY_FILE.exists()
        # Not remembered as written, so the next attempt tries again.
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False)
        assert stored() == {"2026-08-28": 10.0}
