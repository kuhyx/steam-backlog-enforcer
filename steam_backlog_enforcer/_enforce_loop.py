"""Enforcement daemon loop and related helpers."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from steam_backlog_enforcer._actions import allowed_app_ids, allowed_games
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
    CONFIG_DIR,
    CONFIG_FILE,
    Config,
    State,
    _atomic_write,
    load_snapshot,
)
from steam_backlog_enforcer.enforcer import (
    enforce_allowed_game,
    send_notification,
)
from steam_backlog_enforcer.game_install import (
    _echo,
    get_installed_games,
    install_game,
    is_game_installed,
    is_protected_app,
    uninstall_game,
    uninstall_other_games,
)
from steam_backlog_enforcer.library_hider import (
    steam_is_installed,
    try_hide_other_games,
)
from steam_backlog_enforcer.steam_api import SteamAPIClient
from steam_backlog_enforcer.store_blocker import block_store

logger = logging.getLogger(__name__)
_OWNED_IDS_CACHE_FILE = CONFIG_DIR / "owned_app_ids_cache.json"
_OWNED_IDS_CACHE_TTL_SECONDS = 3600


def _load_owned_app_ids_cache(steam_id: str) -> list[int] | None:
    """Return fresh cached owned app IDs for this steam_id, if available."""
    if not steam_id or not _OWNED_IDS_CACHE_FILE.exists():
        return None

    try:
        data: dict[str, Any] = json.loads(
            _OWNED_IDS_CACHE_FILE.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError, ValueError):
        return None

    cached_steam_id = str(data.get("steam_id", ""))
    if cached_steam_id != steam_id:
        return None

    fetched_at = float(data.get("fetched_at", 0.0) or 0.0)
    age = time.time() - fetched_at
    if age > _OWNED_IDS_CACHE_TTL_SECONDS:
        return None

    raw_ids = data.get("app_ids", [])
    if not isinstance(raw_ids, list):
        return None

    return [int(app_id) for app_id in raw_ids]


def _save_owned_app_ids_cache(steam_id: str, app_ids: list[int]) -> None:
    """Persist owned app IDs cache for this steam_id."""
    payload = {
        "steam_id": steam_id,
        "fetched_at": time.time(),
        "app_ids": app_ids,
    }
    _atomic_write(_OWNED_IDS_CACHE_FILE, json.dumps(payload, indent=2) + "\n")


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
    cached_ids = _load_owned_app_ids_cache(config.steam_id)

    if cached_ids is not None:
        merged_ids: list[int] = []
        seen: set[int] = set()
        for app_id in [*cached_ids, *snapshot_ids]:
            if app_id in seen:
                continue
            seen.add(app_id)
            merged_ids.append(app_id)
        logger.info("Using cached Steam owned IDs (%d entries).", len(cached_ids))
        return merged_ids

    try:
        client = SteamAPIClient(config.steam_api_key, config.steam_id)
        owned = client.get_owned_games()
        api_ids = [int(g["appid"]) for g in owned if "appid" in g]
        _save_owned_app_ids_cache(config.steam_id, api_ids)

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


def _reinstall_missing_allowed(config: Config, state: State) -> None:
    """Re-install any allowed game that vanished between loop iterations.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
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


def _enforce_loop_iteration(config: Config, state: State) -> None:
    """Perform one iteration of the enforcement loop.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
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

    allowed = allowed_app_ids(state)
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


def do_enforce(config: Config, state: State) -> None:
    """Run the enforcer: block store, uninstall other games, kill processes.

    This is a persistent loop that continuously:
    1. Keeps the Steam store blocked.
    2. Removes any newly-installed unauthorized games.
    3. Auto-installs the assigned game if missing.
    4. Kills any running unauthorized game processes.
    """
    if is_total_block_active():
        _echo(
            "Total gaming block ACTIVE - enforcing that instead of any assigned game."
        )
    elif state.current_app_id is None:
        _echo("No game assigned. Run 'scan' first.")
        return
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
