"""Install, uninstall and library-visibility commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import allowed_app_ids, allowed_games
from steam_backlog_enforcer._enforce_loop import get_all_owned_app_ids
from steam_backlog_enforcer.game_install import (
    _echo,
    get_installed_games,
    install_game,
    is_game_installed,
    is_protected_app,
    uninstall_other_games,
)
from steam_backlog_enforcer.library_hider import (
    try_hide_other_games,
    unhide_all_games,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State


def cmd_installed(_config: Config, state: State) -> None:
    """Show installed games."""
    installed = get_installed_games()
    _echo(f"\nInstalled games ({len(installed)}):\n")
    for app_id, name in installed:
        protected = " [PROTECTED]" if is_protected_app(app_id) else ""
        assigned = " <<< ASSIGNED" if app_id == state.current_app_id else ""
        _echo(f"  {app_id:>8d}  {name}{protected}{assigned}")


def cmd_uninstall(_config: Config, state: State) -> None:
    """Uninstall all games except the assigned one."""
    if state.current_app_id is None:
        _echo("No game assigned. Run 'scan' first.")
        return

    allowed = allowed_app_ids(state)
    installed = get_installed_games()
    to_remove = [
        (aid, n)
        for aid, n in installed
        if aid not in allowed and not is_protected_app(aid)
    ]

    if not to_remove:
        _echo("No games to uninstall (only allowed games and runtimes installed).")
        return

    _echo(f"\nWill uninstall {len(to_remove)} games, keeping:")
    for aid, name in allowed_games(state):
        _echo(f"  - {name} (AppID={aid})")
    _echo("  - Steam runtimes and Proton versions\n")
    _echo("Games to remove:")
    for aid, name in to_remove:
        _echo(f"  - {name} (AppID={aid})")

    _echo()
    confirm = input("Type YES to confirm: ").strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    count = uninstall_other_games(allowed_app_ids(state))
    _echo(f"\nUninstalled {count} games.")


def cmd_install(config: Config, state: State) -> None:
    """Manually trigger install of the assigned game."""
    if state.current_app_id is None:
        _echo("No game currently assigned. Run 'scan' first.")
        return

    if is_game_installed(state.current_app_id):
        _echo(f"{state.current_game_name} is already installed.")
        return

    _echo(f"Installing {state.current_game_name} (AppID={state.current_app_id})...")
    if install_game(
        state.current_app_id,
        state.current_game_name,
        config.steam_id,
        use_steam_protocol=True,
    ):
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
    hidden, skipped = try_hide_other_games(owned_ids, allowed_app_ids(state))
    if skipped is not None:
        _echo(f"Library hiding: skipped ({skipped})")
        return
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
