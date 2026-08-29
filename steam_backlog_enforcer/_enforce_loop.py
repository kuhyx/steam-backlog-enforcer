"""Enforcement daemon loop and related helpers."""

from __future__ import annotations

import json
import logging
import time

from steam_backlog_enforcer._actions import allowed_app_ids, allowed_games
from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._enforce_steps import (
    _enforce_setup,
    _reinstall_missing_allowed,
)

# Re-exported: five modules and the test suite import get_all_owned_app_ids
# from here, so splitting it into _owned_apps_cache stays invisible to them.
from steam_backlog_enforcer._owned_apps_cache import get_all_owned_app_ids
from steam_backlog_enforcer._pick_completion import (
    daemon_sweep,
    retire_completed_manual_picks_throttled,
)
from steam_backlog_enforcer._playtime import playtime_tick
from steam_backlog_enforcer._playtime_session import PlaytimeSession, new_session
from steam_backlog_enforcer._steam_launch import steam_is_installed
from steam_backlog_enforcer._total_block import (
    end_total_block_cleanup,
    enforce_total_block_tick,
    is_total_block_active,
    total_block_needs_cleanup,
)
from steam_backlog_enforcer._whitelist import (
    lock_enforcement_files,
)
from steam_backlog_enforcer.config import (
    CONFIG_FILE,
    Config,
    State,
)
from steam_backlog_enforcer.enforcer import (
    enforce_allowed_game,
    send_notification,
)
from steam_backlog_enforcer.game_uninstall import (
    get_installed_games,
    is_protected_app,
    uninstall_game,
)

logger = logging.getLogger(__name__)

# Seconds between enforce passes.
ENFORCE_INTERVAL = 3

__all__ = [
    "ENFORCE_INTERVAL",
    "do_enforce",
    "get_all_owned_app_ids",
]


def _allowed_names(state: State) -> str:
    """Return a human-readable list of the games the user may play.

    Args:
        state: Current enforcer state.

    Returns:
        Comma-separated game names, or "your assigned game" when none is set.
    """
    names = [name for _, name in allowed_games(state) if name]
    return ", ".join(names) if names else "your assigned game"


def _guard_installed_games(allowed_app_ids: set[int]) -> int:
    """Remove any unauthorized game manifests + files.  Runs every loop.

    Args:
        allowed_app_ids: Every app id that may stay installed — the assignment
            plus any concurrent manual picks.

    Returns number of games removed this pass.
    """
    if not allowed_app_ids:
        return 0
    installed = get_installed_games()
    count = 0
    for app_id, name in installed:
        if app_id in allowed_app_ids:
            continue
        if is_protected_app(app_id):
            continue

        logger.warning(
            "Unauthorized game detected — removing: %s (AppID=%d)", name, app_id
        )
        if uninstall_game(app_id, name):
            count += 1
            send_notification(
                "Game Removed!",
                f"Uninstalled {name} (AppID={app_id}). "
                f"Only your assigned game(s) are allowed.",
            )
    return count


def _enforce_loop_iteration(
    config: Config,
    state: State,
    *,
    session: PlaytimeSession,
    demo: bool = False,
) -> None:
    """Perform one iteration of the enforcement loop.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
        session: Cross-tick engagement and logging state.
        demo: Run the gaming budget on a 60-second demo budget.
    """
    # Daily gaming budget runs FIRST and unconditionally. Every guard below
    # returns early in situations where gaming time is still being spent (total
    # block active, Steam absent, nothing assigned) and where a 06:00 release
    # still has to happen — gating this on any of them would strand the block.
    playtime_tick(config, interval=ENFORCE_INTERVAL, session=session, demo=demo)

    # Total block takes priority over the assigned-game enforcement below -
    # while active, don't fight ourselves (e.g. installing the assigned
    # game while total-block tries to keep Steam uninstalled).
    if is_total_block_active():
        enforce_total_block_tick()
        return

    if total_block_needs_cleanup():
        end_total_block_cleanup()

    # With no Steam client there is no library, no installs and no game
    # processes, so every branch below is a no-op at best - and at worst a
    # 3s-interval error loop trying to write manifests into a steamapps
    # directory that a total block deleted. The total-block tick above still
    # runs: keeping Steam uninstalled is exactly what it is for.
    if not steam_is_installed():
        return

    # Retire manual picks that have hit 100%, at most once every
    # MANUAL_PICK_RECHECK_TTL_SECONDS - this loop ticks every 3s.
    retire_completed_manual_picks_throttled(config, state)

    # Record, but do not evict. A pick the daemon just retired is no longer in
    # allowed_app_ids, so steps A and B below would kill the running process
    # and uninstall the game - possibly seconds after the final achievement
    # popped, mid-session. Keeping those ids allowed defers eviction to a
    # user-invoked done/check/pick-manual, which is where it was before.
    allowed = allowed_app_ids(state) | daemon_sweep.retired
    if not allowed:
        return

    # A) Kill unauthorized game processes.
    if config.kill_unauthorized_games:
        violations = enforce_allowed_game(allowed, kill_unauthorized=True)
        for pid, app_id in violations:
            _echo(f"  Killed unauthorized game: AppID={app_id} (PID={pid})")
            send_notification(
                "Game Blocked!",
                f"Killed unauthorized game (AppID={app_id}). "
                f"Focus on {_allowed_names(state)}!",
            )

    # B) Remove any newly-installed unauthorized games.
    if config.uninstall_other_games:
        removed = _guard_installed_games(allowed)
        if removed > 0:
            _echo(f"  Guard removed {removed} unauthorized game(s)")

    # C) Re-install any allowed game that was somehow removed.
    _reinstall_missing_allowed(config, state)

    # D) Re-apply immutable flag so config cannot be edited without root.
    lock_enforcement_files(CONFIG_FILE)


def do_enforce(config: Config, state: State, *, demo: bool = False) -> None:
    """Run the enforcer: block store, uninstall other games, kill processes.

    This is a persistent loop that continuously:
    1. Keeps the Steam store blocked.
    2. Removes any newly-installed unauthorized games.
    3. Auto-installs the assigned game if missing.
    4. Kills any running unauthorized game processes.
    5. Accounts for the daily gaming budget and enforces its cutoff.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
        demo: Run the gaming budget on a 60-second demo budget.
    """
    if is_total_block_active():
        _echo(
            "Total gaming block ACTIVE - enforcing that instead of any assigned game."
        )
    elif state.current_app_id is None:
        # Fall through to the idle loop for the same reason as the Steam
        # branch below, plus one of its own: the daily gaming budget is
        # enforced from this loop, so returning here would silently stop
        # counting playtime whenever a game is finished but not yet rescanned.
        _echo("No game assigned. Run 'scan' first.")
        _echo("  (Daily gaming budget is still enforced.)")
    elif not steam_is_installed():
        # Fall through to the idle loop rather than returning: returning exits
        # the process, and under Restart=always that is just the crash loop
        # again by another name. Staying alive also means a later Steam
        # reinstall is picked up without needing a restart.
        _echo("Steam is not installed — nothing to enforce.")
        _echo("  (Reinstall Steam to resume backlog enforcement.)")
    else:
        _echo(f"Enforcing: {state.current_game_name} (AppID={state.current_app_id})")
        _enforce_setup(config, state)

    _echo(f"  Enforce loop: ACTIVE (every {ENFORCE_INTERVAL}s)")
    _echo("  Guarding: processes + installs + store")
    _echo("  Press Ctrl+C to stop.\n")
    # One session for the whole daemon: the engagement backdate needs to see
    # the previous tick's verdict, so it cannot be rebuilt per iteration.
    session = new_session(demo=demo)
    try:
        while True:
            # Reload state from disk so CLI changes (e.g. new game
            # assignment via ``done`` / ``scan``) take effect immediately
            # without needing to restart the daemon.
            try:
                fresh = State.load()
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.warning("Failed to reload state: %s", exc)
                time.sleep(ENFORCE_INTERVAL)
                continue
            state.current_app_id = fresh.current_app_id
            state.current_game_name = fresh.current_game_name
            state.finished_app_ids = fresh.finished_app_ids
            # Manual picks too: the MCP pick_manual tool adds a *second* pick
            # without touching current_app_id, so a daemon that never reloaded
            # this list would uninstall that pick as unauthorized.
            state.manual_picks = fresh.manual_picks

            _enforce_loop_iteration(config, state, session=session, demo=demo)
            time.sleep(ENFORCE_INTERVAL)
    except KeyboardInterrupt:
        _echo("\nEnforcer stopped.")
