"""Abandonment and the status payload for manual picks.

Split out of :mod:`steam_backlog_enforcer._actions` to keep both files
under the 250-line cap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer._actions import (
    find_manual_pick,
    is_manual_pick_locked,
)
from steam_backlog_enforcer._allowed_games import (
    active_manual_picks,
    allowed_games,
)
from steam_backlog_enforcer._total_block import get_total_block_status
from steam_backlog_enforcer.game_install import get_installed_games, is_protected_app
from steam_backlog_enforcer.store_blocker import is_store_blocked

# Marks these two as an intentional re-export (they're imported from
# _allowed_games above, not defined here) -- without this, mypy's
# --no-implicit-reexport flags every downstream `from _actions import
# active_manual_picks` as an error. Everything else in this file is
# accessible normally; this only needs to list names imported-then-reexported.
__all__ = [
    "active_manual_picks",
    "allowed_games",
]

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State

# How long an abandoned pick stays out of the auto-assignment pool, so that
# ``scan`` does not immediately hand back the game the user just rejected.
ABANDON_COOLDOWN_DAYS = 30


def manual_pick_age_days(state: State, app_id: int) -> float | None:
    """Return how many days ago *app_id* was picked, or ``None``.

    Informational only — picks can be abandoned at any age. ``None`` means the
    question does not apply: *app_id* is not an active manual pick, or its
    timestamp is missing/malformed.

    Args:
        state: The loaded enforcer state.
        app_id: The manually-picked app id to measure.

    Returns:
        Fractional days elapsed since the pick was made, or ``None`` when the
        question does not apply.
    """
    pick = find_manual_pick(state, app_id)
    if pick is None or not pick.get("started_at"):
        return None
    try:
        started = datetime.fromisoformat(pick["started_at"])
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - started).total_seconds() / 86400


def abandon_manual_pick(state: State, app_id: int) -> bool:
    """Drop one manual pick and persist ``state``.

    A pick may be abandoned at any time, however long ago it was made.

    Only the named pick is dropped: any other active pick keeps its own lock
    and deadline. The abandoned app id goes onto the existing skip cooldown so
    ``scan`` will not hand the same game straight back. State-only: like
    ``apply_manual_pick`` this performs no uninstall/hide cascade, so the MCP
    server can call it without touching the filesystem.

    Args:
        state: The enforcer state to mutate and save.
        app_id: The manually-picked app id to back out of.

    Returns:
        ``True`` if the pick was abandoned, ``False`` if it is not an active
        pick, in which case ``state`` is untouched.
    """
    if find_manual_pick(state, app_id) is None:
        return False

    state.skip_for_days(app_id, ABANDON_COOLDOWN_DAYS)
    state.manual_picks = [
        p for p in active_manual_picks(state) if p.get("app_id") != app_id
    ]

    # The abandoned pick may also have been the current assignment; hand the
    # assignment to a surviving pick so the enforcer keeps guarding it, or
    # clear it so 'scan' can reassign.
    if state.current_app_id == app_id:
        survivor = state.manual_picks[-1] if state.manual_picks else None
        state.current_app_id = survivor["app_id"] if survivor else None
        state.current_game_name = survivor["game_name"] if survivor else ""

    state.save()
    return True


def status_payload(state: State) -> dict[str, Any]:
    """Build the structured status snapshot that ``cmd_status`` renders as text.

    Pure data, no stdout — safe for the MCP server. Reads only ``State`` and the
    stdout-free leaf helpers; never constructs ``Config`` and never exposes the
    Steam API key.

    Args:
        state: The loaded enforcer state.

    Returns:
        A JSON-ready dict describing the current enforcement status.
    """
    total_block = get_total_block_status()
    installed = get_installed_games()
    real_games = [(aid, name) for aid, name in installed if not is_protected_app(aid)]
    assigned_installed = (
        any(aid == state.current_app_id for aid, _ in installed)
        if state.current_app_id
        else None
    )
    return {
        "current_app_id": state.current_app_id,
        "current_game_name": state.current_game_name or None,
        "finished_count": len(state.finished_app_ids),
        "store_blocked": is_store_blocked(),
        "installed_count": len(real_games),
        "assigned_game_installed": assigned_installed,
        "total_block": {
            "active": total_block.active,
            "days_remaining": round(total_block.days_remaining, 1),
            "until": total_block.until.isoformat() if total_block.until else None,
        },
        "manual_pick_locked": is_manual_pick_locked(state),
        "manual_picks": [
            {
                **pick,
                "age_days": manual_pick_age_days(state, pick["app_id"]),
            }
            for pick in active_manual_picks(state)
        ],
    }
