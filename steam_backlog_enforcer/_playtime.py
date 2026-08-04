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

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from steam_backlog_enforcer._playtime_block import (
    kill_gaming_processes,
    mounted_targets,
    reconcile,
    request_steam_shutdown,
    steam_and_launcher_pids,
)
from steam_backlog_enforcer._total_block import (
    LAUNCHER_PROCESS_NAMES,
    is_total_block_active,
)
from steam_backlog_enforcer._whitelist import _try_set_immutable, unlock_for_write
from steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write
from steam_backlog_enforcer.enforcer import (
    get_pids_by_process_names,
    get_running_steam_game_pids,
)
from steam_backlog_enforcer.library_hider import _resolve_desktop_user, _run_as_user

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

PLAYTIME_STATE_FILE = CONFIG_DIR / "playtime_state.json"
PLAYTIME_DEMO_STATE_FILE = CONFIG_DIR / "playtime_demo_state.json"

_PROC = Path("/proc")

_SCHEMA_VERSION = 1

# The gaming day starts here, local time. 05:59 belongs to the previous day.
_DAY_BOUNDARY_HOURS = 6

# Each tick's measured delta is capped at this many tick intervals. Two is the
# smallest value that tolerates one skipped tick without inflating the count.
_DELTA_CLAMP_FACTOR = 2.0

_DEFAULT_BUDGET_SECONDS = 8 * 3600.0
_DEMO_BUDGET_SECONDS = 60.0

# Seconds remaining at which to warn, descending.
_WARN_AT: tuple[int, ...] = (3600, 1800, 600, 300)
_DEMO_WARN_AT: tuple[int, ...] = (30, 10)

# Grace between "budget exhausted" and masking the Steam binaries. Masking
# makes `steam -shutdown` a no-op, so Steam must be given a moment to close
# its games cleanly first — otherwise every single cutoff is a hard SIGTERM.
_SHUTDOWN_GRACE_SECONDS = 3.0
_SIGKILL_AFTER_SECONDS = 30.0
_DEMO_SIGKILL_AFTER_SECONDS = 10.0

# argv[0] basenames that tell us nothing: the real program is argv[1].
_INTERPRETERS = frozenset({"bash", "env", "java", "perl", "python", "python3", "sh"})

# An interpreter invocation needs at least `<interp> <script>` to name a program.
_MIN_ARGV_FOR_INTERPRETER = 2

_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60


@dataclass
class PlaytimeState:
    """Per-gaming-day playtime accounting, persisted between ticks."""

    schema_version: int = _SCHEMA_VERSION
    day_key: str = ""
    """Gaming day this record covers, ``YYYY-MM-DD``, 06:00-shifted."""
    seconds: float = 0.0
    """Qualifying seconds accrued during ``day_key``."""
    last_tick_at: float = 0.0
    """Epoch seconds of the last accounting tick; ``0.0`` means never ticked."""
    blocked_at: float = 0.0
    """Epoch seconds when the cutoff engaged; ``0.0`` means not blocked."""
    warned_seconds: list[int] = field(default_factory=list)
    """Warning thresholds already fired during ``day_key``."""

    def is_blocked(self) -> bool:
        """Whether the cutoff has engaged for this gaming day.

        Deliberately a method rather than a field: ``save`` serialises
        ``self.__dict__``, so a derived field would be persisted and could
        drift out of step with ``blocked_at``.
        """
        return self.blocked_at > 0.0


@dataclass(frozen=True)
class PlaytimeRules:
    """Resolved budget policy for one tick.

    Frozen and passed explicitly so that every decision function stays pure
    and testable without touching ``Config`` or the clock.
    """

    budget_seconds: float
    warn_at: tuple[int, ...]
    sigkill_after: float
    count_launchers: bool
    enforcement: bool
    demo: bool


def rules_for(config: Config, *, demo: bool) -> PlaytimeRules:
    """Build the policy for this tick from *config*.

    Demo mode changes the budget and the warning thresholds and nothing else —
    in particular it uses the same qualifying-process predicate as production,
    because a demo that exercises different logic proves nothing about it.

    Args:
        config: Loaded user configuration.
        demo: Whether this is a short-budget demo run.

    Returns:
        The rules governing this tick.
    """
    return PlaytimeRules(
        budget_seconds=_DEMO_BUDGET_SECONDS
        if demo
        else float(config.daily_gaming_seconds),
        warn_at=_DEMO_WARN_AT if demo else _WARN_AT,
        sigkill_after=(_DEMO_SIGKILL_AFTER_SECONDS if demo else _SIGKILL_AFTER_SECONDS),
        count_launchers=config.count_launcher_processes,
        enforcement=config.playtime_enforcement,
        demo=demo,
    )


def gaming_day_key(now: datetime) -> str:
    """Return the ``YYYY-MM-DD`` gaming day containing *now*.

    The boundary is 06:00 local, so 02:00 on the 5th belongs to the 4th.

    Args:
        now: Timezone-aware local timestamp.

    Returns:
        The gaming day key.
    """
    return (now - timedelta(hours=_DAY_BOUNDARY_HOURS)).date().isoformat()


def state_path(*, demo: bool) -> Path:
    """Return the state file for a demo or production run.

    Demo runs use a separate file so a demo can never consume or clobber the
    real day's counter.

    Args:
        demo: Whether this is a demo run.

    Returns:
        Path to the state file.
    """
    return PLAYTIME_DEMO_STATE_FILE if demo else PLAYTIME_STATE_FILE


def load_state(*, demo: bool) -> PlaytimeState | None:
    """Load persisted state, or ``None`` if it is absent or unusable.

    ``None`` deliberately covers "missing", "corrupt" and "written by a
    different schema" alike: the caller's recovery path is the same for all
    three, and treating an unreadable file as a fresh day is exactly the
    reset-by-deletion the immutable flag exists to prevent.

    Args:
        demo: Whether this is a demo run.

    Returns:
        The stored state, or ``None`` if it could not be read.
    """
    path = state_path(demo=demo)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Playtime state at %s is unreadable; assuming tampered.", path)
        return None
    if not isinstance(data, dict) or data.get("schema_version") != _SCHEMA_VERSION:
        logger.warning("Playtime state at %s has an unknown schema.", path)
        return None
    fields = PlaytimeState.__dataclass_fields__
    return PlaytimeState(**{k: v for k, v in data.items() if k in fields})


def save_state(state: PlaytimeState, *, demo: bool) -> None:
    """Persist *state*, re-applying the immutable flag for production runs.

    ``_atomic_write`` finishes with ``rename(2)``, which fails ``EPERM`` against
    an immutable destination — so clearing the flag first is mandatory, not
    decorative. Demo state is left mutable: it carries no enforcement weight and
    an immutable copy could not be deleted during cleanup, even by root.

    Args:
        state: State to write.
        demo: Whether this is a demo run.
    """
    path = state_path(demo=demo)
    if not demo:
        unlock_for_write(path)
    _atomic_write(path, json.dumps(state.__dict__, indent=2) + "\n")
    if not demo:
        _try_set_immutable(path, immutable=True)


def get_pids_by_cmdline_names(names: frozenset[str]) -> dict[int, str]:
    """Scan ``/proc/*/cmdline`` for processes whose program name is in *names*.

    Complements ``enforcer.get_pids_by_process_names``, which matches on
    ``comm`` and therefore cannot see interpreter-launched programs: the kernel
    records ``/usr/bin/lutris`` as ``python3``. When ``argv[0]``'s basename is a
    known interpreter this falls through to ``argv[1]``.

    The daemon itself runs under ``python3``, so its own PID is skipped.

    Args:
        names: Program basenames to match.

    Returns:
        Mapping of PID to the matched name.
    """
    own_pid = os.getpid()
    found: dict[int, str] = {}

    for entry in _PROC.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == own_pid:
            continue
        matched = _match_cmdline(entry, names)
        if matched is not None:
            found[pid] = matched

    return found


def _match_cmdline(entry: Path, names: frozenset[str]) -> str | None:
    """Return the name in *names* that *entry*'s cmdline runs, if any.

    Args:
        entry: A ``/proc/<pid>`` directory.
        names: Program basenames to match.

    Returns:
        The matched name, or ``None``.
    """
    try:
        raw = (entry / "cmdline").read_bytes()
    except (OSError, ValueError):
        return None

    argv = [
        part for part in raw.decode("utf-8", errors="replace").split("\x00") if part
    ]
    if not argv:
        return None

    first = Path(argv[0]).name
    if first in names:
        return first
    if first not in _INTERPRETERS or len(argv) < _MIN_ARGV_FOR_INTERPRETER:
        return None
    second = Path(argv[1]).name
    return second if second in names else None


def qualifying_pids(rules: PlaytimeRules) -> set[int]:
    """Return PIDs whose runtime counts against the daily budget.

    Steam games are identified by the ``SteamAppId`` environment variable, using
    the same ``!= 0`` predicate ``enforcer.enforce_allowed_game`` uses to exclude
    the Steam client tree — browsing the store is not gaming.

    Args:
        rules: Policy for this tick.

    Returns:
        The set of qualifying PIDs.
    """
    pids = {pid for pid, app_id in get_running_steam_game_pids().items() if app_id != 0}
    if rules.count_launchers:
        pids |= set(get_pids_by_process_names(LAUNCHER_PROCESS_NAMES))
        pids |= set(get_pids_by_cmdline_names(LAUNCHER_PROCESS_NAMES))
    return pids


def accumulate(
    state: PlaytimeState,
    *,
    now: datetime,
    qualifying: set[int],
    interval: float,
) -> PlaytimeState:
    """Add this tick's elapsed gaming time to *state*.

    Pure. Every argument is mandatory, including the clock — a defaulted ``now``
    would add a branch that exists only to be covered.

    The delta is clamped to ``_DELTA_CLAMP_FACTOR`` intervals so that a suspend,
    a skipped tick or a forward NTP step cannot inflate the count, and floored
    at zero so a backward step cannot refund time.

    Args:
        state: Current accounting state.
        now: Timezone-aware local timestamp for this tick.
        qualifying: PIDs currently counting against the budget.
        interval: Nominal seconds between ticks.

    Returns:
        The updated state.
    """
    stamp = now.timestamp()
    if state.last_tick_at <= 0.0:
        return replace(state, last_tick_at=stamp)

    delta = stamp - state.last_tick_at
    if delta <= 0.0 or not qualifying:
        return replace(state, last_tick_at=stamp)

    credited = min(delta, interval * _DELTA_CLAMP_FACTOR)
    return replace(state, last_tick_at=stamp, seconds=state.seconds + credited)


def roll_over(state: PlaytimeState, *, day_key: str) -> PlaytimeState:
    """Reset *state* if the gaming day has changed.

    Pure. ``last_tick_at`` carries across the boundary so the first tick of the
    new day measures a sane delta rather than restarting from zero.

    Args:
        state: Current accounting state.
        day_key: The gaming day *now* falls in.

    Returns:
        Either *state* unchanged, or a fresh record for *day_key*.
    """
    if state.day_key == day_key:
        return state
    return PlaytimeState(day_key=day_key, last_tick_at=state.last_tick_at)


def pending_warning(state: PlaytimeState, rules: PlaytimeRules) -> int | None:
    """Return the largest un-fired warning threshold *state* has crossed.

    Pure. Returning only the largest matters when a tick is skipped: crossing
    two thresholds at once should warn once, not twice.

    Args:
        state: Current accounting state.
        rules: Policy for this tick.

    Returns:
        The threshold in seconds-remaining, or ``None`` if none is due.
    """
    remaining = rules.budget_seconds - state.seconds
    for threshold in rules.warn_at:
        if remaining <= threshold and threshold not in state.warned_seconds:
            return threshold
    return None


def notify_desktop_user(title: str, body: str) -> None:
    """Send a desktop notification into the real user's session.

    ``enforcer.send_notification`` runs ``notify-send`` as root with no
    ``DBUS_SESSION_BUS_ADDRESS``, which cannot reach the user's session bus from
    a system service. This routes through the same ``sudo -u <user> env ...``
    mechanism that ``library_hider`` uses to launch Steam.

    Args:
        title: Notification title.
        body: Notification body.
    """
    user = _resolve_desktop_user()
    try:
        _run_as_user(["notify-send", title, body, "--icon=dialog-warning"], user)
    except (OSError, ValueError):
        logger.debug("Could not send desktop notification.")


def playtime_tick(config: Config, *, interval: float, demo: bool = False) -> None:
    """Account for this tick's gaming time and enforce the daily budget.

    Called first in every enforce-loop iteration, before any other guard, so
    that time is still counted (and a 06:00 release still happens) in the
    situations where the rest of the loop early-returns.

    Args:
        config: Loaded user configuration.
        interval: Nominal seconds between enforce-loop ticks.
        demo: Whether this is a short-budget demo run.
    """
    now = datetime.now(timezone.utc).astimezone()
    rules = rules_for(config, demo=demo)
    state = roll_over(_state_or_recover(rules, now=now), day_key=gaming_day_key(now))

    if is_total_block_active():
        # The total block runs `pacman -R steam` every tick; our bind mounts
        # would make that fail EBUSY. It is strictly stronger — get out of its
        # way, and stop accruing against a budget nobody can spend.
        reconcile(should_block=False)
        save_state(state, demo=demo)
        return

    state = accumulate(
        state,
        now=now,
        qualifying=qualifying_pids(rules),
        interval=interval,
    )
    save_state(_policy(state, rules, now=now), demo=demo)


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
        return _warn(state, rules)

    if not state.is_blocked():
        return _begin_cutoff(state, rules, now=now)

    return _sustain_block(state, rules, now=now)


def _warn(state: PlaytimeState, rules: PlaytimeRules) -> PlaytimeState:
    """Fire the due warning, if any, and record that it fired.

    Args:
        state: Current accounting state.
        rules: Policy for this tick.

    Returns:
        The updated state.
    """
    threshold = pending_warning(state, rules)
    if threshold is None:
        return state

    notify_desktop_user(
        "Gaming time running out",
        f"{_humanise(threshold)} of today's gaming budget left.",
    )
    return replace(state, warned_seconds=[*state.warned_seconds, threshold])


def _begin_cutoff(
    state: PlaytimeState,
    rules: PlaytimeRules,
    *,
    now: datetime,
) -> PlaytimeState:
    """Start the cutoff: ask Steam to close cleanly, then SIGTERM the games.

    No mount happens on this tick. Masking the Steam binaries turns
    ``steam -shutdown`` into a no-op, which would cost a clean close — and
    therefore a cloud-save flush — on every single cutoff.

    Args:
        state: Current accounting state.
        rules: Policy for this tick.
        now: Timezone-aware local timestamp.

    Returns:
        The updated state.
    """
    logger.warning("Daily gaming budget exhausted; shutting Steam down.")
    notify_desktop_user(
        "Gaming time is up",
        "Daily budget used up. Steam and games are shutting down. Unblocks at 06:00.",
    )
    request_steam_shutdown()
    kill_gaming_processes(_kill_set(rules), force=False)
    return replace(state, blocked_at=now.timestamp())


def _sustain_block(
    state: PlaytimeState,
    rules: PlaytimeRules,
    *,
    now: datetime,
) -> PlaytimeState:
    """Hold the block: mask the binaries once the grace has passed, keep killing.

    Args:
        state: Current accounting state.
        rules: Policy for this tick.
        now: Timezone-aware local timestamp.

    Returns:
        *state*, unchanged — upkeep mutates the system, not the record.
    """
    elapsed = now.timestamp() - state.blocked_at
    if elapsed >= _SHUTDOWN_GRACE_SECONDS:
        reconcile(should_block=True)
    kill_gaming_processes(_kill_set(rules), force=elapsed >= rules.sigkill_after)
    return state


def _kill_set(rules: PlaytimeRules) -> set[int]:
    """Return every PID the cutoff should terminate.

    Wider than :func:`qualifying_pids` on purpose. A Lutris-launched Wine game
    has no ``SteamAppId`` and its ``comm`` is the game's own binary, so neither
    matcher sees it — only walking down from the launcher does.

    Args:
        rules: Policy for this tick.

    Returns:
        PIDs to signal.
    """
    return qualifying_pids(rules) | steam_and_launcher_pids()


def _humanise(seconds: int) -> str:
    """Render a warning threshold as a short human phrase.

    Args:
        seconds: Seconds remaining.

    Returns:
        A phrase such as ``"30 minutes"`` or ``"10 seconds"``.
    """
    if seconds < _SECONDS_PER_MINUTE:
        return f"{seconds} seconds"
    minutes = seconds // _SECONDS_PER_MINUTE
    return "1 hour" if minutes == _MINUTES_PER_HOUR else f"{minutes} minutes"
