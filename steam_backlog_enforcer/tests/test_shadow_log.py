"""Tests for the shadow verdict journal: one budget.jsonl record per change."""

from __future__ import annotations

import json

from steam_backlog_enforcer import _playtime_log as log_mod
from steam_backlog_enforcer._budget_log_tail import last_verdict
from steam_backlog_enforcer._playtime_log import BudgetLog
from steam_backlog_enforcer._playtime_state import PlaytimeState
from steam_backlog_enforcer._shadow import ShadowVerdict
from steam_backlog_enforcer._shadow_log import EVENT_SHADOW_CHANGE, ShadowJournal

_STATE = PlaytimeState(
    day_key="2026-10-19",
    shadow_seconds=30.0,
    shadow_budget_seconds=36000.0,
    shadow_per_source={"app:440": 30.0},
    shadow_paused_seconds=6.0,
)


def _records() -> list[dict[str, object]]:
    text = log_mod.BUDGET_LOG_FILE.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _journal() -> ShadowJournal:
    return ShadowJournal(BudgetLog(path=log_mod.BUDGET_LOG_FILE))


class TestShadowJournal:
    def test_writes_on_change_only(self) -> None:
        journal = _journal()
        leisure = ShadowVerdict(paused_by=None, keys=("app:440",))
        journal.observe(leisure, _STATE)
        journal.observe(leisure, _STATE)
        journal.observe(ShadowVerdict(paused_by="i3lock", keys=()), _STATE)
        records = _records()
        assert [r["shadow_state"] for r in records] == ["leisure", "paused"]
        assert {r["event"] for r in records} == {EVENT_SHADOW_CHANGE}

    def test_a_new_source_is_a_change(self) -> None:
        journal = _journal()
        journal.observe(ShadowVerdict(None, ("a",)), _STATE)
        journal.observe(ShadowVerdict(None, ("b",)), _STATE)
        assert [r["sources"] for r in _records()] == [["a"], ["b"]]

    def test_carries_the_shadow_fields(self) -> None:
        _journal().observe(ShadowVerdict(None, ("app:440",)), _STATE)
        record = _records()[0]
        assert record["day_key"] == "2026-10-19"
        assert record["shadow_seconds"] == 30.0
        assert record["shadow_budget_seconds"] == 36000.0
        assert record["shadow_remaining_seconds"] == 35970.0
        assert record["shadow_paused_seconds"] == 6.0
        assert record["shadow_per_source"] == {"app:440": 30.0}
        assert record["paused_by"] is None

    def test_live_status_skips_shadow_records(self) -> None:
        """The web UI's live game view reads the last *game* verdict."""
        log = BudgetLog(path=log_mod.BUDGET_LOG_FILE)
        log.record("verdict_change", state="engaged", qualifying=[])
        ShadowJournal(log).observe(ShadowVerdict(None, ("a",)), _STATE)
        assert last_verdict(demo=False).state == "engaged"
