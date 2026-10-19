"""Phase 2 at 0: end every leisure app the watcher names (Steam is separate).

Runs every 3 s tick while the leisure budget is spent, beside the unchanged
Steam cutoff (:mod:`_playtime_cutoff`). Which pids:

* **Trusted** ``now.json``: every ``focus``/``media`` reason's pid unless it is
  a browser (the extension redirects those to the "leisure spent" page), and
  every ``failclosed`` reason's pid -- a browser that is not reporting (another
  browser, an unreported private window) has nothing redirecting it.
  ``game`` reasons belong to the Steam path.
* **Untrusted** (stale, missing, badly signed, unreadable) for 30 s in a row:
  every browser, media player and wsg-grabber reviewer
  (:func:`_leisure_procs.sweep_targets`) until the watcher is fresh again. One
  stale moment (resume from sleep, a watcher restart) kills nothing: a trusted
  or paused tick, or a gap between ticks (a suspend), restarts the window.
* **Paused** (a locker grab is held): nothing; the lock is not a stale watcher.

Each process gets SIGTERM once, then SIGKILL every tick from 30 s after *its*
SIGTERM -- timed per process, so an app opened an hour into the block still
gets its 30 s. A process is its (pid, start time), so a reused pid starts
over; a reason carrying the start time it saw (leisure-watch 0.2.1 ``start``)
names only that process, never a later one reusing the pid. Root/system
processes, lockers and the enforcer itself are never signalled, nor --
whatever ``now.json`` says -- the desktop session (:mod:`_leisure_never_kill`;
each refusal logged once). Every SIGTERM and the first SIGKILL go to
``budget.jsonl``.
"""

from __future__ import annotations

import logging
import math
import os
import signal
from typing import TYPE_CHECKING, Final, Protocol

from steam_backlog_enforcer._leisure_never_kill import never_kill
from steam_backlog_enforcer._leisure_procs import (
    exe_name,
    is_browser,
    is_protected,
    own_chain,
    start_time,
    sweep_targets,
)

if TYPE_CHECKING:
    from leisure_watch.facts import Now, Reason

    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState
    from steam_backlog_enforcer._shadow import ShadowVerdict

logger = logging.getLogger(__name__)

EVENT_LEISURE_KILL: Final = "leisure_kill"
EVENT_KILL_REFUSED: Final = "leisure_kill_refused"
SIGKILL_AFTER_SECONDS: Final = 30.0
UNTRUSTED_SWEEP_AFTER: Final = 30.0
# Ticks are 3 s apart; a longer gap (suspend, a stalled loop) is not "in a row".
_MAX_TICK_GAP: Final = 10.0
_KILLED_SOURCES: Final = frozenset({"focus", "media"})
_FAILCLOSED: Final = "failclosed"

_Ident = tuple[int, int]


class KillLog(Protocol):
    """Where kills are recorded (``BudgetLog``)."""

    def record(self, event: str, **fields: object) -> None:
        """Append one record."""


def _picks(fact: Now) -> dict[int, Reason]:
    """Pids a trusted *fact* says must end, to the (first) reason naming them."""
    found: dict[int, Reason] = {}
    for reason in fact.reasons:
        if reason.pid is None:
            continue
        failclosed = reason.source == _FAILCLOSED
        if failclosed or (
            reason.source in _KILLED_SOURCES and not is_browser(reason.pid)
        ):
            found.setdefault(reason.pid, reason)
    return found


def fact_targets(fact: Now) -> dict[int, str]:
    """Pids a trusted *fact* says must end, to the reason key that named them."""
    return {pid: reason.key for pid, reason in _picks(fact).items()}


def _start(reason: Reason) -> int | None:
    # Optional from leisure-watch 0.2.1; absent (0.2.0) or unusable = unknown.
    start = getattr(reason, "start", None)
    usable = isinstance(start, int) and not isinstance(start, bool)
    return start if usable else None


def fact_starts(fact: Now) -> dict[int, int]:
    """Per target pid, the start time its reason saw (when it carries one)."""
    starts = {pid: _start(reason) for pid, reason in _picks(fact).items()}
    return {pid: start for pid, start in starts.items() if start is not None}


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
        self._refused: set[_Ident] = set()
        self._untrusted_since: float | None = None
        self._last_stamp = -math.inf
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
        untrusted_for = self._untrusted_for(verdict, stamp)
        if state.seconds < rules.budget_seconds:
            self._termed.clear()
            self._killed.clear()
            return
        if verdict.paused_by is not None:
            return
        starts: dict[int, int] = {}
        if verdict.fact is None:
            if untrusted_for < UNTRUSTED_SWEEP_AFTER:
                return
            targets, why = sweep_targets(), "now.json untrusted"
        else:
            targets, why = fact_targets(verdict.fact), "now.json"
            starts = fact_starts(verdict.fact)
        live = self._identify(targets, starts)
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

    def _untrusted_for(self, verdict: ShadowVerdict, stamp: float) -> float:
        """Seconds ``now.json`` has been untrusted in a row, as of this tick."""
        gap = stamp - self._last_stamp
        self._last_stamp = stamp
        if verdict.fact is not None or verdict.paused_by is not None:
            self._untrusted_since = None
            return 0.0
        if self._untrusted_since is None or not 0.0 <= gap <= _MAX_TICK_GAP:
            self._untrusted_since = stamp
        return stamp - self._untrusted_since

    def _identify(
        self, targets: dict[int, str], starts: dict[int, int]
    ) -> dict[_Ident, str]:
        chain = own_chain()
        live: dict[_Ident, str] = {}
        refused: set[_Ident] = set()
        for pid, key in targets.items():
            started = start_time(pid)
            if started is None or starts.get(pid, started) != started:
                continue  # gone, or the pid now belongs to another process
            if is_protected(pid, chain):
                continue
            guard = never_kill(pid)
            if guard is None:
                live[pid, started] = key
                continue
            refused.add((pid, started))
            if (pid, started) not in self._refused:
                self._refuse(pid, key, guard)
        self._refused = refused
        return live

    def _refuse(self, pid: int, key: str, name: str) -> None:
        """Log, once per process, a kill the never-kill set stopped."""
        logger.warning(
            "Refused leisure kill of pid %d (%s): %s is never killed.", pid, key, name
        )
        if self.log is not None:
            self.log.record(EVENT_KILL_REFUSED, pid=pid, key=key, name=name)

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
