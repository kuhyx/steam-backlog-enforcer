"""Install, uninstall and library-visibility commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import allowed_app_ids, allowed_games
from steam_backlog_enforcer._enforce_loop import get_all_owned_app_ids
from steam_backlog_enforcer._fast_install import fast_install_failure
from steam_backlog_enforcer._progress import current_progress
from steam_backlog_enforcer._prompter import (
    PromptOption,
    confirm_phrase,
    current_prompter,
)
from steam_backlog_enforcer._steam_errors import SteamUnavailableError
from steam_backlog_enforcer._steam_restart_guard import game_is_running
from steam_backlog_enforcer._steam_state import is_game_fully_installed
from steam_backlog_enforcer.game_install import (
    _echo,
    get_installed_games,
    install_game,
    is_protected_app,
    uninstall_other_games,
)
from steam_backlog_enforcer.library_hider import (
    try_hide_other_games,
    unhide_all_games,
)
from steam_backlog_enforcer.main._install_target import (
    dry_run_install,
    install_candidates,
    resolve_target,
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
    if not confirm_phrase(
        "uninstall", f"Uninstall {len(to_remove)} games?", count=len(to_remove)
    ):
        _echo("Aborted.")
        return

    count = uninstall_other_games(allowed_app_ids(state))
    _echo(f"\nUninstalled {count} games.")


def _pick_install_target(
    candidates: list[tuple[int, str]],
) -> tuple[int, str] | None:
    """The allowed game to install: the only unfinished one, or the user's pick.

    Every allowed game counts, not just the assignment: a manual pick whose
    fast install was skipped (a game was running at pick time) needs a way to
    start it later too, and so does an approved exception.
    """
    pending = [(aid, n) for aid, n in candidates if not is_game_fully_installed(aid)]
    if not pending:
        _echo("All allowed games are already installed.")
        return None
    if len(pending) == 1:
        return pending[0]
    options = [PromptOption(str(aid), name or f"AppID={aid}") for aid, name in pending]
    picked = int(current_prompter().choice("Install which game", options))
    return next(game for game in pending if game[0] == picked)


def cmd_install(
    config: Config,
    state: State,
    *,
    target: str | None = None,
    dry_run: bool = False,
    valve_proton: bool = False,
) -> dict[str, object] | None:
    """Install an allowed game, through the fast installer when it can be used.

    A download Steam already started is taken over, so this is also how a
    fast install that was skipped earlier gets started. *target* (AppID, URL
    or name) must be a game allowed today; *dry_run* only reports what the
    installer would do.

    Returns:
        ``{app_id, dry_run, fast_install_skipped}`` once a game was chosen,
        else ``None``.

    Raises:
        JobError: ``locked`` for a target that is not allowed today.
    """
    candidates = install_candidates(config, state)
    if not candidates:
        _echo("No game currently assigned. Run 'scan' first.")
        return None
    if target:
        chosen: tuple[int, str] | None = resolve_target(target, candidates)
    else:
        chosen = _pick_install_target(candidates)
    if chosen is None:
        return None
    app_id, name = chosen
    result: dict[str, object] = {
        "app_id": app_id,
        "dry_run": dry_run,
        "fast_install_skipped": None,
    }
    if dry_run:
        current_progress().phase(f"Dry run of {name or app_id}")
        dry_run_install(app_id, name, valve_proton=valve_proton)
        return result
    # The installer closes Steam: with a game running the fast path is
    # refused (Steam's own download starts instead), and the UI says why.
    if game_is_running():
        result["fast_install_skipped"] = "game_running"

    _echo(f"Installing {name} (AppID={app_id})...")
    # install_game only *starts* the download (fast installer or steam://);
    # there is no download-progress loop to report on yet.
    current_progress().phase(f"Starting install of {name}")
    if not install_game(
        app_id,
        name,
        config.steam_id,
        use_steam_protocol=True,
        valve_proton=valve_proton,
    ):
        _echo("Failed to start the install.")
    elif fast_install_failure(app_id) is None:
        _echo("Done!")
    else:
        # The fast install already printed its "Failed: ..." line.
        _echo("Steam's own download was started instead.")
    return result


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
    # Same contract as cmd_hide: no reachable Steam means nothing to change
    # this time, not a failed command.
    try:
        count = unhide_all_games(owned_ids)
    except SteamUnavailableError as exc:
        _echo(f"Library unhiding: skipped ({exc})")
        return
    _echo(f"Unhidden {count} games.")

    if count > 0:
        _echo("Done!")
