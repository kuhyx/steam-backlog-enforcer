"""MCP tools for the daily gaming-time budget.

Reading today's usage and resetting it are separated from the pick/block
tools because they operate on the playtime state, not on which game is
assigned.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import Any

from steam_backlog_enforcer._budget_view import build_budget_snapshot
from steam_backlog_enforcer._mcp_server import (
    logger,
    mcp,
)
from steam_backlog_enforcer._playtime import (
    PlaytimeState,
    gaming_day_key,
    save_state,
)
from steam_backlog_enforcer._playtime_block import release_block


@mcp.tool()
def get_gaming_time() -> dict[str, Any]:
    """Return today's gaming-budget usage and whether the cutoff has engaged.

    The gaming day starts at 06:00 local time, so a session played after
    midnight still counts against the day it began in. Reads on-disk state and
    the live mount table only — no network, no Steam API key, no config secrets.
    """
    snapshot = build_budget_snapshot(demo=False)
    rules = snapshot["rules"]
    today = snapshot["today"]
    masked = rules["masked_launchers"]

    if today is None:
        return {
            "ok": True,
            "recorded": False,
            "state_status": snapshot["state_status"],
            "budget_seconds": rules["budget_seconds"],
            "enforcement": rules["enforcement"],
            "masked_launchers": masked,
        }

    return {
        "ok": True,
        "recorded": True,
        "state_status": snapshot["state_status"],
        "gaming_day": today["gaming_day"],
        "day_starts_at": today["day_starts_at"],
        "seconds_used": today["seconds_used"],
        "budget_seconds": today["budget_seconds"],
        "seconds_remaining": today["seconds_remaining"],
        "next_warning_seconds": today["next_warning_seconds"],
        "blocked": today["blocked"],
        "enforcement": rules["enforcement"],
        "counts_launchers": rules["counts_launchers"],
        "masked_launchers": masked,
        # Which games make up seconds_used, largest first, with whatever the
        # focus probe could not attribute as a trailing "unattributed" slice.
        "games": today["games"],
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
        now = datetime.now(UTC).astimezone()
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
