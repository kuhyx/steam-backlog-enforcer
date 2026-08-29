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

_PKG = "steam_backlog_enforcer._playtime_history"


def _raw() -> dict:
    return json.loads(history_mod.HISTORY_FILE.read_text(encoding="utf-8"))


def _stored() -> dict[str, float]:
    """Day totals, with the per-game breakdown unwrapped away."""
    return {day: entry["seconds"] for day, entry in _raw()["days"].items()}


class TestRecordDay:
    """Tests for record_day."""

    def test_creates_and_upserts(self) -> None:
        record_day("2026-08-27", 100.0, {})
        record_day("2026-08-28", 200.0, {})
        record_day("2026-08-28", 250.0, {})
        assert _stored() == {"2026-08-27": 100.0, "2026-08-28": 250.0}

    def test_written_world_readable(self) -> None:
        record_day("2026-08-28", 1.0, {})
        assert history_mod.HISTORY_FILE.stat().st_mode & 0o777 == 0o644

    def test_trims_to_the_retention_window(self) -> None:
        with patch(f"{_PKG}._MAX_DAYS", 2):
            for day in ("2026-08-26", "2026-08-27", "2026-08-28"):
                record_day(day, 1.0, {})
        assert sorted(_stored()) == ["2026-08-27", "2026-08-28"]


class TestLoadHistory:
    """Tests for load_history and its guards."""

    def test_missing_file_is_empty(self) -> None:
        assert load_history() == []

    def test_returns_oldest_first_and_limited(self) -> None:
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
        record_day("2026-08-28", 1.0, {})
        assert load_history(0) == []

    def test_unparseable_file_is_ignored(self) -> None:
        history_mod.HISTORY_FILE.write_text("{not json", encoding="utf-8")
        assert load_history() == []

    def test_unreadable_file_is_ignored(self) -> None:
        record_day("2026-08-28", 1.0, {})
        with patch("pathlib.Path.read_text", side_effect=PermissionError):
            assert load_history() == []

    def test_unknown_schema_is_ignored(self) -> None:
        history_mod.HISTORY_FILE.write_text(
            json.dumps({"schema_version": 99, "days": {}}), encoding="utf-8"
        )
        assert load_history() == []

    def test_non_mapping_payload_is_ignored(self) -> None:
        history_mod.HISTORY_FILE.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        assert load_history() == []

    def test_non_mapping_days_is_ignored(self) -> None:
        history_mod.HISTORY_FILE.write_text(
            json.dumps({"schema_version": 1, "days": ["nope"]}), encoding="utf-8"
        )
        assert load_history() == []

    def test_bad_entries_are_dropped(self) -> None:
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
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False)
        assert _stored() == {"2026-08-28": 10.0}

    def test_skips_a_small_move(self) -> None:
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False)
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=12.0), demo=False)
        assert _stored() == {"2026-08-28": 10.0}

    def test_records_a_large_move(self) -> None:
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False)
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=90.0), demo=False)
        assert _stored() == {"2026-08-28": 90.0}

    def test_records_a_refund(self) -> None:
        # backdate() can move the counter *down* by the idle grace.
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=400.0), demo=False)
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=100.0), demo=False)
        assert _stored() == {"2026-08-28": 100.0}

    def test_records_the_new_day_after_rollover(self) -> None:
        writer = HistoryWriter()
        writer.observe(PlaytimeState(day_key="2026-08-27", seconds=500.0), demo=False)
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=0.0), demo=False)
        assert _stored() == {"2026-08-27": 500.0, "2026-08-28": 0.0}

    def test_demo_runs_are_not_recorded(self) -> None:
        HistoryWriter().observe(
            PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=True
        )
        assert not history_mod.HISTORY_FILE.exists()

    def test_stateless_record_is_not_written(self) -> None:
        HistoryWriter().observe(PlaytimeState(day_key="", seconds=10.0), demo=False)
        assert not history_mod.HISTORY_FILE.exists()

    def test_write_failure_does_not_raise(self) -> None:
        writer = HistoryWriter()
        with patch(f"{_PKG}.record_day", side_effect=OSError("read-only")):
            writer.observe(
                PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False
            )
        assert not history_mod.HISTORY_FILE.exists()
        # Not remembered as written, so the next attempt tries again.
        writer.observe(PlaytimeState(day_key="2026-08-28", seconds=10.0), demo=False)
        assert _stored() == {"2026-08-28": 10.0}


class TestPerGameBreakdown:
    """The per-game dimension, and the legacy shape it had to grow out of."""

    def test_round_trips_games_and_labels(self) -> None:
        record_day("2026-08-28", 300.0, {"proc:osu-lazer": 200.0})
        stored = _raw()
        assert stored["days"]["2026-08-28"]["games"] == {"proc:osu-lazer": 200.0}
        assert stored["labels"]["proc:osu-lazer"] == "osu!lazer"

    def test_a_later_flush_preserves_other_days(self) -> None:
        """Regression: the writer read through a lossy view and rewrote it.

        A whole-file read-modify-write built from a reader that dropped the
        `games` sub-dict destroyed every other day's breakdown roughly once a
        minute, so a bar kept its total and silently lost its bands.
        """
        record_day("2026-08-27", 300.0, {"proc:osu-lazer": 300.0})
        record_day("2026-08-28", 100.0, {"app:440": 100.0})
        assert _raw()["days"]["2026-08-27"]["games"] == {"proc:osu-lazer": 300.0}

    def test_reads_a_schema_1_bare_float(self) -> None:
        """Days recorded before attribution existed keep their total."""
        history_mod.HISTORY_FILE.write_text(
            json.dumps({"schema_version": 1, "days": {"2026-08-20": 1234.5}}),
            encoding="utf-8",
        )
        days = load_history()
        assert [(d.day, d.seconds, d.games) for d in days] == [
            ("2026-08-20", 1234.5, {})
        ]

    def test_drops_malformed_games_and_labels(self) -> None:
        history_mod.HISTORY_FILE.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "days": {
                        "2026-08-28": {"seconds": 10, "games": {"ok": 5, "bad": "x"}},
                        "2026-08-27": {"seconds": True},
                        "2026-08-26": {"games": {}},
                        "2026-08-25": ["nope"],
                    },
                    "labels": {"ok": "Fine", "bad": 7},
                }
            ),
            encoding="utf-8",
        )
        days = {d.day: d.games for d in load_history()}
        assert days == {"2026-08-28": {"ok": 5.0}}
        assert history_mod.load_labels() == {"ok": "Fine"}

    def test_non_mapping_games_is_ignored(self) -> None:
        history_mod.HISTORY_FILE.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "days": {"2026-08-28": {"seconds": 5, "games": 3}},
                }
            ),
            encoding="utf-8",
        )
        assert [d.games for d in load_history()] == [{}]

    def test_non_mapping_labels_is_ignored(self) -> None:
        history_mod.HISTORY_FILE.write_text(
            json.dumps({"schema_version": 1, "days": {}, "labels": "nope"}),
            encoding="utf-8",
        )
        assert history_mod.load_labels() == {}
