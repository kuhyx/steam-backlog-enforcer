"""Tests for the budget audit trail.

Two properties matter. It must never raise — a logging failure taking down the
enforcer would be worse than the missing record — and it must not write a line
per tick, which at a three-second interval would be 28 800 lines a day.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _playtime_log as log_mod
from steam_backlog_enforcer._playtime_log import (
    EVENT_HEARTBEAT,
    EVENT_VERDICT_CHANGE,
    BudgetLog,
    TickJournal,
    budget_log_path,
)
from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    _MakeJournal = Callable[..., tuple[TickJournal, Path]]

PL = "steam_backlog_enforcer._playtime_log"

RULES = PlaytimeRules(
    budget_seconds=28800.0,
    warn_at=(3600,),
    sigkill_after=30.0,
    count_launchers=True,
    enforcement=True,
    demo=False,
)
STATE = PlaytimeState(day_key="2026-08-28", seconds=100.0)


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestBudgetLogPath:
    """Production and demo runs journal to separate trails."""

    def test_production_run_journals_to_the_real_trail(self) -> None:
        """A production run writes the real budget log."""
        assert budget_log_path(demo=False) == log_mod.BUDGET_LOG_FILE

    def test_demo_run_cannot_reach_the_production_trail(self) -> None:
        """A demo run writes only the demo log."""
        # A demo bills against a 60-second budget. Letting those records land
        # in the production log makes the log unusable for the one job it has:
        # reconstructing what the real budget actually did.
        assert budget_log_path(demo=True) == log_mod.BUDGET_DEMO_LOG_FILE
        assert budget_log_path(demo=True) != log_mod.BUDGET_LOG_FILE


class TestBudgetLog:
    """The JSONL sink: lazy open, one handler per path, never raises."""

    def test_creates_its_directory_on_first_write(self, tmp_path: Path) -> None:
        """Missing parent directories are created on the first record."""
        target = tmp_path / "deep" / "nested" / "budget.jsonl"
        log = BudgetLog(path=target)
        log.record("hello", answer=42)
        log.close()
        assert _records(target)[0]["answer"] == 42

    def test_closing_an_unopened_sink_is_a_no_op(self, tmp_path: Path) -> None:
        """Closing before any write does nothing."""
        BudgetLog(path=tmp_path / "budget.jsonl").close()

    def test_a_second_sink_on_the_same_path_replaces_the_first(
        self, tmp_path: Path
    ) -> None:
        """A second sink on one path takes over and both records land."""
        # Two sinks share a logger name; the stale handler must be closed
        # rather than silently dropped, or the file descriptor leaks.
        target = tmp_path / "budget.jsonl"
        first = BudgetLog(path=target)
        first.record("one")
        second = BudgetLog(path=target)
        second.record("two")
        second.close()
        assert [r["event"] for r in _records(target)] == ["one", "two"]

    def test_every_record_carries_a_timestamp_and_event(self, tmp_path: Path) -> None:
        """Each record has its event name and a timestamp."""
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        log.record("thing")
        log.close()
        record = _records(target)[0]
        assert record["event"] == "thing"
        assert record["timestamp"]

    def test_reuses_the_sink_across_records(self, tmp_path: Path) -> None:
        """Several records go through one open sink."""
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        log.record("one")
        log.record("two")
        log.close()
        assert [r["event"] for r in _records(target)] == ["one", "two"]

    def test_an_uncreatable_path_does_not_raise(self, tmp_path: Path) -> None:
        """A path under a regular file is silently dropped."""
        blocker = tmp_path / "file"
        blocker.write_text("not a directory")
        BudgetLog(path=blocker / "budget.jsonl").record("dropped")

    def test_an_unserialisable_payload_does_not_raise(self, tmp_path: Path) -> None:
        """A serialisation error is swallowed."""
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        with patch(f"{PL}.json.dumps", side_effect=ValueError("nope")):
            log.record("bad")
        log.close()

    def test_a_write_failure_does_not_raise(self, tmp_path: Path) -> None:
        """A write error after the first record is swallowed."""
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        log.record("first")
        with patch(f"{PL}.json.dumps", side_effect=OSError("disk gone")):
            log.record("second")
        log.close()


@pytest.fixture(name="make_journal")
def fixture_make_journal(tmp_path: Path) -> Iterator[_MakeJournal]:
    """Build journals over a tmp budget log; close every log afterwards."""
    logs: list[BudgetLog] = []

    def make(**kwargs: float) -> tuple[TickJournal, Path]:
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        logs.append(log)
        return TickJournal(log, **kwargs), target

    yield make
    for log in logs:
        log.close()


class TestTickJournal:
    """The tick journal records verdict changes and sparse heartbeats only."""

    def _observe(self, journal: TickJournal, qualifying: set[int], at: float) -> None:
        journal.observe(qualifying, STATE, rules=RULES, now_monotonic=at)

    def test_a_changed_verdict_is_recorded(self, make_journal: _MakeJournal) -> None:
        """A new verdict writes a verdict-change record."""
        journal, target = make_journal()
        self._observe(journal, {11}, 0.0)
        events = [r["event"] for r in _records(target)]
        assert events == [EVENT_VERDICT_CHANGE]

    def test_an_unchanged_verdict_is_not_repeated(
        self, make_journal: _MakeJournal
    ) -> None:
        """Repeating the same verdict writes nothing more."""
        journal, target = make_journal(heartbeat=300.0)
        for tick in range(5):
            self._observe(journal, {11}, float(tick) * 3.0)
        assert len(_records(target)) == 1

    def test_a_heartbeat_is_written_once_the_interval_passes(
        self, make_journal: _MakeJournal
    ) -> None:
        """An engaged verdict gets a heartbeat after the interval."""
        journal, target = make_journal(heartbeat=10.0)
        self._observe(journal, {11}, 0.0)
        self._observe(journal, {11}, 5.0)
        self._observe(journal, {11}, 50.0)
        assert [r["event"] for r in _records(target)] == [
            EVENT_VERDICT_CHANGE,
            EVENT_HEARTBEAT,
        ]

    def test_ordinary_desktop_use_produces_no_heartbeat(
        self, make_journal: _MakeJournal
    ) -> None:
        """An idle desktop never gets heartbeats."""
        journal, target = make_journal(heartbeat=0.0)
        self._observe(journal, set(), 0.0)
        self._observe(journal, set(), 1000.0)
        assert len(_records(target)) == 1

    def test_the_snapshot_names_the_qualifying_processes(
        self, make_journal: _MakeJournal
    ) -> None:
        """A record lists the sorted qualifying pids and budget numbers."""
        # Without these, accrual from an orphaned helper process cannot be
        # attributed after the fact.
        journal, target = make_journal()
        self._observe(journal, {22, 11}, 0.0)
        record = _records(target)[0]
        assert record["qualifying"] == [11, 22]
        assert record["state"] == "engaged"
        assert record["remaining_seconds"] == 28700.0
        assert record["budget_seconds"] == 28800.0
