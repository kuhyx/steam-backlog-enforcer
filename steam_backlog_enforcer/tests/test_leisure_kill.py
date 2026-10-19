"""Phase 2 at 0: which leisure pids die, how, and what the audit log says."""

from __future__ import annotations

from dataclasses import replace
import os
import signal
from typing import TYPE_CHECKING
from unittest.mock import patch

from leisure_watch.facts import Focus, Now, Reason
import pytest

from steam_backlog_enforcer import _leisure_kill
from steam_backlog_enforcer._leisure_kill import (
    EVENT_LEISURE_KILL,
    LeisureKiller,
    fact_targets,
)
from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState
from steam_backlog_enforcer._shadow import ShadowVerdict
from steam_backlog_enforcer.tests._isolate_leisure import leisure_proc
from steam_backlog_enforcer.tests._leisure_fake_proc import FakeProc, add_proc

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from unittest.mock import MagicMock

_HELIUM = "/opt/helium-browser-bin/helium"
_RULES = PlaytimeRules(
    budget_seconds=100.0,
    warn_at=(),
    sigkill_after=30.0,
    count_launchers=False,
    enforcement=True,
    demo=False,
    leisure=True,
)
_SPENT = PlaytimeState(day_key="2026-11-02", seconds=100.0)


class StubLog:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, object]]] = []

    def record(self, event: str, **fields: object) -> None:
        self.records.append((event, fields))


def _now(*reasons: Reason) -> Now:
    return Now(
        ts=0.0,
        seq=1,
        state="leisure",
        paused_by=None,
        reasons=reasons,
        focus=Focus("Helium", "", None, idle=False),
    )


def _verdict(fact: Now | None, paused: str | None = None) -> ShadowVerdict:
    return ShadowVerdict(paused_by=paused, keys=("k",), fact=fact)


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    root = leisure_proc(tmp_path)
    add_proc(root, FakeProc(10, exe="/usr/bin/mpv"))
    add_proc(root, FakeProc(20, exe=_HELIUM, comm="helium"))
    add_proc(root, FakeProc(30, exe="/usr/bin/chromium", comm="chromium"))
    add_proc(root, FakeProc(40, exe="/usr/bin/vesktop", uid=0))
    return root


@pytest.fixture
def kill() -> Iterator[MagicMock]:
    with patch.object(os, "kill") as mock:
        yield mock


class TestFactTargets:
    def test_media_and_focus_apps_die_browsers_and_games_do_not(
        self, proc: Path
    ) -> None:
        del proc
        fact = _now(
            Reason("media", "app:mpv", 10, "mpv"),
            Reason("focus", "domain:youtube.com", 20, "YouTube"),
            Reason("media", "domain:youtube.com", None, "url"),
            Reason("game", "steam:440", 50, "tf2"),
            Reason("mystery", "x", 10, "?"),
        )
        assert fact_targets(fact) == {10: "app:mpv"}

    @pytest.mark.parametrize(
        ("pid", "key"),
        [
            (20, "failclosed:helium"),
            (20, "failclosed:helium:unreported"),
            (20, "failclosed:helium:audio"),
            (30, "browser:chromium"),
        ],
    )
    def test_a_non_reporting_browser_dies(self, proc: Path, pid: int, key: str) -> None:
        del proc
        fact = _now(Reason("failclosed", key, pid, "x"))
        assert fact_targets(fact) == {pid: key}

    def test_failclosed_without_a_pid_names_nothing(self) -> None:
        fact = _now(Reason("failclosed", "failclosed:display", None, "X"))
        assert fact_targets(fact) == {}


class TestEnforce:
    def test_mpv_is_terminated_then_killed_after_30_s(
        self, proc: Path, kill: MagicMock
    ) -> None:
        del proc
        log = StubLog()
        killer = LeisureKiller(log)
        verdict = _verdict(
            _now(
                Reason("media", "app:mpv", 10, "mpv"),
                Reason("focus", "domain:x.com", 20, "x"),
            )
        )
        for stamp in (1000.0, 1003.0, 1029.0, 1030.0, 1033.0):
            killer.enforce(_SPENT, _RULES, verdict=verdict, stamp=stamp)
        assert [c.args for c in kill.call_args_list] == [
            (10, signal.SIGTERM),
            (10, signal.SIGKILL),
            (10, signal.SIGKILL),
        ]
        assert [(e, f["pid"], f["signal"]) for e, f in log.records] == [
            (EVENT_LEISURE_KILL, 10, "SIGTERM"),
            (EVENT_LEISURE_KILL, 10, "SIGKILL"),
        ]
        first = log.records[0][1]
        assert first["key"] == "app:mpv"
        assert first["name"] == "mpv"
        assert first["why"] == "now.json"
        assert first["day_key"] == "2026-11-02"

    def test_untrusted_watcher_sweeps_but_spares_root(
        self, proc: Path, kill: MagicMock
    ) -> None:
        add_proc(proc, FakeProc(41, exe="/usr/bin/mpv", uid=0))
        killer = LeisureKiller(StubLog())
        for stamp in range(0, 31, 3):  # untrusted for the whole 30 s window
            killer.enforce(_SPENT, _RULES, verdict=_verdict(None), stamp=stamp)
        assert sorted(c.args[0] for c in kill.call_args_list) == [10, 20, 30]

    def test_paused_is_not_stale(self, proc: Path, kill: MagicMock) -> None:
        del proc
        LeisureKiller(StubLog()).enforce(
            _SPENT, _RULES, verdict=_verdict(None, paused="i3lock"), stamp=1.0
        )
        kill.assert_not_called()

    def test_under_budget_forgets_the_timers(self, proc: Path, kill: MagicMock) -> None:
        del proc
        killer = LeisureKiller(None)
        verdict = _verdict(_now(Reason("media", "app:mpv", 10, "mpv")))
        killer.enforce(_SPENT, _RULES, verdict=verdict, stamp=0.0)
        under = PlaytimeState(day_key="2026-11-02", seconds=50.0)
        killer.enforce(under, _RULES, verdict=verdict, stamp=10.0)
        killer.enforce(_SPENT, _RULES, verdict=verdict, stamp=40.0)
        assert [c.args[1] for c in kill.call_args_list] == [signal.SIGTERM] * 2

    def test_a_target_that_drops_out_restarts_its_timer(
        self, proc: Path, kill: MagicMock
    ) -> None:
        del proc
        killer = LeisureKiller(None)
        listed = _verdict(_now(Reason("media", "app:mpv", 10, "mpv")))
        killer.enforce(_SPENT, _RULES, verdict=listed, stamp=0.0)
        killer.enforce(_SPENT, _RULES, verdict=_verdict(_now()), stamp=3.0)
        killer.enforce(_SPENT, _RULES, verdict=listed, stamp=40.0)
        assert [c.args[1] for c in kill.call_args_list] == [signal.SIGTERM] * 2

    def test_a_pid_reused_by_a_new_process_starts_over(
        self, proc: Path, kill: MagicMock
    ) -> None:
        killer = LeisureKiller(None)
        verdict = _verdict(_now(Reason("media", "app:mpv", 10, "mpv")))
        killer.enforce(_SPENT, _RULES, verdict=verdict, stamp=0.0)
        (proc / "10" / "stat").write_text(
            "10 (mpv) S 1 " + "0 " * 17 + "999 0", encoding="utf-8"
        )
        killer.enforce(_SPENT, _RULES, verdict=verdict, stamp=40.0)
        assert [c.args[1] for c in kill.call_args_list] == [signal.SIGTERM] * 2

    def test_a_vanished_or_unsignallable_pid_is_not_logged(
        self, proc: Path, kill: MagicMock
    ) -> None:
        add_proc(proc, FakeProc(11, exe="/usr/bin/vlc"))
        (proc / "12").mkdir()
        (proc / "12" / "status").write_text("Uid:\t1000\t1000\n", encoding="utf-8")
        kill.side_effect = ProcessLookupError
        log = StubLog()
        verdict = _verdict(
            _now(
                Reason("media", "app:vlc", 11, "vlc"),
                Reason("media", "app:ghost", 12, "?"),
            )
        )
        LeisureKiller(log).enforce(_SPENT, _RULES, verdict=verdict, stamp=0.0)
        assert [c.args[0] for c in kill.call_args_list] == [11]
        assert log.records == []

    @pytest.mark.parametrize(
        "rules",
        [
            replace(_RULES, enforcement=False),
            replace(_RULES, demo=True),
            replace(_RULES, leisure=False),
        ],
    )
    def test_never_with_enforcement_off_in_a_demo_or_dormant(
        self, proc: Path, kill: MagicMock, rules: PlaytimeRules
    ) -> None:
        del proc
        LeisureKiller(None).enforce(_SPENT, rules, verdict=_verdict(None), stamp=0.0)
        kill.assert_not_called()

    def test_a_bug_never_escapes_into_the_loop(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        killer = LeisureKiller(None)
        with patch.object(_leisure_kill, "sweep_targets", side_effect=RecursionError):
            for stamp in range(0, 34, 3):  # sweeps (and fails) at 30 and 33
                killer.enforce(_SPENT, _RULES, verdict=_verdict(None), stamp=stamp)
        assert sum("Leisure kill failed" in r.message for r in caplog.records) == 1

    def test_a_failed_sigkill_is_retried_and_logged_once_delivered(
        self, proc: Path, kill: MagicMock
    ) -> None:
        del proc
        kill.side_effect = [None, ProcessLookupError, None, None]
        log = StubLog()
        killer = LeisureKiller(log)
        verdict = _verdict(_now(Reason("media", "app:mpv", 10, "mpv")))
        for stamp in (0.0, 30.0, 33.0, 36.0):
            killer.enforce(_SPENT, _RULES, verdict=verdict, stamp=stamp)
        assert [f["signal"] for _e, f in log.records] == ["SIGTERM", "SIGKILL"]
        assert kill.call_count == 4
