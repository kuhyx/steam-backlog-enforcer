"""MCP tools for the daily gaming-time budget.

Reading today's usage and resetting it are separated from the pick/block
tools because they operate on the playtime state, not on which game is
assigned.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from steam_backlog_enforcer._mcp_server import (
    logger,
    mcp,
)
from steam_backlog_enforcer._playtime import (
    PlaytimeState,
    gaming_day_key,
    load_state,
    rules_for,
    save_state,
)
from steam_backlog_enforcer._playtime_block import mounted_targets, release_block
from steam_backlog_enforcer.config import Config


@mcp.tool()
def get_gaming_time() -> dict[str, Any]:
    """Return today's gaming-budget usage and whether the cutoff has engaged.

    The gaming day starts at 06:00 local time, so a session played after
    midnight still counts against the day it began in. Reads on-disk state and
    the live mount table only — no network, no Steam API key, no config secrets.
    """
    config = Config.load()
    rules = rules_for(config, demo=False)
    stored = load_state(demo=False)
    masked = sorted(str(path) for path in mounted_targets())

    if stored is None:
        return {
            "ok": True,
            "recorded": False,
            "budget_seconds": rules.budget_seconds,
            "enforcement": rules.enforcement,
            "masked_launchers": masked,
        }

    return {
        "ok": True,
        "recorded": True,
        "gaming_day": stored.day_key,
        "day_starts_at": "06:00 local",
        "seconds_used": round(stored.seconds, 1),
        "budget_seconds": rules.budget_seconds,
        "seconds_remaining": round(max(0.0, rules.budget_seconds - stored.seconds), 1),
        "blocked": stored.is_blocked(),
        "enforcement": rules.enforcement,
        "counts_launchers": rules.count_launchers,
        "masked_launchers": masked,
    }


@mcp.tool()
def reset_gaming_time(*, confirm: bool = False) -> dict[str, Any]:
    """Reset today's gaming counter and lift the block (gated, privileged write).

    With ``confirm=False`` (the default) returns a preview and mutates nothing.
    With ``confirm=True`` it attempts the reset, which **requires root** (it
    releases bind mounts over ``/usr/bin/steam`` and friends). The MCP server
    runs unprivileged, so this will normally return ``{"ok": false, "reason":
    "requires elevated privileges"}`` rather than succeeding.

    Args:
        confirm: Set ``True`` to attempt the reset; otherwise preview.
    """
    if not confirm:
        return {
            "ok": True,
            "preview": True,
            "action": "reset_gaming_time",
            "effect": (
                "Zeroes today's gaming counter and unmasks every launcher "
                "binary, restoring a full daily budget immediately."
            ),
            "requires_root": True,
            "confirm_required": True,
        }
    if os.geteuid() != 0:
        return {"ok": False, "reason": "requires elevated privileges"}
    try:
        released = release_block()
        now = datetime.now(timezone.utc).astimezone()
        save_state(
            PlaytimeState(day_key=gaming_day_key(now), last_tick_at=now.timestamp()),
            demo=False,
        )
    except (OSError, ValueError) as exc:  # never crash the server on a write
        logger.warning("reset_gaming_time failed: %s", exc)
        return {"ok": False, "reason": "requires elevated privileges"}
    logger.info("reset_gaming_time applied; released %d mount(s)", len(released))
    return {
        "ok": True,
        "applied": True,
        "action": "reset_gaming_time",
        "released": [str(path) for path in released],
    }
