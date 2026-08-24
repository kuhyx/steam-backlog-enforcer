"""User-facing CLI output.

A one-function leaf module so every command can print without importing the
install machinery. Split out of :mod:`steam_backlog_enforcer.game_install` to
keep that module under the 250-line cap.
"""

from __future__ import annotations

import sys


def _echo(msg: str = "", *, end: str = "\n", flush: bool = False) -> None:
    """Write user-facing CLI output to stdout.

    Args:
        msg: Text to output.
        end: String appended after the message.
        flush: Whether to flush stdout immediately.
    """
    sys.stdout.write(msg + end)
    if flush:
        sys.stdout.flush()


# Steam infrastructure app IDs that should NEVER be uninstalled.
