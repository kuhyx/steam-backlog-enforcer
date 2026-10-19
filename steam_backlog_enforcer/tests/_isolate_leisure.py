"""Autouse isolation of the Phase-2 leisure switch and the leisure kill scan.

The switch file ``/etc/leisure-watch/leisure_from`` is read twice per tick:
by ``earned_time`` itself (``is_leisure``, looked up at call time from
``earned_time._leisure``) and by the enforcer's gate, which passes its own
constant explicitly. Both point at an absent file under ``tmp_path``, so no
test ever reads the real one and every test starts dormant. A test turns
Phase 2 on by writing a date to :func:`switch_file`.

The leisure kill scan reads ``/proc`` through its own constant; it gets an
empty directory (:func:`leisure_proc`), so no test can see -- or signal -- a
live browser or player.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SWITCH_NAME = "leisure_from"
_PROC_NAME = "leisure_proc"


def switch_file(tmp_path: Path) -> Path:
    """The redirected switch file for this test (absent until written)."""
    return tmp_path / "etc-leisure-watch" / _SWITCH_NAME


def leisure_proc(tmp_path: Path) -> Path:
    """The redirected ``/proc`` the leisure kill scan reads for this test."""
    return tmp_path / _PROC_NAME


@pytest.fixture(autouse=True)
def _isolate_leisure(tmp_path: Path) -> Iterator[None]:
    """Point both switch readers and the kill scan at ``tmp_path``."""
    switch = switch_file(tmp_path)
    switch.parent.mkdir(exist_ok=True)
    proc = leisure_proc(tmp_path)
    proc.mkdir(exist_ok=True)
    with (
        patch("earned_time._leisure.LEISURE_FROM_PATH", switch),
        patch("steam_backlog_enforcer._leisure_mode.LEISURE_FROM_PATH", switch),
        patch("steam_backlog_enforcer._leisure_procs._PROC", proc),
    ):
        yield
