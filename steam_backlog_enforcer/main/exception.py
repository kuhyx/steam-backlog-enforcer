"""``add-exception``: request a whitelist exception for one game.

Split out of :mod:`steam_backlog_enforcer.main.misc` when the command gained
its typed-phrase confirmation, to keep both files under the 250-line cap.
"""

from __future__ import annotations

import sys

from steam_backlog_enforcer._prompter import confirm_phrase
from steam_backlog_enforcer._snapshot import snapshot_game_name
from steam_backlog_enforcer._whitelist import validate_reason
from steam_backlog_enforcer._whitelist_locking import add_pending_exception
from steam_backlog_enforcer.game_install import _echo

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


def cmd_add_exception(args: list[str]) -> None:
    """Add a whitelist exception, active immediately.

    Usage: add-exception <app_id> --reason "<text>"

    The exception becomes active right away (no cooldown).  The reason must be
    a genuine justification of at least 5 words with sufficient entropy, and
    the ``add-exception`` friction phrase must be typed to confirm.

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

    game_name = snapshot_game_name(app_id) or f"AppID={app_id}"
    if not confirm_phrase(
        "add-exception",
        f"Request a whitelist exception for {game_name}?",
        game_name=game_name,
    ):
        _echo("Aborted.")
        sys.exit(1)

    try:
        msg = add_pending_exception(app_id, reason)
    except ValueError as exc:
        _echo(f"Error: {exc}")
        sys.exit(1)

    _echo(msg)
