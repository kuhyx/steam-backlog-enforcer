"""The individual steps one enforce pass performs.

Split out of :mod:`steam_backlog_enforcer._enforce_loop` to keep both files
under the 250-line cap: this module holds *what* each pass does, while the
loop module owns the cadence and the surrounding lifecycle.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import allowed_app_ids, allowed_games
from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._owned_apps_cache import get_all_owned_app_ids
from steam_backlog_enforcer._steam_client import is_game_installed
from steam_backlog_enforcer._steam_state import steam_library_ready
from steam_backlog_enforcer.enforcer import send_notification
from steam_backlog_enforcer.game_install import install_game
from steam_backlog_enforcer.game_uninstall import uninstall_other_games
from steam_backlog_enforcer.library_hider import try_hide_other_games
from steam_backlog_enforcer.store_blocker import block_store

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

logger = logging.getLogger(__name__)


def _reinstall_missing_allowed(config: Config, state: State) -> None:
    """Re-install any allowed game that vanished between loop iterations.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    # Nothing is reinstallable without a Steam library, and every game looks
    # "missing" when steamapps does not exist — logging per game per 3s pass
    # is just noise. install_game guards this too; returning here keeps the
    # log quiet as well.
    if not steam_library_ready():
        return

    for app_id, name in allowed_games(state):
        if is_game_installed(app_id):
            continue
        logger.info("Allowed game disappeared — re-installing %s", name)
        install_game(app_id, name, config.steam_id)


def _enforce_setup(config: Config, state: State) -> None:
    """Perform initial setup for enforcement mode.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    # Initial store block.
    if config.block_store:
        if block_store():
            _echo("  Steam store: BLOCKED")
        else:
            _echo("  Steam store: FAILED (need sudo?)")

    # Initial cleanup.
    if config.uninstall_other_games:
        _echo("  Uninstalling non-assigned games...")
        count = uninstall_other_games(allowed_app_ids(state))
        _echo(f"  Uninstalled {count} games")

    # Auto-install the assigned game.
    _enforce_auto_install(config, state)

    # Hide all other games in the Steam library.
    _enforce_hide_games(config, state)


def _enforce_auto_install(config: Config, state: State) -> None:
    """Auto-install every allowed game that is not installed yet.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    for app_id, name in allowed_games(state):
        if is_game_installed(app_id):
            _echo(f"  Allowed game already installed: {name}")
            continue
        _echo(f"  Auto-installing {name}...")
        if install_game(
            app_id,
            name,
            config.steam_id,
            use_steam_protocol=True,
        ):
            send_notification("Game Installing", f"{name} is being downloaded.")
        else:
            _echo("  Could not auto-install. Install manually from Steam.")


def _enforce_hide_games(config: Config, state: State) -> None:
    """Hide non-assigned games in the Steam library.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    owned_ids = get_all_owned_app_ids(config)
    if not owned_ids:
        _echo("  Library hiding: skipped (no owned game list — run 'scan' first)")
        return

    # An unreachable Steam is not fatal: with no client there is no library to
    # hide, and everything else the enforcer does (store block, install guard)
    # still works. Letting this escape used to exit(1) into Restart=always,
    # which spun the service through ~1000 restarts against a Steam that had
    # been uninstalled - each attempt leaving a dead process named "steam"
    # behind that /proc scanners misread as a live Steam.
    hidden, skipped = try_hide_other_games(owned_ids, allowed_app_ids(state))
    if skipped is not None:
        _echo(f"  Library hiding: skipped ({skipped})")
        return

    if hidden > 0:
        _echo(f"  Library: hid {hidden} games (only assigned game visible)")
    else:
        _echo("  Library: games already hidden")
