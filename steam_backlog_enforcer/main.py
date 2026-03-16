"""Main CLI for Steam Backlog Enforcer."""

from __future__ import annotations

import logging
import sys

from python_pkg.steam_backlog_enforcer.config import (
    Config,
    State,
    interactive_setup,
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
    uninstall_other_games,
)
from python_pkg.steam_backlog_enforcer.hltb import (
    fetch_hltb_times_cached,
    load_hltb_cache,
)
from python_pkg.steam_backlog_enforcer.library_hider import (
    hide_other_games,
    restart_steam,
    unhide_all_games,
)
from python_pkg.steam_backlog_enforcer.scanning import (
    _pick_playable_candidate,
    do_check,
    do_enforce,
    do_scan,
    get_all_owned_app_ids,
    pick_next_game,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient
from python_pkg.steam_backlog_enforcer.store_blocker import (
    block_store,
    is_store_blocked,
    unblock_store,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_LIST_DISPLAY_LIMIT = 50
_MIN_CLI_ARGS = 2


# ──────────────────────────────────────────────────────────────
# CLI commands
# ──────────────────────────────────────────────────────────────


def cmd_status(_config: Config, state: State) -> None:
    """Show current status."""
    _echo("=== Steam Backlog Enforcer ===\n")

    if state.current_app_id:
        _echo(
            f"Assigned game: {state.current_game_name} (AppID={state.current_app_id})"
        )
    else:
        _echo("No game currently assigned.")

    _echo(f"Finished games: {len(state.finished_app_ids)}")
    _echo(f"Store blocked:  {is_store_blocked()}")

    # Show installed games.
    installed = get_installed_games()
    real_games = [(aid, n) for aid, n in installed if aid not in PROTECTED_APP_IDS]
    _echo(f"Installed games: {len(real_games)}")

    if state.current_app_id:
        is_assigned_installed = any(aid == state.current_app_id for aid, _ in installed)
        _echo(f"Assigned game installed: {is_assigned_installed}")


def cmd_list(_config: Config, state: State) -> None:
    """List games from the last snapshot."""
    snapshot = load_snapshot()
    if snapshot is None:
        _echo("No snapshot found. Run 'scan' first.")
        return

    games = [GameInfo.from_snapshot(d) for d in snapshot]
    incomplete = [g for g in games if not g.is_complete]
    complete = [g for g in games if g.is_complete]

    # Sort incomplete by completionist hours.
    def sort_key(g: GameInfo) -> tuple[int, float]:
        if g.completionist_hours > 0:
            return (0, g.completionist_hours)
        return (1, 0.0)

    incomplete.sort(key=sort_key)

    _echo(f"\n{'─' * 70}")
    _echo(f"  INCOMPLETE ({len(incomplete)} games)")
    _echo(f"{'─' * 70}")
    for i, g in enumerate(incomplete[:_LIST_DISPLAY_LIMIT], 1):
        marker = " <<< ASSIGNED" if g.app_id == state.current_app_id else ""
        hrs = f" [{g.completionist_hours:.0f}h]" if g.completionist_hours > 0 else ""
        pct = f"{g.completion_pct:.0f}%"
        _echo(f"  {i:3d}. {g.name[:40]:<40s} {pct:>5s}{hrs}{marker}")

    if len(incomplete) > _LIST_DISPLAY_LIMIT:
        _echo(f"  ... and {len(incomplete) - _LIST_DISPLAY_LIMIT} more")

    _echo(f"\n  COMPLETE: {len(complete)} games")


def cmd_unblock(_config: Config, _state: State) -> None:
    """Remove store blocking."""
    if unblock_store():
        _echo("Steam store unblocked.")
    else:
        _echo("Failed to unblock. Run with sudo.")


def cmd_buy_dlc(config: Config, state: State) -> None:
    """Temporarily unblock the store so the user can buy DLC."""
    if state.current_app_id is None:
        _echo("No game currently assigned.")
        return

    _echo(f"Current game: {state.current_game_name} (AppID={state.current_app_id})")
    _echo("Unblocking Steam store for DLC purchase...")

    if not unblock_store():
        _echo("Failed to unblock store. Run with sudo.")
        return

    _echo("\nStore UNBLOCKED — buy your DLC now.")
    _echo("Press Enter when you're done to re-block the store...")
    input()

    if config.block_store:
        if block_store():
            _echo("Store re-blocked. Restarting Steam to clear DNS cache...")
            restart_steam()
            _echo("Done.")
        else:
            _echo("Warning: failed to re-block store.")


def cmd_reset(config: Config, state: State) -> None:
    """Reset all state (unblock, unhide, clear assignment)."""
    unblock_store()

    # Unhide all games in the library.
    try:
        owned = get_all_owned_app_ids(config)
        if owned:
            count = unhide_all_games(owned)
            if count:
                _echo(f"Unhidden {count} games.")
    except (OSError, RuntimeError, ValueError) as exc:
        _echo(f"Warning: could not unhide games: {exc}")

    state.current_app_id = None
    state.current_game_name = ""
    state.finished_app_ids = []
    state.save()
    _echo("State reset. Store unblocked.")


def cmd_installed(_config: Config, state: State) -> None:
    """Show installed games."""
    installed = get_installed_games()
    _echo(f"\nInstalled games ({len(installed)}):\n")
    for app_id, name in installed:
        protected = " [PROTECTED]" if app_id in PROTECTED_APP_IDS else ""
        assigned = " <<< ASSIGNED" if app_id == state.current_app_id else ""
        _echo(f"  {app_id:>8d}  {name}{protected}{assigned}")


def cmd_uninstall(_config: Config, state: State) -> None:
    """Uninstall all games except the assigned one."""
    if state.current_app_id is None:
        _echo("No game assigned. Run 'scan' first.")
        return

    installed = get_installed_games()
    to_remove = [
        (aid, n)
        for aid, n in installed
        if aid != state.current_app_id and aid not in PROTECTED_APP_IDS
    ]

    if not to_remove:
        _echo("No games to uninstall (only assigned game and runtimes installed).")
        return

    _echo(f"\nWill uninstall {len(to_remove)} games, keeping:")
    _echo(f"  - {state.current_game_name} (AppID={state.current_app_id})")
    _echo("  - Steam runtimes and Proton versions\n")
    _echo("Games to remove:")
    for aid, name in to_remove:
        _echo(f"  - {name} (AppID={aid})")

    _echo()
    confirm = input("Type YES to confirm: ").strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    count = uninstall_other_games(state.current_app_id)
    _echo(f"\nUninstalled {count} games.")


def cmd_setup(_config: Config, _state: State) -> None:
    """Run interactive setup."""
    interactive_setup()


def cmd_install(config: Config, state: State) -> None:
    """Manually trigger install of the assigned game."""
    if state.current_app_id is None:
        _echo("No game currently assigned. Run 'scan' first.")
        return

    if is_game_installed(state.current_app_id):
        _echo(f"{state.current_game_name} is already installed.")
        return

    _echo(f"Installing {state.current_game_name} (AppID={state.current_app_id})...")
    if install_game(state.current_app_id, state.current_game_name, config.steam_id):
        _echo("Done!")
    else:
        _echo("Failed to create install manifest.")


def cmd_hide(config: Config, state: State) -> None:
    """Hide all non-assigned games in the Steam library."""
    if state.current_app_id is None:
        _echo("No game assigned. Run 'scan' first.")
        return

    owned_ids = get_all_owned_app_ids(config)
    if not owned_ids:
        _echo("No owned game list available. Run 'scan' first.")
        return

    _echo(f"Hiding all games except {state.current_game_name}...")
    hidden = hide_other_games(owned_ids, state.current_app_id)
    _echo(f"Hidden {hidden} games.")

    if hidden > 0:
        _echo("Done! Only the assigned game should be visible in your library.")


def cmd_unhide(config: Config, _state: State) -> None:
    """Unhide all games in the Steam library."""
    owned_ids = get_all_owned_app_ids(config)
    if not owned_ids:
        _echo("No owned game list available. Run 'scan' first.")
        return

    _echo("Unhiding all games...")
    count = unhide_all_games(owned_ids)
    _echo(f"Unhidden {count} games.")

    if count > 0:
        _echo("Done!")


def _try_reassign_shorter_game(
    hltb_cache: dict[int, float],
    app_id: int,
    hours: float,
    state: State,
    config: Config,
) -> bool:
    """Check if a shorter game is available and reassign if so."""
    snapshot_data = load_snapshot()
    if not snapshot_data:
        return False
    all_games = [GameInfo.from_snapshot(d) for d in snapshot_data]
    for g in all_games:
        cached_hours = hltb_cache.get(g.app_id, -1.0)
        if cached_hours > 0:
            g.completionist_hours = cached_hours
    skip = set(config.skip_app_ids) | set(state.finished_app_ids)
    candidates = [
        g
        for g in all_games
        if not g.is_complete and g.app_id not in skip and g.completionist_hours > 0
    ]
    candidates.sort(key=lambda g: g.completionist_hours)
    if not candidates or candidates[0].app_id == app_id:
        return False
    # Filter out Linux-incompatible games before deciding to reassign.
    playable = _pick_playable_candidate(
        [c for c in candidates if c.app_id != app_id],
    )
    if playable is None or playable.completionist_hours >= hours:
        return False
    _echo(
        f"\n  Reassigning: {playable.name} is shorter"
        f" (~{playable.completionist_hours:.1f}h vs ~{hours:.1f}h)"
    )
    pick_next_game(all_games, state, config)
    return True


def _finalize_completion(
    config: Config,
    state: State,
    game_name: str,
    app_id: int,
) -> None:
    """Mark game complete, pick next, hide non-assigned games, notify."""
    _echo(f"\n  COMPLETED: {game_name}!")
    state.finished_app_ids.append(app_id)

    snapshot_data = load_snapshot()
    _echo("\nPicking next game...")
    if not snapshot_data:
        _echo("  No snapshot found. Run 'scan' first.")
        state.current_app_id = None
        state.current_game_name = ""
        state.save()
        return

    games = [GameInfo.from_snapshot(d) for d in snapshot_data]
    pick_next_game(games, state, config)

    if state.current_app_id is None:
        _echo("  No more games to assign!")
        return

    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden = hide_other_games(owned_ids, state.current_app_id)
        if hidden > 0:
            _echo(f"\n  Library: hid {hidden} games")

    send_notification(
        "Game Complete!",
        f"Finished {game_name}! Now playing: {state.current_game_name}",
    )
    _echo(f"\nAll done! Go play {state.current_game_name}!")


def _enforce_on_done(config: Config, state: State) -> None:
    """Run a single enforcement pass during the 'done' command.

    Kills unauthorized game processes, uninstalls unauthorized games,
    and ensures the assigned game is installed.
    """
    if state.current_app_id is None:
        return

    if config.kill_unauthorized_games:
        violations = enforce_allowed_game(
            state.current_app_id,
            kill_unauthorized=True,
        )
        for pid, app_id in violations:
            _echo(f"  Killed unauthorized game: AppID={app_id} (PID={pid})")

    if config.uninstall_other_games:
        count = uninstall_other_games(state.current_app_id)
        if count:
            _echo(f"  Uninstalled {count} unauthorized game(s)")

    if not is_game_installed(state.current_app_id):
        _echo(f"  Re-installing {state.current_game_name}...")
        install_game(
            state.current_app_id,
            state.current_game_name,
            config.steam_id,
        )


def cmd_done(config: Config, state: State) -> None:
    """Check completion, pick next game, uninstall & hide.

    All-in-one command for after finishing a game:
    1. Verify 100% achievements on Steam.
    2. Pick the next game (shortest HLTB 100% time).
    3. Uninstall all non-assigned games.
    4. Hide all non-assigned games in the Steam library.
    5. Install the newly assigned game.
    """
    if state.current_app_id is None:
        _echo("No game currently assigned. Run 'scan' first.")
        return

    client = SteamAPIClient(config.steam_api_key, config.steam_id)
    game_name = state.current_game_name
    app_id = state.current_app_id

    _echo(f"Checking {game_name} (AppID={app_id})...")
    game = client.refresh_single_game(app_id, game_name)
    if game is None:
        _echo("  Could not fetch achievement data from Steam.")
        return

    _echo(
        f"  Progress: {game.unlocked_achievements}/{game.total_achievements}"
        f" ({game.completion_pct:.1f}%)"
    )

    hltb_cache = load_hltb_cache()
    hours = hltb_cache.get(app_id, -1.0)
    if hours < 0:
        hltb_cache = fetch_hltb_times_cached([(app_id, game_name)])
        hours = hltb_cache.get(app_id, -1.0)
    if hours > 0:
        _echo(f"  HLTB 100% estimate: {hours:.1f} hours")

    if _try_reassign_shorter_game(hltb_cache, app_id, hours, state, config):
        return

    if not game.is_complete:
        remaining = game.total_achievements - game.unlocked_achievements
        _echo(f"\n  NOT COMPLETE: {remaining} achievements remaining. Keep going!")
        _enforce_on_done(config, state)
        return

    _finalize_completion(config, state, game_name, app_id)


COMMANDS = {
    "scan": ("Scan library & assign a game", do_scan),
    "check": ("Check assigned game completion", do_check),
    "status": ("Show current status", cmd_status),
    "list": ("List games from snapshot", cmd_list),
    "enforce": ("Run enforcer: block, uninstall, kill, hide", do_enforce),
    "install": ("Install the assigned game", cmd_install),
    "hide": ("Hide all non-assigned games in library", cmd_hide),
    "unhide": ("Unhide all games in library", cmd_unhide),
    "unblock": ("Remove store blocking", cmd_unblock),
    "buy-dlc": ("Temporarily unblock store to buy DLC", cmd_buy_dlc),
    "reset": ("Reset all state", cmd_reset),
    "installed": ("List installed games", cmd_installed),
    "uninstall": ("Uninstall all non-assigned games", cmd_uninstall),
    "setup": ("Run first-time setup", cmd_setup),
    "done": ("Finish game, open HLTB, pick next", cmd_done),
}


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < _MIN_CLI_ARGS or sys.argv[1] not in COMMANDS:
        _echo("Steam Backlog Enforcer\n")
        _echo("Usage: python -m python_pkg.steam_backlog_enforcer.main <command>\n")
        _echo("Commands:")
        for name, (desc, _) in COMMANDS.items():
            _echo(f"  {name:<12s}  {desc}")
        sys.exit(1)

    command = sys.argv[1]
    config = Config.load()

    if command != "setup" and not config.steam_api_key:
        _echo("Not configured. Run 'setup' first.")
        sys.exit(1)

    state = State.load()
    _, func = COMMANDS[command]
    func(config, state)


if __name__ == "__main__":
    main()
