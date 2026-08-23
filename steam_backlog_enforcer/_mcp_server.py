"""MCP (Model Context Protocol) server for Steam Backlog Enforcer.

Exposes the enforcer's read surface and two *gated* write actions as typed MCP
tools, so an MCP client (Claude Code and its subagents) can query and — with
explicit confirmation — drive the backlog without shelling out to the CLI.

Run via the dedicated venv that has the ``mcp`` extra installed::

    ~/.venvs/steam-backlog-mcp/bin/python -m steam_backlog_enforcer._mcp

(see ``scripts/setup_mcp.sh`` and the repo-root ``.mcp.json``).

Safety invariants (do not break when adding tools):
  * **stdout is the JSON-RPC channel.** This module and every function a tool
    calls must never write to stdout. All logging is routed to STDERR below, and
    tools call only stdout-free leaf helpers (never the ``cmd_*`` handlers, which
    ``_echo`` to stdout / ``input()`` / ``sys.exit()``).
  * **No secret ever leaves.** There is no tool that returns ``Config`` or reads
    ``config.json``; read tools load only ``State`` and the secrets-free web
    dataset. Game-name lookups use the on-disk snapshot only (no Steam API key).
  * **Writes are gated.** Every write tool defaults to a dry-run preview and
    mutates only when ``confirm=True``. These write tools must never be added to
    a permission allowlist (a subagent could then bypass the human).
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from steam_backlog_enforcer.config import load_snapshot

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo

# Log to STDERR only — STDOUT carries the MCP JSON-RPC protocol frames, so a
# single stray stdout write would corrupt the stream and kill the session.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] steam-mcp: %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("steam-backlog-enforcer")

_DEFAULT_LIST_LIMIT = 50


def _resolve_game_name(app_id: int) -> str | None:
    """Resolve a game name from the on-disk snapshot only (no Config / API).

    Deliberately snapshot-only: it never constructs ``Config`` and never touches
    the Steam API key, so it is safe to call from an MCP tool. A game absent from
    the last snapshot simply resolves to ``None``.

    Args:
        app_id: The Steam app id to look up.

    Returns:
        The game name, or ``None`` if not present in the snapshot.
    """
    snapshot = load_snapshot()
    if snapshot:
        for entry in snapshot:
            if entry.get("app_id") == app_id:
                return str(entry["name"])
    return None


def _backlog_sort_key(game: GameInfo) -> tuple[int, float]:
    """Sort incomplete games shortest-completionist-first, unknowns last."""
    if game.completionist_hours > 0:
        return (0, game.completionist_hours)
    return (1, 0.0)


# ──────────────────────────────────────────────────────────────
# Read tools (State-only; never expose Config / the Steam API key)
# ──────────────────────────────────────────────────────────────
