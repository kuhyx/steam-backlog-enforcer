"""Stdout-free, state-only core operations shared by the CLI and MCP server.

Every function here is safe to call from a stdio MCP server, where STDOUT
carries the JSON-RPC protocol and any stray write corrupts the stream. That
means: no ``print``/``_echo``/``sys.stdout`` writes, no ``input()``, and no
``sys.exit()``. The interactive CLI (``main.py``) reuses these same functions so
there is a single tested implementation of the underlying behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer._total_block import get_total_block_status
from steam_backlog_enforcer.game_install import get_installed_games, is_protected_app
from steam_backlog_enforcer.store_blocker import is_store_blocked

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State

# Days before the manual-pick lock automatically expires. Single source of
# truth: both ``main.py`` and the MCP server import it from here.
MANUAL_LOCK_DAYS = 14


def is_manual_pick_locked(state: State) -> bool:
    """Return ``True`` if the manual-pick lock is currently in force.

    The lock releases once the picked game reaches ``finished_app_ids`` or once
    ``MANUAL_LOCK_DAYS`` have elapsed since the pick timestamp.

    Args:
        state: The loaded enforcer state.

    Returns:
        Whether the manual-pick lock is active right now.
    """
    if state.manual_pick_app_id is None:
        return False

    # Lock released once the game appears in finished_app_ids.
    if state.manual_pick_app_id in state.finished_app_ids:
        return False

    # Lock released after MANUAL_LOCK_DAYS days from the pick timestamp.
    if state.manual_pick_started_at:
        try:
            started = datetime.fromisoformat(state.manual_pick_started_at)
            deadline = started + timedelta(days=MANUAL_LOCK_DAYS)
            if datetime.now(timezone.utc) >= deadline:
                return False
        except ValueError:
            pass

    return True


def apply_manual_pick(state: State, app_id: int, game_name: str) -> None:
    """Assign *app_id* as the manually-picked game and persist ``state``.

    This is the non-interactive, side-effect-scoped core of the CLI's
    ``pick-manual`` command. It mutates and saves ``State`` only; it deliberately
    does **not** run the destructive post-assignment cascade (uninstalling other
    games, installing the pick, hiding the library) that the CLI performs after
    its interactive ``YES`` confirmation. Keeping this state-only means an
    automated caller (the MCP server) can never wipe installed games.

    Args:
        state: The enforcer state to mutate and save.
        app_id: The Steam app id to lock in.
        game_name: Human-readable name for the picked game.
    """
    now = datetime.now(timezone.utc).isoformat()
    state.manual_pick_app_id = app_id
    state.manual_pick_game_name = game_name
    state.manual_pick_started_at = now
    state.current_app_id = app_id
    state.current_game_name = game_name
    if not state.enforcement_started_at:
        state.enforcement_started_at = now
    state.save()


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
    }
