"""Shadow leisure billing (contract C4): measured every tick, never enforced.

Phase 1 of the leisure rollout counts every non-productive minute on the PC
beside the enforced gaming count, so a week of real data exists before the
leisure budget is switched on. Nothing here feeds a warning, a cutoff or a
kill, and nothing here writes an enforced field (``seconds``, ``per_game``,
``last_tick_at``, ...): the shadow is computed from the incoming tick stamp
*before* :func:`~steam_backlog_enforcer._playtime_budget.accumulate` moves it.

Per tick, in order:

1. A locker whose X grab is actually held, or i3lock -> paused: the delta
   goes to ``shadow_paused_seconds`` and nothing bills, games included (Q7).
2. Any qualifying game process (the enforcer's own scan) -> leisure, billed
   to the game keys.
3. Else the watcher's signed ``now.json``: ``leisure`` bills its reason keys;
   a missing, stale or badly signed file fails closed (Q8) and bills
   ``failclosed:watcher``.

Overlapping sources bill the wall clock once and split it evenly, so
``sum(shadow_per_source) == shadow_seconds`` up to float rounding.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final

from leisure_watch.facts import read_now
from leisure_watch.lockstate import paused_by

from steam_backlog_enforcer._playtime_state import _DELTA_CLAMP_FACTOR

if TYPE_CHECKING:
    from leisure_watch.facts import Now

    from steam_backlog_enforcer._playtime_state import PlaytimeState

# Explicit, because the daemon is root: these are the desktop user's (uid 1000).
NOW_PATH: Final = Path("/run/user/1000/leisure-watch/now.json")
CLAIMS_DIR: Final = Path("/run/user/1000/gatelock/claims")
# now.json older than this is not trusted (contract C3/Q8).
_MAX_AGE_SECONDS: Final = 15
FAILCLOSED_KEY: Final = "failclosed:watcher"


@dataclass(frozen=True)
class ShadowVerdict:
    """What one tick means for the shadow budget."""

    paused_by: str | None
    """``gatelock:<app>`` / ``i3lock`` while paused, else ``None``."""
    keys: tuple[str, ...]
    """Sources billed this tick; empty = free (or paused)."""

    @property
    def state(self) -> str:
        """``paused``, ``leisure`` or ``free``."""
        if self.paused_by is not None:
            return "paused"
        return "leisure" if self.keys else "free"


def shadow_keys(owners: dict[int, str], fact: Now | None) -> tuple[str, ...]:
    """Return the sources this unpaused tick bills, or ``()`` when it is free.

    Args:
        owners: Qualifying game PIDs to attribution keys (``app:<id>`` ...).
        fact: The verified watcher fact, or ``None`` if it cannot be trusted.

    Returns:
        Game keys (sorted) if a game runs; else the watcher's reason keys in
        its order; ``(FAILCLOSED_KEY,)`` when the watcher cannot be trusted.
    """
    if owners:
        return tuple(sorted(set(owners.values())))
    if fact is None:
        return (FAILCLOSED_KEY,)
    if fact.state != "leisure":
        return ()
    return tuple(dict.fromkeys(r.key for r in fact.reasons)) or (FAILCLOSED_KEY,)


def observe_shadow(owners: dict[int, str], *, stamp: float) -> ShadowVerdict:
    """Read the lock state and (unless paused) ``now.json`` once for this tick.

    Args:
        owners: This tick's qualifying game PIDs and their keys.
        stamp: Epoch seconds of this tick, the freshness reference.

    Returns:
        The tick's shadow verdict.
    """
    paused = paused_by(CLAIMS_DIR)
    if paused is not None:
        return ShadowVerdict(paused_by=paused, keys=())
    fact = read_now(NOW_PATH, stamp, max_age=_MAX_AGE_SECONDS)
    return ShadowVerdict(paused_by=None, keys=shadow_keys(owners, fact))


def shadow_accumulate(
    state: PlaytimeState,
    *,
    stamp: float,
    interval: float,
    verdict: ShadowVerdict,
) -> PlaytimeState:
    """Add this tick's shadow time to *state*; pure, enforced fields untouched.

    Measured from the same incoming ``last_tick_at`` and clamped by the same
    factor as the enforced ``accumulate``, so a first tick, a backward clock
    step or a suspend behave identically in both counts.

    Args:
        state: Accounting state *before* this tick's enforced accumulation.
        stamp: Epoch seconds of this tick.
        interval: Nominal seconds between ticks.
        verdict: This tick's shadow verdict.

    Returns:
        The updated state.
    """
    delta = stamp - state.last_tick_at
    if state.last_tick_at <= 0.0 or delta <= 0.0:
        return state
    credited = min(delta, interval * _DELTA_CLAMP_FACTOR)
    if verdict.paused_by is not None:
        paused = state.shadow_paused_seconds + credited
        return replace(state, shadow_paused_seconds=paused)
    if not verdict.keys:
        return state
    share = credited / len(verdict.keys)
    per_source = dict(state.shadow_per_source)
    for key in verdict.keys:
        per_source[key] = per_source.get(key, 0.0) + share
    return replace(
        state,
        shadow_seconds=state.shadow_seconds + credited,
        shadow_per_source=per_source,
    )
