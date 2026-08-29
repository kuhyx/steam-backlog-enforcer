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
from steam_backlog_enforcer._engagement_types import (
    CAUSE_IDLE,
    STATE_ENGAGED,
    STATE_NOT_APPLICABLE,
    STATE_PAUSED,
    EngagementVerdict,
)
from steam_backlog_enforcer._playtime_log import (
    EVENT_DETECTOR_FAILURE,
    EVENT_HEARTBEAT,
    EVENT_VERDICT_CHANGE,
    BudgetLog,
    TickJournal,
    budget_log_path,
)
from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

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
    def test_production_run_journals_to_the_real_trail(self) -> None:
        assert budget_log_path(demo=False) == log_mod.BUDGET_LOG_FILE

    def test_demo_run_cannot_reach_the_production_trail(self) -> None:
        # A demo bills against a 60-second budget. Letting those records land
        # in the production log makes the log unusable for the one job it has:
        # reconstructing what the real budget actually did.
        assert budget_log_path(demo=True) == log_mod.BUDGET_DEMO_LOG_FILE
        assert budget_log_path(demo=True) != log_mod.BUDGET_LOG_FILE


class TestBudgetLog:
    def test_creates_its_directory_on_first_write(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "budget.jsonl"
        log = BudgetLog(path=target)
        log.record("hello", answer=42)
        log.close()
        assert _records(target)[0]["answer"] == 42

    def test_closing_an_unopened_sink_is_a_no_op(self, tmp_path: Path) -> None:
        BudgetLog(path=tmp_path / "budget.jsonl").close()

    def test_a_second_sink_on_the_same_path_replaces_the_first(
        self, tmp_path: Path
    ) -> None:
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
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        log.record("thing")
        log.close()
        record = _records(target)[0]
        assert record["event"] == "thing"
        assert record["timestamp"]

    def test_reuses_the_sink_across_records(self, tmp_path: Path) -> None:
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        log.record("one")
        log.record("two")
        log.close()
        assert [r["event"] for r in _records(target)] == ["one", "two"]

    def test_an_uncreatable_path_does_not_raise(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("not a directory")
        BudgetLog(path=blocker / "budget.jsonl").record("dropped")

    def test_an_unserialisable_payload_does_not_raise(self, tmp_path: Path) -> None:
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        with patch(f"{PL}.json.dumps", side_effect=ValueError("nope")):
            log.record("bad")
        log.close()

    def test_a_write_failure_does_not_raise(self, tmp_path: Path) -> None:
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        log.record("first")
        with patch(f"{PL}.json.dumps", side_effect=OSError("disk gone")):
            log.record("second")
        log.close()


class TestTickJournal:
    def _journal(self, tmp_path: Path, **kwargs: float) -> tuple[TickJournal, Path]:
        target = tmp_path / "budget.jsonl"
        log = BudgetLog(path=target)
        self._logs.append(log)
        return TickJournal(log, **kwargs), target

    @pytest.fixture(autouse=True)
    def _close_logs(self) -> Iterator[None]:
        self._logs: list[BudgetLog] = []
        yield
        for log in self._logs:
            log.close()

    def _observe(
        self, journal: TickJournal, verdict: EngagementVerdict, at: float
    ) -> None:
        journal.observe(verdict, STATE, rules=RULES, now_monotonic=at)

    def test_a_changed_verdict_is_recorded(self, tmp_path: Path) -> None:
        journal, target = self._journal(tmp_path)
        self._observe(journal, EngagementVerdict(state=STATE_ENGAGED), 0.0)
        events = [r["event"] for r in _records(target)]
        assert events == [EVENT_VERDICT_CHANGE]

    def test_an_unchanged_verdict_is_not_repeated(self, tmp_path: Path) -> None:
        journal, target = self._journal(tmp_path, heartbeat=300.0)
        verdict = EngagementVerdict(state=STATE_ENGAGED)
        for tick in range(5):
            self._observe(journal, verdict, float(tick) * 3.0)
        assert len(_records(target)) == 1

    def test_a_heartbeat_is_written_once_the_interval_passes(
        self, tmp_path: Path
    ) -> None:
        journal, target = self._journal(tmp_path, heartbeat=10.0)
        verdict = EngagementVerdict(state=STATE_ENGAGED)
        self._observe(journal, verdict, 0.0)
        self._observe(journal, verdict, 5.0)
        self._observe(journal, verdict, 50.0)
        assert [r["event"] for r in _records(target)] == [
            EVENT_VERDICT_CHANGE,
            EVENT_HEARTBEAT,
        ]

    def test_ordinary_desktop_use_produces_no_heartbeat(self, tmp_path: Path) -> None:
        journal, target = self._journal(tmp_path, heartbeat=0.0)
        verdict = EngagementVerdict(state=STATE_NOT_APPLICABLE)
        self._observe(journal, verdict, 0.0)
        self._observe(journal, verdict, 1000.0)
        assert len(_records(target)) == 1

    def test_a_degraded_probe_is_always_recorded(self, tmp_path: Path) -> None:
        journal, target = self._journal(tmp_path)
        verdict = EngagementVerdict(state=STATE_ENGAGED, degraded=("idle",))
        self._observe(journal, verdict, 0.0)
        self._observe(journal, verdict, 3.0)
        events = [r["event"] for r in _records(target)]
        assert events.count(EVENT_DETECTOR_FAILURE) == 2
        assert all(r.get("billed", True) for r in _records(target))

    def test_the_snapshot_names_the_qualifying_processes(self, tmp_path: Path) -> None:
        # Without these, accrual from an orphaned helper process cannot be
        # attributed after the fact.
        journal, target = self._journal(tmp_path)
        verdict = EngagementVerdict(
            state=STATE_PAUSED,
            causes=(CAUSE_IDLE,),
            idle_seconds=310.0,
            qualifying=(11, 22),
        )
        self._observe(journal, verdict, 0.0)
        record = _records(target)[0]
        assert record["qualifying"] == [11, 22]
        assert record["reason"] == "idle"
        assert record["remaining_seconds"] == 28700.0
