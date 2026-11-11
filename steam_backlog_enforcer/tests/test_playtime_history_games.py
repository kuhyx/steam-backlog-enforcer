"""Tests for _playtime_history: the per-game breakdown and its legacy shape.

Split from test_playtime_history.py.
"""

from __future__ import annotations

import json

from steam_backlog_enforcer import _playtime_history as history_mod
from steam_backlog_enforcer._playtime_history import (
    load_history,
    record_day,
)
from steam_backlog_enforcer.tests._playtime_history_files import raw


class TestPerGameBreakdown:
    """The per-game dimension, and the legacy shape it had to grow out of."""

    def test_round_trips_games_and_labels(self) -> None:
        """Per-game seconds and their labels are stored."""
        record_day("2026-08-28", 300.0, {"proc:osu-lazer": 200.0})
        stored = raw()
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
        assert raw()["days"]["2026-08-27"]["games"] == {"proc:osu-lazer": 300.0}

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
        """Malformed per-game entries and labels are dropped."""
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
        """A non-object games field loads as an empty breakdown."""
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
        """A non-object labels field loads as no labels."""
        history_mod.HISTORY_FILE.write_text(
            json.dumps({"schema_version": 1, "days": {}, "labels": "nope"}),
            encoding="utf-8",
        )
        assert history_mod.load_labels() == {}
