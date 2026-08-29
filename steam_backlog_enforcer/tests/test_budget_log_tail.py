"""Tests for _budget_log_tail module — 100% branch coverage."""

from __future__ import annotations

import json
from unittest.mock import patch

from steam_backlog_enforcer import _playtime_log as log_mod
from steam_backlog_enforcer._budget_log_tail import last_verdict

_PKG = "steam_backlog_enforcer._budget_log_tail"


def _write(lines: list[str]) -> None:
    log_mod.BUDGET_LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _record(**over: object) -> str:
    body: dict[str, object] = {
        "timestamp": "2026-08-28T20:42:19+02:00",
        "event": "verdict_change",
        "state": "engaged",
        "reason": "engaged",
        "causes": [],
        "idle_seconds": 1.5,
        "screen_held": False,
        "qualifying": [],
        "day_key": "2026-08-28",
        "billed_seconds": 100.0,
    }
    body.update(over)
    return json.dumps(body)


class TestLastVerdict:
    """Tests for reading the tail of the audit log."""

    def test_missing_log_is_unavailable(self) -> None:
        view = last_verdict(demo=False)
        assert view.available is False
        assert view.state == ""

    def test_reads_the_last_record(self) -> None:
        _write([_record(state="paused"), _record(state="engaged", reason="ok")])
        view = last_verdict(demo=False)
        assert view.available is True
        assert view.state == "engaged"
        assert view.reason == "ok"
        assert view.idle_seconds == 1.5
        assert view.screen_held is False
        assert view.observed_at.startswith("2026-08-28")

    def test_skips_a_malformed_last_line(self) -> None:
        _write([_record(state="engaged"), "{ this is not json"])
        assert last_verdict(demo=False).state == "engaged"

    def test_empty_log_is_unavailable(self) -> None:
        log_mod.BUDGET_LOG_FILE.write_text("", encoding="utf-8")
        assert last_verdict(demo=False).available is False

    def test_a_json_scalar_is_not_a_record(self) -> None:
        _write(["42"])
        assert last_verdict(demo=False).available is False

    def test_unreadable_log_is_unavailable(self) -> None:
        _write([_record()])
        with patch("pathlib.Path.open", side_effect=PermissionError):
            assert last_verdict(demo=False).available is False

    def test_reads_only_the_tail(self) -> None:
        # Seeking back a fixed number of bytes lands mid-record; that leading
        # fragment must be skipped rather than crashing the read.
        newest = _record(state="newest")
        _write([_record(state="old")] * 50 + [newest])
        with patch(f"{_PKG}._TAIL_BYTES", len(newest) + 20):
            assert last_verdict(demo=False).state == "newest"

    def test_a_tail_shorter_than_one_record_finds_nothing(self) -> None:
        _write([_record(state="newest")])
        with patch(f"{_PKG}._TAIL_BYTES", 10):
            assert last_verdict(demo=False).available is False

    def test_demo_log_is_read_separately(self) -> None:
        _write([_record(state="production")])
        log_mod.BUDGET_DEMO_LOG_FILE.write_text(
            _record(state="demo") + "\n", encoding="utf-8"
        )
        assert last_verdict(demo=True).state == "demo"
        assert last_verdict(demo=False).state == "production"

    def test_missing_and_odd_fields_default(self) -> None:
        _write([json.dumps({"event": "heartbeat"})])
        view = last_verdict(demo=False)
        assert view.available is True
        assert view.state == ""
        assert view.causes == []
        assert view.idle_seconds is None
        assert view.screen_held is None
        assert view.observed_at == ""

    def test_non_list_causes_are_dropped(self) -> None:
        _write([_record(causes="focus")])
        assert last_verdict(demo=False).causes == []


class TestLiveGames:
    """Tests for resolving qualifying PIDs to live processes."""

    def test_resolves_running_pids(self) -> None:
        _write([_record(qualifying=[1, 2])])
        with patch(f"{_PKG}.process_name", side_effect=["alpha", "beta"]):
            games = last_verdict(demo=False).games
        assert [(g.pid, g.name) for g in games] == [(1, "alpha"), (2, "beta")]

    def test_drops_pids_that_have_exited(self) -> None:
        # A recycled PID would otherwise be reported under the wrong process.
        _write([_record(qualifying=[1, 2])])
        with patch(f"{_PKG}.process_name", side_effect=["alpha", None]):
            games = last_verdict(demo=False).games
        assert [g.name for g in games] == ["alpha"]

    def test_ignores_non_integer_pids(self) -> None:
        _write([_record(qualifying=["nope"])])
        assert last_verdict(demo=False).games == []

    def test_non_list_qualifying_is_dropped(self) -> None:
        _write([_record(qualifying=7)])
        assert last_verdict(demo=False).games == []
