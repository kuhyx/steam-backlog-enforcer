"""Enforcement daemon loop and related helpers."""

from __future__ import annotations

import json
import logging
import time

from python_pkg.steam_backlog_enforcer.config import (
    Config,
    State,
    load_snapshot,
)
from python_pkg.steam_backlog_enforcer.enforcer import (
    enforce_allowed_game,
    send_notification,
)
from python_pkg.steam_backlog_enforcer.game_install import (
    PROTECTED_APP_IDS,
    _echo,
    get_installed_games,
    install_game,
    is_game_installed,
    uninstall_game,
    uninstall_other_games,
)
from python_pkg.steam_backlog_enforcer.library_hider import hide_other_games
from python_pkg.steam_backlog_enforcer.steam_api import SteamAPIClient
from python_pkg.steam_backlog_enforcer.store_blocker import block_store

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def get_all_owned_app_ids(config: Config) -> list[int]:
    """Get all owned game app IDs from Steam API plus snapshot fallback.

    Snapshot data contains only games with achievements, so API data is the
    primary source for library hiding. Snapshot IDs are merged in to keep
    behavior resilient when the API result is partial.
    """
    snapshot = load_snapshot() or []
    snapshot_ids = [int(d["app_id"]) for d in snapshot if "app_id" in d]

    try:
        client = SteamAPIClient(config.steam_api_key, config.steam_id)
        owned = client.get_owned_games()
        api_ids = [int(g["appid"]) for g in owned if "appid" in g]

        merged_ids: list[int] = []
        seen: set[int] = set()
        for app_id in [*api_ids, *snapshot_ids]:
            if app_id in seen:
                continue
            seen.add(app_id)
            merged_ids.append(app_id)
    except (OSError, RuntimeError, ValueError):
        if snapshot_ids:
            return snapshot_ids
        logger.warning("Could not fetch owned game list for hiding.")
        return []
    else:
        return merged_ids


# ──────────────────────────────────────────────────────────────
# Enforce mode (daemon loop)
# ──────────────────────────────────────────────────────────────

# How often the enforce loop runs (seconds).
ENFORCE_INTERVAL = 3


def _guard_installed_games(allowed_app_id: int | None) -> int:
    """Remove any unauthorized game manifests + files.  Runs every loop.

    Returns number of games removed this pass.
    """
    if allowed_app_id is None:
        return 0
    installed = get_installed_games()
    count = 0
    for app_id, name in installed:
        if app_id == allowed_app_id:
            continue
        if app_id in PROTECTED_APP_IDS:
            continue

        logger.warning(
            "Unauthorized game detected — removing: %s (AppID=%d)", name, app_id
        )
        if uninstall_game(app_id, name):
            count += 1
            send_notification(
                "Game Removed!",
                f"Uninstalled {name} (AppID={app_id}). "
                f"Only the assigned game is allowed.",
            )
    return count


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
        count = uninstall_other_games(state.current_app_id)
        _echo(f"  Uninstalled {count} games")

    # Auto-install the assigned game.
    _enforce_auto_install(config, state)

    # Hide all other games in the Steam library.
    _enforce_hide_games(config, state)


def _enforce_auto_install(config: Config, state: State) -> None:
    """Auto-install the assigned game if not already installed.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    app_id = state.current_app_id
    if app_id is None:
        return
    if not is_game_installed(app_id):
        _echo(f"  Auto-installing {state.current_game_name}...")
        if install_game(
            app_id,
            state.current_game_name,
            config.steam_id,
            use_steam_protocol=True,
        ):
            send_notification(
                "Game Installing",
                f"{state.current_game_name} is being downloaded.",
            )
        else:
            _echo("  Could not auto-install. Install manually from Steam.")
    else:
        _echo(f"  Assigned game already installed: {state.current_game_name}")


def _enforce_hide_games(config: Config, state: State) -> None:
    """Hide non-assigned games in the Steam library.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden = hide_other_games(owned_ids, state.current_app_id)
        if hidden > 0:
            _echo(f"  Library: hid {hidden} games (only assigned game visible)")
        else:
            _echo("  Library: games already hidden")
    else:
        _echo("  Library hiding: skipped (no owned game list — run 'scan' first)")


def _enforce_loop_iteration(config: Config, state: State) -> None:
    """Perform one iteration of the enforcement loop.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    if state.current_app_id is None:
        return

    # A) Kill unauthorized game processes.
    if config.kill_unauthorized_games:
        violations = enforce_allowed_game(
            state.current_app_id,
            kill_unauthorized=True,
        )
        for pid, app_id in violations:
            _echo(f"  Killed unauthorized game: AppID={app_id} (PID={pid})")
            send_notification(
                "Game Blocked!",
                f"Killed unauthorized game (AppID={app_id}). "
                f"Focus on {state.current_game_name}!",
            )

    # B) Remove any newly-installed unauthorized games.
    if config.uninstall_other_games:
        removed = _guard_installed_games(state.current_app_id)
        if removed > 0:
            _echo(f"  Guard removed {removed} unauthorized game(s)")

    # C) Re-install assigned game if it was somehow removed.
    app_id = state.current_app_id
    if app_id is not None and not is_game_installed(app_id):
        logger.info(
            "Assigned game disappeared — re-installing %s",
            state.current_game_name,
        )
        install_game(
            app_id,
            state.current_game_name,
            config.steam_id,
        )


def do_enforce(config: Config, state: State) -> None:
    """Run the enforcer: block store, uninstall other games, kill processes.

    This is a persistent loop that continuously:
    1. Keeps the Steam store blocked.
    2. Removes any newly-installed unauthorized games.
    3. Auto-installs the assigned game if missing.
    4. Kills any running unauthorized game processes.
    """
    if state.current_app_id is None:
        _echo("No game assigned. Run 'scan' first.")
        return

    _echo(f"Enforcing: {state.current_game_name} (AppID={state.current_app_id})")
    _enforce_setup(config, state)

    _echo(f"  Enforce loop: ACTIVE (every {ENFORCE_INTERVAL}s)")
    _echo("  Guarding: processes + installs + store")
    _echo("  Press Ctrl+C to stop.\n")
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

            _enforce_loop_iteration(config, state)
            time.sleep(ENFORCE_INTERVAL)
    except KeyboardInterrupt:
        _echo("\nEnforcer stopped.")
