"""Commands that do not belong to a larger group.

Store blocking, state reset, setup, whitelist exceptions, the web UI and the
total gaming block.
"""

from __future__ import annotations

import errno
import sys
from typing import TYPE_CHECKING

from steam_backlog_enforcer._config_setup import interactive_setup
from steam_backlog_enforcer._enforce_loop import get_all_owned_app_ids
from steam_backlog_enforcer._serve_startup import (
    ensure_port_available,
    parse_serve_args,
)
from steam_backlog_enforcer._total_block import start_total_block
from steam_backlog_enforcer._web_build import build_frontend, frontend_is_stale
from steam_backlog_enforcer._web_server import serve
from steam_backlog_enforcer._whitelist import (
    add_pending_exception,
    validate_reason,
)
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.library_hider import restart_steam, unhide_all_games
from steam_backlog_enforcer.store_blocker import block_store, unblock_store

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

_MIN_ADD_EXCEPTION_ARGS = 3
_ADD_EXCEPTION_USAGE = (
    'Usage: add-exception <app_id> --reason "<justification>"\n'
    "  app_id   : numeric Steam application ID\n"
    "  --reason : genuine justification (>= 5 words)\n\n"
    "Example:\n"
    "  add-exception 440 --reason "
    '"TF2 is needed for a community event this weekend"\n\n'
    "Exceptions become active immediately."
)

_BLOCK_GAMING_USAGE = (
    "Usage: block-gaming <days>\n"
    "  days : whole number of days to block ALL gaming:\n"
    "         Steam uninstalled, all known game/launcher processes killed,\n"
    "         Steam + game-website domains blocked.\n\n"
    "There is NO in-app command to undo this early once confirmed."
)


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
    state.manual_pick_app_id = None
    state.manual_pick_game_name = ""
    state.manual_pick_started_at = ""
    state.manual_picks = []
    state.save()
    _echo("State reset. Store unblocked.")


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


def cmd_add_exception(args: list[str]) -> None:
    """Add a whitelist exception, active immediately.

    Usage: add-exception <app_id> --reason "<text>"

    The exception becomes active right away (no cooldown).  The reason must be
    a genuine justification of at least 5 words with sufficient entropy.

    Args:
        args: CLI argument list after the command name.
    """
    if len(args) < _MIN_ADD_EXCEPTION_ARGS or "--reason" not in args:
        _echo(_ADD_EXCEPTION_USAGE)
        sys.exit(1)

    try:
        app_id = int(args[0])
    except ValueError:
        _echo(f"Error: app_id must be a number, got '{args[0]}'.")
        sys.exit(1)

    reason_idx = args.index("--reason")
    reason_parts = args[reason_idx + 1 :]
    if not reason_parts:
        _echo("Error: --reason requires a value.")
        sys.exit(1)
    reason = " ".join(reason_parts)

    # Show validation feedback before attempting to add.
    err = validate_reason(reason)
    if err is not None:
        _echo(f"Invalid reason: {err}")
        sys.exit(1)

    try:
        msg = add_pending_exception(app_id, reason)
    except ValueError as exc:
        _echo(f"Error: {exc}")
        sys.exit(1)

    _echo(msg)


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
    confirm = input(f"Type YES to confirm a {days}-day total gaming block: ").strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    _echo("\nStarting total gaming block...")
    if start_total_block(days):
        _echo(f"Total gaming block ACTIVE for {days} day(s).")
        _echo("Run 'status' to check remaining time.")
    else:
        _echo("Error: failed to engage the block (see logs). Run with sudo?")
        sys.exit(1)
