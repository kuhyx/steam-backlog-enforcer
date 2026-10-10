"""Commands that do not belong to a larger group.

Store blocking, state reset, setup, the web UI and the total gaming block.
``add-exception`` lives in :mod:`steam_backlog_enforcer.main.exception`.
"""

from __future__ import annotations

import errno
import sys
from typing import TYPE_CHECKING

from steam_backlog_enforcer._backups import create_backup
from steam_backlog_enforcer._config_setup import interactive_setup
from steam_backlog_enforcer._enforce_loop import get_all_owned_app_ids
from steam_backlog_enforcer._prompter import confirm_phrase
from steam_backlog_enforcer._serve_startup import (
    ensure_port_available,
    parse_serve_args,
)
from steam_backlog_enforcer._store_window import (
    DEFAULT_WINDOW_MINUTES,
    MAX_WINDOW_MINUTES,
    open_store_window,
)
from steam_backlog_enforcer._total_block import start_total_block
from steam_backlog_enforcer._web_build import build_frontend, frontend_is_stale
from steam_backlog_enforcer._web_server import serve
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.library_hider import unhide_all_games

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

_BLOCK_GAMING_USAGE = (
    "Usage: block-gaming <days>\n"
    "  days : whole number of days to block ALL gaming:\n"
    "         Steam uninstalled, all known game/launcher processes killed,\n"
    "         Steam + game-website domains blocked.\n\n"
    "There is NO in-app command to undo this early once confirmed."
)


def cmd_unblock(_config: Config, state: State, args: list[str] | None = None) -> None:
    """Open a timed store window: unblocked now, re-blocked by the daemon after.

    Usage: unblock [minutes]   (default 15, max 30)

    Args:
        _config: Unused; kept for the shared command signature.
        state: Enforcer state; receives the window deadline.
        args: CLI argument list after the command name.
    """
    raw = args[0] if args else str(DEFAULT_WINDOW_MINUTES)
    try:
        until = open_store_window(state, int(raw))
    except ValueError as exc:
        _echo(f"Usage: unblock [minutes]  (1-{MAX_WINDOW_MINUTES}): {exc}")
        sys.exit(1)
    except RuntimeError as exc:
        _echo(f"Failed to unblock: {exc}")
        sys.exit(1)
    local = until.astimezone().strftime("%H:%M")
    _echo(f"Steam store UNBLOCKED until {local}.")
    _echo("The enforcer daemon keeps it open until then (even if a hosts")
    _echo("reinstall re-blocks it) and re-blocks it afterwards.")


def cmd_buy_dlc(config: Config, state: State) -> None:
    """Open the default-length store window to buy a game or DLC."""
    cmd_unblock(config, state, [])


def cmd_reset(config: Config, state: State) -> None:
    """Reset all state (unhide, clear assignment), backed up first.

    The store block is deliberately left alone. The daemon only re-blocks the
    store at startup or when a timed window ends, so lifting it here would be
    an open-ended window that skips ``unblock``'s 1-30 minute cap and phrase.

    Args:
        config: Loaded configuration.
        state: State to wipe.
    """
    if not confirm_phrase("reset", "Wipe all enforcer state?"):
        _echo("Aborted.")
        return
    backup = create_backup("before reset")
    if backup is not None:
        _echo(f"State backed up as {backup.id}.")

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
    state.manual_pick_app_id = None
    state.manual_pick_game_name = ""
    state.manual_pick_started_at = ""
    state.manual_picks = []
    state.current_assigned_at = ""
    state.last_assigned_at = {}
    state.released_at = {}
    state.save()
    _echo("State reset. Store left blocked: open a timed window with 'unblock'.")


def cmd_setup(_config: Config, _state: State) -> None:
    """Run interactive setup."""
    interactive_setup()


def cmd_serve(args: list[str]) -> None:
    """Start the interactive web UI server (read-only, localhost only).

    Re-running this is safe rather than fatal: an already-running server on
    current code is reported, one on outdated code is replaced, and a stale
    frontend bundle is rebuilt before anything is served.

    Args:
        args: CLI argument list after the command name.
    """
    host, port = parse_serve_args(args)
    # Build BEFORE touching the port. A failed build must not cost you the
    # server that was already running, and rebuilding first is what lets the
    # "already running" path hand the browser a fresh bundle on its next
    # request - _web_server reads web/dist per request, not at startup.
    if frontend_is_stale() and not build_frontend():
        sys.exit(1)
    ensure_port_available(host, port)
    try:
        serve(host, port)
    except OSError as exc:
        # Last-ditch cover for the gap between the /proc check and the bind.
        if exc.errno != errno.EADDRINUSE:
            raise
        _echo(f"Port {port} was taken while starting up. Try again.")
        sys.exit(1)


def cmd_block_gaming(args: list[str]) -> None:
    """Start a total gaming block for a fixed number of days.

    Usage: block-gaming <days>

    Args:
        args: Remaining CLI args (first element should be the day count).
    """
    if not args:
        _echo(_BLOCK_GAMING_USAGE)
        sys.exit(1)

    try:
        days = int(args[0])
    except ValueError:
        _echo(f"Error: days must be a whole number, got '{args[0]}'.")
        sys.exit(1)

    if days < 1:
        _echo("Error: days must be at least 1.")
        sys.exit(1)

    _echo(
        f"\nWARNING: This will, for the next {days} day(s):"
        f"\n  - Uninstall Steam"
        f"\n  - Kill Steam and all known game-launcher processes on sight"
        f"\n  - Block all Steam network domains AND known browser/flash"
        f"\n    game websites"
        f"\n\nThere is NO in-app command to undo this early. It can only be"
        f"\nlifted by waiting out the {days} day(s), or by manual root-level"
        f"\nsystem administration outside this tool."
    )
    _echo()
    if not confirm_phrase(
        "block-gaming", f"Block all gaming for {days} day(s)?", days=days
    ):
        _echo("Aborted.")
        return

    _echo("\nStarting total gaming block...")
    if start_total_block(days):
        _echo(f"Total gaming block ACTIVE for {days} day(s).")
        _echo("Run 'status' to check remaining time.")
    else:
        _echo("Error: failed to engage the block (see logs). Run with sudo?")
        sys.exit(1)
