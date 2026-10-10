"""Per-pass guards of the enforce loop: who may stay installed, and who is named.

Split out of :mod:`steam_backlog_enforcer._enforce_loop` to keep it under the
250-line cap once it also had to drive the control socket.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import allowed_games
from steam_backlog_enforcer.enforcer import send_notification
from steam_backlog_enforcer.game_uninstall import (
    get_installed_games,
    is_protected_app,
    uninstall_game,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State

logger = logging.getLogger(__name__)


def allowed_names(state: State) -> str:
    """Return a human-readable list of the games the user may play.

    Args:
        state: Current enforcer state.

    Returns:
        Comma-separated game names, or "your assigned game" when none is set.
    """
    names = [name for _, name in allowed_games(state) if name]
    return ", ".join(names) if names else "your assigned game"


def guard_installed_games(allowed: set[int]) -> int:
    """Remove any unauthorized game manifests + files.  Runs every loop.

    Args:
        allowed: Every app id that may stay installed — the assignment plus
            any concurrent manual picks.

    Returns number of games removed this pass.
    """
    if not allowed:
        return 0
    installed = get_installed_games()
    count = 0
    for app_id, name in installed:
        if app_id in allowed:
            continue
        if is_protected_app(app_id):
            continue

        logger.warning(
            "Unauthorized game detected — removing: %s (AppID=%d)", name, app_id
        )
        if uninstall_game(app_id, name):
            count += 1
            send_notification(
                "Game Removed!",
                f"Uninstalled {name} (AppID={app_id}). "
                f"Only your assigned game(s) are allowed.",
            )
    return count
