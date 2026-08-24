"""``abandon-pick``: back out of a manual pick."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import (
    ABANDON_COOLDOWN_DAYS as _ABANDON_COOLDOWN_DAYS,
)
from steam_backlog_enforcer._actions import (
    abandon_manual_pick,
    active_manual_picks,
    find_manual_pick,
)
from steam_backlog_enforcer.game_install import (
    _echo,
    is_game_installed,
    uninstall_game,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

_ABANDON_PICK_USAGE = (
    "Usage: abandon-pick <app_id>\n"
    "  app_id : the manually-picked game you want to back out of.\n\n"
    "A pick can be abandoned at any time, however long ago it was made."
)


def _abandon_pick_target(state: State, args: list[str]) -> int | None:
    """Validate the abandon-pick argument against the active manual pick.

    Requiring the explicit app_id (rather than defaulting to the current pick)
    makes an accidental abandon impossible to trigger by muscle memory.

    Args:
        state: Current enforcer state.
        args: Remaining CLI args (first element should be the app_id).

    Returns:
        The validated app id, or ``None`` if the input was unusable (a message
        has already been printed in that case).
    """
    if not args:
        _echo(_ABANDON_PICK_USAGE)
        return None

    try:
        app_id = int(args[0])
    except ValueError:
        _echo(f"Error: app_id must be a number, got '{args[0]}'.")
        return None

    picks = active_manual_picks(state)
    if not picks:
        _echo("No manual pick is active — nothing to abandon.")
        return None

    if find_manual_pick(state, app_id) is None:
        listed = ", ".join(f"{p['game_name']} (AppID={p['app_id']})" for p in picks)
        _echo(
            f"Error: AppID={app_id} is not one of your manual picks.\nActive: {listed}."
        )
        return None

    return app_id


def cmd_abandon_pick(_config: Config, state: State, args: list[str]) -> None:
    """Back out of a manual pick, whatever its age.

    Args:
        _config: Enforcer configuration (unused, kept for dispatch symmetry).
        state: Current enforcer state.
        args: Remaining CLI args (first element should be the app_id).
    """
    app_id = _abandon_pick_target(state, args)
    if app_id is None:
        sys.exit(1)

    pick = find_manual_pick(state, app_id)
    game_name = str(pick["game_name"]) if pick else ""

    others = [p for p in active_manual_picks(state) if p["app_id"] != app_id]
    _echo(f"\nAbandoning manual pick: {game_name} (AppID={app_id})")
    _echo(
        f"\nThis will:"
        f"\n  - Drop this pick from your allowed games"
        f"\n  - Uninstall {game_name}"
        f"\n  - Keep it out of auto-assignment for"
        f" {_ABANDON_COOLDOWN_DAYS} days"
    )
    if others:
        kept = ", ".join(f"{p['game_name']} (AppID={p['app_id']})" for p in others)
        _echo(f"\n  Your other pick(s) stay locked in: {kept}")
    else:
        _echo("\n  - Leaves you with no assigned game (run 'scan' to get one)")
    _echo()
    confirm = input(f"Type YES to abandon {game_name}: ").strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    abandon_manual_pick(state, app_id)

    _echo(f"\nManual pick abandoned: {game_name}")

    if is_game_installed(app_id):
        _echo(f"  Uninstalling {game_name}...")
        if uninstall_game(app_id, game_name):
            _echo("  Uninstalled.")
        else:
            _echo("  Warning: could not uninstall — remove it from Steam manually.")

    if state.current_app_id is None:
        _echo("\nNo game is assigned now. Run 'scan' to get a new assignment,")
        _echo("or 'pick-manual <app_id>' to choose one yourself.\n")
    else:
        _echo(f"\nStill assigned: {state.current_game_name}\n")
