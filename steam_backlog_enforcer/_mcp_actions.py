"""Mutating MCP tools: manual picks, abandonment and gaming blocks.

Every tool here takes an explicit ``confirm`` flag, so a model cannot change
enforcement state on a single unconfirmed call. The read-only half lives in
:mod:`steam_backlog_enforcer._mcp_query`.
"""

from __future__ import annotations

from typing import Any

from steam_backlog_enforcer._actions import (
    ABANDON_COOLDOWN_DAYS,
    abandon_manual_pick,
    active_manual_picks,
    apply_manual_pick,
    find_manual_pick,
    manual_pick_age_days,
)
from steam_backlog_enforcer._allowed_games import MANUAL_LOCK_DAYS
from steam_backlog_enforcer._mcp_server import (
    _resolve_game_name,
    logger,
    mcp,
)
from steam_backlog_enforcer._pick_completion import (
    retire_completed_manual_picks,
)
from steam_backlog_enforcer._total_block import start_total_block
from steam_backlog_enforcer.config import Config, State


@mcp.tool()
def pick_manual(app_id: int, *, confirm: bool = False) -> dict[str, Any]:
    """Lock the enforcer to a game by Steam app_id (gated write).

    With ``confirm=False`` (the default) this performs **no** mutation and
    returns a preview of what confirming would do. Call again with
    ``confirm=True`` to apply. Applying overrides the current assignment and
    locks all other commands for ``MANUAL_LOCK_DAYS`` days (or until 100%
    achievements). Unlike the CLI's ``pick-manual``, this mutates **state only**
    — it never uninstalls, installs, or hides games.

    Args:
        app_id: The Steam app id to lock in (must exist in the last snapshot).
        confirm: Set ``True`` to actually apply the pick; otherwise preview.
    """
    game_name = _resolve_game_name(app_id)
    if game_name is None:
        return {
            "ok": False,
            "reason": f"AppID={app_id} not found in the snapshot. Run 'scan' first.",
        }
    if not confirm:
        return {
            "ok": True,
            "preview": True,
            "action": "pick_manual",
            "app_id": app_id,
            "game_name": game_name,
            "effect": (
                "Overrides the current assignment and locks all other commands "
                f"for {MANUAL_LOCK_DAYS} days or until 100% achievements."
            ),
            "confirm_required": True,
        }
    config = Config.load()
    state = State.load()
    # Free the slots of picks already at 100%, so the cap below cannot refuse
    # on behalf of a game that is finished. Matches the CLI's pick-manual.
    retired = retire_completed_manual_picks(config, state)
    refused = apply_manual_pick(
        state,
        app_id,
        game_name,
        max_picks=config.max_manual_picks,
    )
    if refused is not None:
        return {"ok": False, "reason": refused}
    logger.info("pick_manual applied: %s (AppID=%s)", game_name, app_id)
    return {
        "ok": True,
        "applied": True,
        "action": "pick_manual",
        "app_id": app_id,
        "game_name": game_name,
        "retired_completed": [
            {"app_id": r.app_id, "game_name": r.game_name} for r in retired if r.retired
        ],
    }


@mcp.tool()
def abandon_pick(app_id: int, *, confirm: bool = False) -> dict[str, Any]:
    """Undo a manual pick (gated write).

    With ``confirm=False`` (the default) this performs **no** mutation and
    returns a preview. A pick can be abandoned at any time, however long ago
    it was made. Like ``pick_manual``, this mutates **state only** — the CLI's
    ``abandon-pick`` additionally uninstalls the abandoned game.

    Args:
        app_id: The manually-picked app id to back out of.
        confirm: Set ``True`` to actually abandon the pick; otherwise preview.
    """
    state = State.load()
    picks = active_manual_picks(state)
    if not picks:
        return {"ok": False, "reason": "No manual pick is active."}

    pick = find_manual_pick(state, app_id)
    if pick is None:
        listed = ", ".join(f"AppID={p['app_id']}" for p in picks)
        return {
            "ok": False,
            "reason": (
                f"AppID={app_id} is not one of the active manual picks ({listed})."
            ),
        }

    age = manual_pick_age_days(state, app_id)

    game_name = str(pick["game_name"])
    if not confirm:
        return {
            "ok": True,
            "preview": True,
            "action": "abandon_pick",
            "app_id": app_id,
            "game_name": game_name,
            "age_days": age,
            "effect": (
                "Releases the manual pick lock, clears the assignment, and "
                f"keeps the game out of auto-assignment for "
                f"{ABANDON_COOLDOWN_DAYS} days."
            ),
            "confirm_required": True,
        }

    abandon_manual_pick(state, app_id)
    logger.info("abandon_pick applied: %s (AppID=%s)", game_name, app_id)
    return {
        "ok": True,
        "applied": True,
        "action": "abandon_pick",
        "app_id": app_id,
        "game_name": game_name,
    }


@mcp.tool()
def block_gaming(days: int, *, confirm: bool = False) -> dict[str, Any]:
    """Start a total gaming block for ``days`` days (gated, privileged write).

    With ``confirm=False`` (the default) returns a preview only. With
    ``confirm=True`` it attempts the block, which **requires root** (it edits
    ``/etc/hosts`` and uninstalls Steam). The MCP server runs unprivileged, so
    this will normally return ``{"ok": false, "reason": "requires elevated
    privileges"}`` rather than succeeding. There is no in-app undo.

    Args:
        days: Whole number of days to block all gaming (must be >= 1).
        confirm: Set ``True`` to attempt the block; otherwise preview.
    """
    if days < 1:
        return {"ok": False, "reason": "days must be at least 1."}
    if not confirm:
        return {
            "ok": True,
            "preview": True,
            "action": "block_gaming",
            "days": days,
            "effect": (
                f"For {days} day(s): uninstalls Steam, kills game launchers, and "
                "blocks Steam + game-website domains. There is NO in-app undo."
            ),
            "requires_root": True,
            "confirm_required": True,
        }
    try:
        applied = start_total_block(days)
    except (OSError, RuntimeError) as exc:  # never crash the server on a write
        logger.warning("block_gaming failed: %s", exc)
        return {"ok": False, "reason": "requires elevated privileges"}
    if not applied:
        return {"ok": False, "reason": "requires elevated privileges"}
    logger.info("block_gaming applied: %d day(s)", days)
    return {"ok": True, "applied": True, "action": "block_gaming", "days": days}
