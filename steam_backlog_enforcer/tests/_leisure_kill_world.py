"""Shared world for the leisure-kill tests: a fake /proc, facts and a log stub."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from leisure_watch.facts import Focus, Now, Reason

from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState
from steam_backlog_enforcer._shadow import ShadowVerdict
from steam_backlog_enforcer.tests._isolate_leisure import leisure_proc
from steam_backlog_enforcer.tests._leisure_fake_proc import FakeProc, add_proc

if TYPE_CHECKING:
    from pathlib import Path

HELIUM = "/opt/helium-browser-bin/helium"
# Enforced budget rules with 100 s allowed; RULES also bills the leisure budget.
BASE_RULES = PlaytimeRules(
    budget_seconds=100.0,
    warn_at=(),
    sigkill_after=30.0,
    count_launchers=False,
    enforcement=True,
    demo=False,
)
RULES = replace(BASE_RULES, leisure=True)
SPENT = PlaytimeState(day_key="2026-11-02", seconds=100.0)


class StubLog:
    """Audit log double that keeps every recorded event in order."""

    def __init__(self) -> None:
        """Start with no records."""
        self.records: list[tuple[str, dict[str, object]]] = []

    def record(self, event: str, **fields: object) -> None:
        """Remember one event and its fields."""
        self.records.append((event, fields))


def now_with(*reasons: Reason) -> Now:
    """Build a leisure ``now.json`` fact carrying ``reasons``."""
    return Now(
        ts=0.0,
        seq=1,
        state="leisure",
        paused_by=None,
        reasons=reasons,
        focus=Focus("Helium", "", None, idle=False),
    )


def verdict_of(fact: Now | None, paused: str | None = None) -> ShadowVerdict:
    """Wrap a fact (or its absence) in a shadow verdict."""
    return ShadowVerdict(paused_by=paused, keys=("k",), fact=fact)


def build_proc(tmp_path: Path) -> Path:
    """Fill the isolated /proc with mpv, two browsers and a root-owned app."""
    root = leisure_proc(tmp_path)
    add_proc(root, FakeProc(10, exe="/usr/bin/mpv"))
    add_proc(root, FakeProc(20, exe=HELIUM, comm="helium"))
    add_proc(root, FakeProc(30, exe="/usr/bin/chromium", comm="chromium"))
    add_proc(root, FakeProc(40, exe="/usr/bin/vesktop", uid=0))
    return root
