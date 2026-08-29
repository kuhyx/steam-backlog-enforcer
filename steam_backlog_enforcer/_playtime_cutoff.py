"""Warning, cutoff and kill steps of the playtime policy.

The escalation ladder once a budget is spent: warn, ask Steam to shut down
cleanly, then mask its binaries and SIGTERM/SIGKILL what is still running.
The grace between shutdown and masking exists because masking makes
``steam -shutdown`` itself a no-op.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._playtime_block import (
    reconcile,
)
from steam_backlog_enforcer._playtime_budget import pending_warning
from steam_backlog_enforcer._playtime_kill import (
    kill_gaming_processes,
    request_steam_shutdown,
    steam_and_launcher_pids,
)
from steam_backlog_enforcer._playtime_notify import _humanise, notify_desktop_user
from steam_backlog_enforcer._playtime_procs import qualifying_pids
from steam_backlog_enforcer._playtime_state import (
    _SHUTDOWN_GRACE_SECONDS,
    PlaytimeRules,
    PlaytimeState,
)

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


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
    return set(qualifying_pids(rules)) | steam_and_launcher_pids()
