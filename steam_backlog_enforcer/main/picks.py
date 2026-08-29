"""Game-selection commands: ``pick``, ``pick-manual`` and ``abandon-pick``."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import (
    active_manual_picks,
    allowed_app_ids,
    allowed_games,
    apply_manual_pick,
    manual_pick_slots_left,
)
from steam_backlog_enforcer._allowed_games import (
    MANUAL_LOCK_DAYS as _MANUAL_LOCK_DAYS,
)
from steam_backlog_enforcer._enforce_loop import get_all_owned_app_ids
from steam_backlog_enforcer._hltb_types import load_hltb_cache
from steam_backlog_enforcer.config import load_snapshot
from steam_backlog_enforcer.game_install import (
    _echo,
    install_game,
    is_game_installed,
    uninstall_other_games,
)
from steam_backlog_enforcer.library_hider import try_hide_other_games
from steam_backlog_enforcer.main._shared import _MANUAL_LOCK_EXEMPT_COMMANDS
from steam_backlog_enforcer.scanning import pick_next_game
from steam_backlog_enforcer.steam_api import (
    GameInfo,
    SteamAPIClient,
    SteamAPIError,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State


def cmd_pick(config: Config, state: State) -> None:
    """Manually pick a new game from the shortest-first candidate list."""
    snapshot_data = load_snapshot()
    if not snapshot_data:
        _echo("No snapshot found. Run 'scan' first.")
        return

    games = [GameInfo.from_snapshot(d) for d in snapshot_data]
    hltb_cache = load_hltb_cache()
    for game in games:
        if game.app_id in hltb_cache:
            game.completionist_hours = hltb_cache[game.app_id]

    pick_next_game(games, state, config)

    if state.current_app_id is not None:
        owned_ids = get_all_owned_app_ids(config)
        if owned_ids:
            hidden, skipped = try_hide_other_games(owned_ids, allowed_app_ids(state))
            if skipped is not None:
                _echo(f"\n  Library hiding: skipped ({skipped})")
            elif hidden > 0:
                _echo(f"\n  Library: hid {hidden} games")


def _resolve_game_name(config: Config, app_id: int) -> str | None:
    """Look up a game name by app_id, checking snapshot then Steam API.

    Returns the game name, or None if not found.
    """
    # Fast path: snapshot already on disk.
    snapshot = load_snapshot()
    if snapshot:
        for entry in snapshot:
            if entry.get("app_id") == app_id:
                return str(entry["name"])

    # Slower path: owned games API.
    try:
        client = SteamAPIClient(config.steam_api_key, config.steam_id)
        owned = client.get_owned_games()
        for g in owned:
            if g.get("appid") == app_id:
                return str(g.get("name", f"Unknown ({app_id})"))
    except SteamAPIError, OSError, RuntimeError, ValueError:
        return None

    return None


def _report_pick_slots(config: Config, state: State) -> list[dict[str, object]]:
    """Show which manual picks are already locked in; exit if the cap is full.

    Args:
        config: Enforcer configuration (for ``max_manual_picks``).
        state: Current enforcer state.

    Returns:
        The currently-active manual picks.
    """
    existing = active_manual_picks(state)
    if existing:
        _echo(f"\nAlready locked in ({len(existing)}/{config.max_manual_picks}):")
        for pick in existing:
            _echo(f"  - {pick['game_name']} (AppID={pick['app_id']})")

    if manual_pick_slots_left(state, config.max_manual_picks) == 0:
        _echo(
            f"\nError: you already have {config.max_manual_picks} manual pick(s)."
            f"\nFinish one, or undo one with 'abandon-pick <app_id>' — a pick"
            f"\ncan be abandoned at any time."
        )
        sys.exit(1)

    return existing


def _apply_allowed_set(config: Config, state: State) -> None:
    """Make the filesystem and library match the allowed set.

    Uninstalls everything outside it, installs every allowed game that is
    missing, and hides the rest of the library. Operating on the whole set
    (rather than one app id) is what lets a second manual pick coexist with
    the first instead of tearing it down.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    allowed = allowed_app_ids(state)

    if config.uninstall_other_games:
        _echo("  Uninstalling non-allowed games...")
        count = uninstall_other_games(allowed)
        if count:
            _echo(f"  Uninstalled {count} non-allowed game(s)")

    for app_id, name in allowed_games(state):
        if is_game_installed(app_id):
            _echo(f"  {name} is already installed.")
            continue
        _echo(f"  Installing {name}...")
        install_game(app_id, name, config.steam_id, use_steam_protocol=True)

    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden, skipped = try_hide_other_games(owned_ids, allowed)
        if skipped is not None:
            _echo(f"  Library hiding: skipped ({skipped})")
        elif hidden > 0:
            _echo(f"  Library: hid {hidden} games")


def cmd_pick_manual(config: Config, state: State, args: list[str]) -> None:
    """Manually pick a game by Steam app_id, locking the enforcer for 2 weeks.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
        args: Remaining CLI args (first element should be the app_id).
    """
    raw_id = args[0] if args else input("Enter Steam app_id: ").strip()

    try:
        app_id = int(raw_id)
    except ValueError:
        _echo(f"Error: app_id must be a number, got '{raw_id}'.")
        return

    _echo(f"Looking up AppID={app_id}...")
    game_name = _resolve_game_name(config, app_id)
    if game_name is None:
        _echo(
            f"Error: AppID={app_id} not found in your Steam library or snapshot.\n"
            "Run 'scan' first, or verify the app_id is correct."
        )
        return

    _echo(f"\nGame found: {game_name} (AppID={app_id})")

    existing = _report_pick_slots(config, state)

    _echo(
        f"\nWARNING: Picking this game will:"
        f"\n  - Add it to your allowed games ({len(existing) + 1} of"
        f" {config.max_manual_picks} slot(s) used)"
        f"\n  - Lock ALL other commands for {_MANUAL_LOCK_DAYS} DAYS or until"
        f"\n    you reach 100% achievements on every pick"
        f"\n  - Leave only these commands usable:"
        f"\n    {', '.join(sorted(_MANUAL_LOCK_EXEMPT_COMMANDS))}"
        f"\n  - Stay undoable at any time via 'abandon-pick {app_id}'"
    )
    _echo()
    confirm = input(
        f"Type YES to confirm you will play {game_name} until completion: "
    ).strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    # State mutation is the shared, stdout-free core (also used by the MCP
    # server); the destructive post-assignment cascade below stays CLI-only.
    refused = apply_manual_pick(
        state,
        app_id,
        game_name,
        max_picks=config.max_manual_picks,
    )
    if refused is not None:
        _echo(f"\nError: {refused}")
        sys.exit(1)

    _echo(f"\nManual pick confirmed: {game_name} (AppID={app_id})")
    _echo(f"Lock active from now until 100% achievements or {_MANUAL_LOCK_DAYS} days.")
    _echo("Run 'done' or 'check' once you have 100% to release the lock.\n")

    # Post-assignment: mirror what _assign_chosen_game + cmd_pick do, but for
    # the whole allowed set so an earlier pick is not torn down by a later one.
    _apply_allowed_set(config, state)
