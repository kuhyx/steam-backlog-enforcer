"""One-line descriptions of every CLI command, in help order.

The CLI's usage text and the web command catalog (``GET /api/commands``)
both read these. They live outside ``main`` so the catalog, which the web
server loads from inside ``main`` (``main`` → ``misc`` → ``_web_server``),
can import them at the top without a cycle.
"""

from __future__ import annotations

from typing import Final

from steam_backlog_enforcer._allowed_games import MANUAL_LOCK_DAYS

# Commands dispatched through ``main.COMMANDS`` (handler takes config, state).
COMMAND_DESCRIPTIONS: Final[dict[str, str]] = {
    "scan": "Scan library & assign a game",
    "check": "Check assigned game for a new achievement",
    "status": "Show current status",
    "list": "List games from snapshot",
    "install": "Install the assigned game",
    "hide": "Hide all non-assigned games in library",
    "unhide": "Unhide all games in library",
    "buy-dlc": "Unblock the store for 15 min to buy a game/DLC",
    "reset": "Reset all state",
    "installed": "List installed games",
    "uninstall": "Uninstall all non-assigned games",
    "setup": "Run first-time setup",
    "done": "Move on after a new achievement, pick next",
    "pick": "Manually pick your next game from candidates",
    "stats": "Show backlog completion-time estimates",
    "gaming-status": "Show today's gaming time and block state",
    "gaming-reset": "Reset today's gaming counter (root + phrase)",
}

# Commands with non-standard arg handling (shown in help but not in COMMANDS).
EXTRA_COMMAND_DESCRIPTIONS: Final[dict[str, str]] = {
    "add-exception": "Request 24h-locked whitelist exception (use --reason)",
    "unblock": "Unblock the store for [minutes] (default 15, max 30)",
    "serve": "Start the web UI (--port N; replaces a stale server)",
    "pick-manual": f"Pick a game by app_id, lock enforcer for {MANUAL_LOCK_DAYS} days",
    "abandon-pick": "Undo a manual pick at any time (needs app_id)",
    "block-gaming": "Block ALL gaming for <days> days, no in-app undo",
    "enforce": "Run enforcer: block, uninstall, kill, hide (--demo for a 60s budget)",
    "gaming-unblock": "Force-release playtime bind mounts (root; recovery hatch)",
}

ALL_COMMAND_DESCRIPTIONS: Final[dict[str, str]] = (
    COMMAND_DESCRIPTIONS | EXTRA_COMMAND_DESCRIPTIONS
)
