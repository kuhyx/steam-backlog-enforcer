"""Phase 2 at 0: end every leisure app the watcher names (Steam is separate).

Runs every 3 s tick while the leisure budget is spent, beside the unchanged
Steam cutoff (:mod:`_playtime_cutoff`). Which pids:

* **Trusted** ``now.json``: every ``focus``/``media`` reason's pid unless it is
  a browser (the extension redirects those to the "leisure spent" page), and
  every ``failclosed`` reason's pid -- a browser that is not reporting (another
  browser, an unreported private window) has nothing redirecting it.
  ``game`` reasons belong to the Steam path.
* **Untrusted** (stale, missing, badly signed, unreadable): every browser,
  media player and wsg-grabber reviewer (:func:`_leisure_procs.sweep_targets`)
  until the watcher is fresh again.
* **Paused** (a locker grab is held): nothing; the lock is not a stale watcher.

Each process gets SIGTERM once, then SIGKILL every tick from 30 s after *its*
SIGTERM -- timed per process, so an app opened an hour into the block still
gets its 30 s. A process is its (pid, start time), so a reused pid starts
over. Root/system processes, lockers and the enforcer itself are never
signalled. Every SIGTERM and the first SIGKILL go to ``budget.jsonl``.
"""

from __future__ import annotations

import logging
import os
import signal
from typing import TYPE_CHECKING, Final, Protocol

from steam_backlog_enforcer._leisure_procs import (
    exe_name,
    is_browser,
    is_protected,
    own_chain,
    start_time,
    sweep_targets,
)

if TYPE_CHECKING:
    from leisure_watch.facts import Now

    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState
    from steam_backlog_enforcer._shadow import ShadowVerdict

logger = logging.getLogger(__name__)

EVENT_LEISURE_KILL: Final = "leisure_kill"
SIGKILL_AFTER_SECONDS: Final = 30.0
_KILLED_SOURCES: Final = frozenset({"focus", "media"})
_FAILCLOSED: Final = "failclosed"

_Ident = tuple[int, int]


class KillLog(Protocol):
    """Where kills are recorded (``BudgetLog``)."""

    def record(self, event: str, **fields: object) -> None:
        """Append one record."""


def fact_targets(fact: Now) -> dict[int, str]:
    """Pids a trusted *fact* says must end, to the reason key that named them."""
    found: dict[int, str] = {}
    for reason in fact.reasons:
        if reason.pid is None:
            continue
        failclosed = reason.source == _FAILCLOSED
        if failclosed or (
            reason.source in _KILLED_SOURCES and not is_browser(reason.pid)
        ):
            found.setdefault(reason.pid, reason.key)
    return found


class LeisureKiller:
    """The per-daemon kill state: when each process got its SIGTERM."""

    def __init__(self, log: KillLog | None = None) -> None:
        """Start with nothing signalled.

        Args:
            log: The budget audit log; ``None`` records nowhere.
        """
        self.log = log
        self._termed: dict[_Ident, float] = {}
        self._killed: set[_Ident] = set()
        self._last_error = ""

    def enforce(
        self,
        state: PlaytimeState,
        rules: PlaytimeRules,
        *,
        verdict: ShadowVerdict,
        stamp: float,
    ) -> None:
        """Signal this tick's leisure targets if the leisure budget is spent.

        Never raises: the enforce loop has no per-tick guard.

        Args:
            state: Accounting state after this tick's policy.
            rules: Policy for this tick (``leisure`` set by the billing step).
            verdict: This tick's shadow verdict, carrying the trusted fact.
            stamp: Epoch seconds of this tick.
        """
        try:
            self._enforce(state, rules, verdict=verdict, stamp=stamp)
        except Exception as exc:  # the loop must outlive any kill bug
            message = f"{type(exc).__name__}: {exc}"
            if message != self._last_error:
                self._last_error = message
                logger.warning("Leisure kill failed (%s).", message, exc_info=True)

    def _enforce(
        self,
        state: PlaytimeState,
        rules: PlaytimeRules,
        *,
        verdict: ShadowVerdict,
        stamp: float,
    ) -> None:
        if not rules.leisure or rules.demo or not rules.enforcement:
            return
        if state.seconds < rules.budget_seconds:
            self._termed.clear()
            self._killed.clear()
            return
        if verdict.paused_by is not None:
            return
        if verdict.fact is None:
            targets, why = sweep_targets(), "now.json untrusted"
        else:
            targets, why = fact_targets(verdict.fact), "now.json"
        live = self._identify(targets)
        self._termed = {i: t for i, t in self._termed.items() if i in live}
        self._killed &= set(live)
        base = {
            "why": why,
            "day_key": state.day_key,
            "seconds": round(state.seconds, 3),
        }
        for ident, key in sorted(live.items()):
            note = {"key": key, "name": exe_name(ident[0]), **base}
            first = self._termed.get(ident)
            if first is None:
                self._termed[ident] = stamp
                self._signal(ident[0], signal.SIGTERM, note)
            elif stamp - first >= SIGKILL_AFTER_SECONDS:
                quiet = ident in self._killed
                if self._signal(ident[0], signal.SIGKILL, None if quiet else note):
                    self._killed.add(ident)

    @staticmethod
    def _identify(targets: dict[int, str]) -> dict[_Ident, str]:
        chain = own_chain()
        live: dict[_Ident, str] = {}
        for pid, key in targets.items():
            started = start_time(pid)
            if started is not None and not is_protected(pid, chain):
                live[pid, started] = key
        return live

    def _signal(
        self, pid: int, sig: signal.Signals, note: dict[str, object] | None
    ) -> bool:
        """Send *sig*; record it unless *note* is ``None``. True if delivered."""
        try:
            os.kill(pid, sig)
        except ProcessLookupError, PermissionError:
            return False
        if note is not None and self.log is not None:
            self.log.record(EVENT_LEISURE_KILL, pid=pid, signal=sig.name, **note)
        return True
