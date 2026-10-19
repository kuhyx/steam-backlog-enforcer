"""An untrusted watcher is swept only after 30 s of continuous untrust."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

from leisure_watch.facts import Focus, Now
import pytest

from steam_backlog_enforcer._leisure_kill import UNTRUSTED_SWEEP_AFTER, LeisureKiller
from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState
from steam_backlog_enforcer._shadow import ShadowVerdict
from steam_backlog_enforcer.tests._isolate_leisure import leisure_proc
from steam_backlog_enforcer.tests._leisure_fake_proc import FakeProc, add_proc

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path
    from unittest.mock import MagicMock

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
_FREE = PlaytimeState(day_key="2026-11-02", seconds=1.0)
_TRUSTED = ShadowVerdict(
    paused_by=None,
    keys=(),
    fact=Now(0.0, 1, "free", None, (), Focus("i3", "", None, idle=False)),
)
_STALE = ShadowVerdict(paused_by=None, keys=("k",), fact=None)
_PAUSED = ShadowVerdict(paused_by="i3lock", keys=(), fact=None)


@pytest.fixture
def kill(tmp_path: Path) -> Iterator[MagicMock]:
    add_proc(leisure_proc(tmp_path), FakeProc(10, exe="/usr/bin/mpv"))
    with patch.object(os, "kill") as mock:
        yield mock


def _ticks(
    killer: LeisureKiller,
    stamps: Iterable[float],
    verdict: ShadowVerdict = _STALE,
    state: PlaytimeState = _SPENT,
) -> None:
    for stamp in stamps:
        killer.enforce(state, _RULES, verdict=verdict, stamp=float(stamp))


def test_the_window_is_30_s() -> None:
    assert UNTRUSTED_SWEEP_AFTER == 30.0


def test_one_stale_moment_kills_nothing(kill: MagicMock) -> None:
    killer = LeisureKiller(None)
    _ticks(killer, range(0, 28, 3))
    kill.assert_not_called()
    _ticks(killer, [30])
    assert [c.args[0] for c in kill.call_args_list] == [10]


def test_a_trusted_tick_restarts_the_window(kill: MagicMock) -> None:
    killer = LeisureKiller(None)
    _ticks(killer, range(0, 25, 3))
    _ticks(killer, [27], _TRUSTED)
    _ticks(killer, range(30, 58, 3))
    kill.assert_not_called()
    _ticks(killer, [60])
    kill.assert_called_once()


def test_a_pause_restarts_the_window(kill: MagicMock) -> None:
    killer = LeisureKiller(None)
    _ticks(killer, range(0, 25, 3))
    _ticks(killer, [27], _PAUSED)
    _ticks(killer, range(30, 55, 3))
    kill.assert_not_called()


def test_resume_from_sleep_restarts_the_window(kill: MagicMock) -> None:
    killer = LeisureKiller(None)
    _ticks(killer, range(0, 28, 3))
    _ticks(killer, range(3600, 3628, 3))
    kill.assert_not_called()
    _ticks(killer, [3630])
    kill.assert_called_once()


def test_untrust_counts_while_the_budget_lasts(kill: MagicMock) -> None:
    killer = LeisureKiller(None)
    _ticks(killer, range(0, 31, 3), state=_FREE)
    _ticks(killer, [33])
    kill.assert_called_once()


def test_a_clock_step_back_restarts_the_window(kill: MagicMock) -> None:
    killer = LeisureKiller(None)
    _ticks(killer, range(100, 128, 3))
    _ticks(killer, range(0, 28, 3))
    kill.assert_not_called()
