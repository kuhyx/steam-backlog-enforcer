"""Daily gaming-time budget: accounting, day rollover and cutoff policy.

Tracks how long the user has spent gaming during the current *gaming day* and,
once the budget is exhausted, drives the cutoff sequence implemented in
:mod:`steam_backlog_enforcer._playtime_block`.

Three design points that are load-bearing:

**The gaming day starts at 06:00 local, not midnight.** A session that runs
past midnight belongs to the day it started in; a midnight boundary would hand
out a fresh 8-hour budget in the middle of a late session. Rollover is checked
lazily on every tick against a stored day key rather than scheduled, so it
survives suspend, reboot and daemon restarts with no timer of its own.

**Elapsed time is measured from wall-clock deltas, clamped.** Counting "one
tick = one interval" silently under-counts whenever the loop is slow and
over-counts nothing; measuring the raw delta over-counts wildly across a
suspend. Clamping each delta to a small multiple of the tick interval makes
suspends, missed ticks, daemon restarts and NTP steps all behave.

**Launchers are matched by cmdline, not by ``comm``.** ``/usr/bin/lutris`` is a
``#!/usr/bin/env python3`` script, so the kernel records its ``comm`` as
``python3`` and the ``comm``-based scan in :mod:`enforcer` never sees it. That
is why :func:`get_pids_by_cmdline_names` exists alongside
``enforcer.get_pids_by_process_names`` rather than replacing it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import logging
import time
from typing import TYPE_CHECKING

from steam_backlog_enforcer._playtime_block import (
    mounted_targets,
    reconcile,
)
from steam_backlog_enforcer._playtime_budget import (
    accumulate,
    roll_over,
)
from steam_backlog_enforcer._playtime_cutoff import (
    _begin_cutoff,
    _sustain_block,
    _warn,
)
from steam_backlog_enforcer._playtime_procs import attributed_key, qualifying_pids
from steam_backlog_enforcer._playtime_state import (
    PlaytimeRules,
    PlaytimeState,
    gaming_day_key,
    load_state,
    rules_for,
    save_state,
)
from steam_backlog_enforcer._total_block import is_total_block_active

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_session import PlaytimeSession
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)


_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60


def playtime_tick(
    config: Config,
    *,
    interval: float,
    session: PlaytimeSession,
    demo: bool = False,
) -> None:
    """Account for this tick's gaming time and enforce the daily budget.

    Called first in every enforce-loop iteration, before any other guard, so
    that time is still counted (and a 06:00 release still happens) in the
    situations where the rest of the loop early-returns.

    Time only accrues while the user is actually engaged: a resident game
    process behind a locked screen, an unfocused window or five minutes of
    silence is not play. See :mod:`_playtime_engagement`.

    Args:
        config: Loaded user configuration.
        interval: Nominal seconds between enforce-loop ticks.
        session: Cross-tick engagement and logging state.
        demo: Whether this is a short-budget demo run.
    """
    now = datetime.now(UTC).astimezone()
    rules = rules_for(config, demo=demo)
    state = roll_over(_state_or_recover(rules, now=now), day_key=gaming_day_key(now))

    if is_total_block_active():
        # The total block runs `pacman -R steam` every tick; our bind mounts
        # would make that fail EBUSY. It is strictly stronger — get out of its
        # way, and stop accruing against a budget nobody can spend.
        reconcile(should_block=False)
        save_state(state, demo=demo)
        session.history.observe(state, demo=demo)
        return

    owners = qualifying_pids(rules)
    pids = set(owners)
    monotonic = time.monotonic()
    verdict = session.tracker.assess(rules, qualifying=pids, now_monotonic=monotonic)

    state = accumulate(
        state,
        now=now,
        qualifying=pids if verdict.engaged else set(),
        interval=interval,
        credited_key=(
            attributed_key(owners, verdict.focus_pid) if verdict.engaged else ""
        ),
    )
    state = session.tracker.backdate(state, verdict, rules=rules)
    state = _policy(state, rules, now=now)
    session.journal.observe(verdict, state, rules=rules, now_monotonic=monotonic)
    save_state(state, demo=demo)
    session.history.observe(state, demo=demo)


def _state_or_recover(rules: PlaytimeRules, *, now: datetime) -> PlaytimeState:
    """Load state, synthesising a fail-closed record if it is unusable.

    If the state file is gone but the binaries are still masked, the only safe
    reading is that the file was deleted to lift the block. Synthesising an
    exhausted budget keeps it in force; the normal 06:00 rollover then lifts it
    with no special case.

    Args:
        rules: Policy for this tick.
        now: Timezone-aware local timestamp.

    Returns:
        Loaded or synthesised state.
    """
    loaded = load_state(demo=rules.demo)
    if loaded is not None:
        return loaded

    stamp = now.timestamp()
    fresh = PlaytimeState(day_key=gaming_day_key(now), last_tick_at=stamp)
    if not mounted_targets():
        return fresh

    logger.warning("Playtime state missing while blocked; failing closed.")
    return replace(fresh, seconds=rules.budget_seconds, blocked_at=stamp)


def _release_after_raise(
    state: PlaytimeState,
    rules: PlaytimeRules,
) -> PlaytimeState:
    """Clear block bookkeeping after the day's budget rose past what was spent.

    Only ``roll_over`` at the 06:00 boundary ever reset ``blocked_at`` before
    the workout coupling existed, because the budget could not move within a
    day. It can now: logging a workout raises it from the unearned floor to the
    earned budget, and the mounts come down on the very next tick. Two things
    have to come down with them.

    ``blocked_at`` — otherwise ``is_blocked()`` stays true and ``build_today``
    keeps reporting ``"blocked": true``, so the UI would claim you were blocked
    while gaming worked fine. That is the exact "state disagrees with reality"
    failure the mount-visibility check exists to catch.

    ``warned_seconds`` — the thresholds are keyed on seconds *remaining*, so a
    raise makes remaining climb back through values already recorded as fired.
    Left alone, the extra two hours would arrive with no warnings at all.

    Args:
        state: Accounting state for the current gaming day.
        rules: Policy for this tick, holding the newly raised budget.

    Returns:
        The state with block bookkeeping cleared.
    """
    logger.warning(
        "Gaming budget rose to %.1fh past the %.0fs already spent — releasing "
        "the block and re-arming warnings for the remaining time.",
        rules.budget_seconds / 3600,
        state.seconds,
    )
    return replace(state, blocked_at=0.0, warned_seconds=[])


def _policy(
    state: PlaytimeState,
    rules: PlaytimeRules,
    *,
    now: datetime,
) -> PlaytimeState:
    """Apply warnings, the cutoff, and block upkeep to *state*.

    Args:
        state: Accounting state after this tick's accumulation.
        rules: Policy for this tick.
        now: Timezone-aware local timestamp.

    Returns:
        The updated state.
    """
    if not rules.enforcement:
        # A kill switch must still release: leaving live mounts behind would
        # make "disabled" mean "permanently blocked".
        reconcile(should_block=False)
        return state

    if state.seconds < rules.budget_seconds:
        reconcile(should_block=False)
        if state.is_blocked():
            state = _release_after_raise(state, rules)
        return _warn(state, rules)

    if not state.is_blocked():
        return _begin_cutoff(state, rules, now=now)

    return _sustain_block(state, rules, now=now)
