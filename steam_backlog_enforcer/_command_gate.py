"""Why a command may not run right now: the lock rules, side-effect free.

The pure half of the gate in :mod:`steam_backlog_enforcer.main._gate`: the
not-configured check, then the total gaming block, then the manual pick lock
— the order :func:`steam_backlog_enforcer.main.main` always used. It lives
outside ``main`` so the web server, which ``main`` itself loads (``main`` →
``misc`` → ``_web_server``), can ask it at import time without a cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._actions import is_manual_pick_locked
from steam_backlog_enforcer._allowed_games import active_manual_picks
from steam_backlog_enforcer._command_locks import (
    _MANUAL_LOCK_EXEMPT_COMMANDS,
    _TOTAL_BLOCK_EXEMPT_COMMANDS,
)
from steam_backlog_enforcer._total_block import (
    get_total_block_status,
    is_total_block_active,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

# Usable before an API key exists: setup creates one, add-exception never
# talks to Steam.
UNCONFIGURED_OK: Final = frozenset({"setup", "add-exception"})
NOT_CONFIGURED_MSG: Final = "Not configured. Run 'setup' first."


def lock_reason(command: str, config: Config, state: State | None) -> str | None:
    """Say why *command* may not run right now, without printing anything.

    Args:
        command: Canonical command name (never raw argv).
        config: Loaded configuration.
        state: Loaded state; ``None`` skips the manual-pick check, for callers
            that have no state yet.

    Returns:
        A one-line reason, or ``None`` when the command may run.
    """
    if command not in UNCONFIGURED_OK and not config.steam_api_key:
        return NOT_CONFIGURED_MSG
    if is_total_block_active() and command not in _TOTAL_BLOCK_EXEMPT_COMMANDS:
        days = get_total_block_status().days_remaining
        allowed = ", ".join(sorted(_TOTAL_BLOCK_EXEMPT_COMMANDS))
        return (
            f"Total gaming block active ({days:.1f} day(s) left). Allowed: {allowed}."
        )
    if (
        state is not None
        and is_manual_pick_locked(state)
        and command not in _MANUAL_LOCK_EXEMPT_COMMANDS
    ):
        names = ", ".join(str(p["game_name"]) for p in active_manual_picks(state))
        return (
            f"Manual pick lock active ({names}): earn a new achievement first. "
            f"Allowed: {', '.join(sorted(_MANUAL_LOCK_EXEMPT_COMMANDS))}."
        )
    return None
