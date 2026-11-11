"""PID reuse: a reason carrying its process start time kills only that process.

leisure-watch 0.2.1 adds an optional ``start`` (``/proc/<pid>/stat`` field 22)
to each reason; :class:`_R` stands in for it, so this runs on 0.2.0 too.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

from leisure_watch.facts import Focus, Now, Reason
import pytest

from steam_backlog_enforcer._leisure_kill import LeisureKiller, fact_starts
from steam_backlog_enforcer._shadow import ShadowVerdict
from steam_backlog_enforcer.tests._isolate_leisure import leisure_proc
from steam_backlog_enforcer.tests._leisure_fake_proc import FakeProc, add_proc
from steam_backlog_enforcer.tests._leisure_kill_world import RULES, SPENT

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class _R(Reason):
    start: int | None = None


def _killed(tmp_path: Path, *reasons: Reason) -> list[int]:
    root = leisure_proc(tmp_path)
    add_proc(root, FakeProc(10, exe="/usr/bin/mpv", start=500))
    fact = Now(0.0, 1, "leisure", None, reasons, Focus("mpv", "", None, idle=False))
    verdict = ShadowVerdict(paused_by=None, keys=("k",), fact=fact)
    with patch.object(os, "kill") as kill:
        LeisureKiller(None).enforce(SPENT, RULES, verdict=verdict, stamp=0.0)
    return [c.args[0] for c in kill.call_args_list]


def test_a_matching_start_is_killed(tmp_path: Path) -> None:
    """A pid whose start time matches the reason is killed."""
    assert _killed(tmp_path, _R("media", "app:mpv", 10, "mpv", start=500)) == [10]


def test_a_reused_pid_is_spared(tmp_path: Path) -> None:
    """A pid whose start time differs (reused pid) is spared."""
    assert _killed(tmp_path, _R("media", "app:mpv", 10, "mpv", start=499)) == []


@pytest.mark.parametrize(
    "reason",
    [
        Reason("media", "app:mpv", 10, "mpv"),
        _R("media", "app:mpv", 10, "mpv", start=None),
        _R("media", "app:mpv", 10, "mpv", start=True),
    ],
)
def test_no_usable_start_keeps_the_old_behaviour(
    tmp_path: Path, reason: Reason
) -> None:
    """Without a usable start time the pid is killed as before."""
    assert _killed(tmp_path, reason) == [10]


def test_starts_come_from_the_reason_that_named_the_pid() -> None:
    """A pid takes its start time from the reason that named it, not others."""
    fact = Now(
        0.0,
        1,
        "leisure",
        None,
        (
            _R("game", "steam:1", 10, "x", start=1),
            _R("media", "app:mpv", 10, "mpv", start=500),
            _R("focus", "app:mpv", 10, "mpv", start=7),
            _R("media", "app:vlc", None, "vlc", start=9),
        ),
        Focus("mpv", "", None, idle=False),
    )
    assert fact_starts(fact) == {10: 500}
