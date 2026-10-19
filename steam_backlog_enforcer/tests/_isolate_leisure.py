"""Autouse isolation of the Phase-2 leisure switch and the leisure kill scan.

The switch file ``/etc/leisure-watch/leisure_from`` is read per tick by
``earned_time`` itself (``is_leisure``, looked up at call time from
``earned_time._leisure``), by the enforcer's billing gate and by its budget
pricing, which pass their own constants explicitly. All point at an absent
file under ``tmp_path``, so no
test ever reads the real one and every test starts dormant. A test turns
Phase 2 on by writing a date to :func:`switch_file`.

The leisure kill scan reads ``/proc`` through its own constant; it gets an
empty directory (:func:`leisure_proc`), so no test can see -- or signal -- a
live browser or player.

Module-level code runs at collection, before any fixture: it wraps itself in
:func:`collection_isolated` instead.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

_SWITCH_NAME = "leisure_from"
_PROC_NAME = "leisure_proc"
# Every switch reader, by the module attribute it looks up at call time.
_SWITCH_READERS = (
    "earned_time._leisure.LEISURE_FROM_PATH",
    "steam_backlog_enforcer._leisure_mode.LEISURE_FROM_PATH",
    "steam_backlog_enforcer._budget_resolve.LEISURE_FROM_PATH",
)
# Can never exist (/dev/null is not a directory): always the parked date.
_NO_SWITCH = Path(os.devnull) / _SWITCH_NAME


@contextmanager
def collection_isolated() -> Iterator[None]:
    """Point every switch reader at a file that cannot exist (no ``tmp_path``)."""
    with ExitStack() as stack:
        for target in _SWITCH_READERS:
            stack.enter_context(patch(target, _NO_SWITCH))
        yield


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
    with ExitStack() as stack:
        for target in _SWITCH_READERS:
            stack.enter_context(patch(target, switch))
        stack.enter_context(patch("steam_backlog_enforcer._leisure_procs._PROC", proc))
        yield
