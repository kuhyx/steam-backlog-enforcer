"""The lock gate every command passes before it runs, CLI or web job.

One gate, so a command refused at the terminal is refused in the browser
too. The rules themselves live in :mod:`steam_backlog_enforcer._command_gate`
(:func:`~steam_backlog_enforcer._command_gate.lock_reason`); this module is
the CLI's printing, exiting half of it.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from steam_backlog_enforcer._command_gate import NOT_CONFIGURED_MSG, UNCONFIGURED_OK
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.main._shared import (
    _enforce_manual_pick_lock,
    _enforce_total_block_lock,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config


def enforce_gate(command: str, config: Config) -> State:
    """Run the gate the CLI way: print the lock message and exit on refusal.

    The web job runner calls this too, under its output sink, so the very
    same lock banner reaches the UI as log lines.

    Args:
        command: Canonical command name (never raw argv).
        config: Loaded configuration.

    Returns:
        The loaded state, once every check passed.
    """
    if command not in UNCONFIGURED_OK and not config.steam_api_key:
        _echo(NOT_CONFIGURED_MSG)
        sys.exit(1)

    state = State.load()

    # Total block is the most restrictive lock - check it first.
    _enforce_total_block_lock(command)

    # Enforce the manual-pick lock before dispatching any command.
    # This also covers add-exception (previously dispatched before state load).
    _enforce_manual_pick_lock(command, state)
    return state
