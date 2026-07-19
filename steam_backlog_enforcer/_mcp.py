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
from typing import Any

from mcp.server.fastmcp import FastMCP

from steam_backlog_enforcer._actions import (
    ABANDON_COOLDOWN_DAYS,
    MANUAL_GRACE_DAYS,
    MANUAL_LOCK_DAYS,
    abandon_manual_pick,
    active_manual_picks,
    apply_manual_pick,
    can_abandon_manual_pick,
    find_manual_pick,
    manual_pick_grace_remaining,
    status_payload,
)
from steam_backlog_enforcer._total_block import start_total_block
from steam_backlog_enforcer._web_dataset import build_web_dataset, dataset_to_payload
from steam_backlog_enforcer.config import Config, State, load_snapshot
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


@mcp.tool()
def get_dataset() -> dict[str, Any]:
    """Return the full, secrets-free backlog dataset.

    Includes every incomplete candidate game with HowLongToBeat times,
    ProtonDB tiers, pace-vs-HLTB calibration, and the default CLI thresholds —
    the same projection the local web UI consumes. Reads on-disk caches only
    (no network, no Steam API key).
    """
    return dataset_to_payload(build_web_dataset(State.load()))


@mcp.tool()
def get_status() -> dict[str, Any]:
    """Return the current enforcer status.

    Reports the assigned game, finished count, whether the Steam store is
    blocked, installed-game count, any active total block (with days remaining),
    and whether a manual-pick lock is in force.
    """
    return status_payload(State.load())


@mcp.tool()
def get_stats() -> dict[str, Any]:
    """Return backlog completion-time estimates.

    A focused subset of the dataset: the default qualifying-games summary
    (rush / leisure / worst-case totals) and the player's measured pace versus
    HowLongToBeat.
    """
    payload = dataset_to_payload(build_web_dataset(State.load()))
    return {
        "default_summary": payload["default_summary"],
        "pace_vs_hltb": payload["pace_vs_hltb"],
    }


@mcp.tool()
def list_backlog(limit: int = _DEFAULT_LIST_LIMIT) -> dict[str, Any]:
    """List incomplete games, shortest-completionist-first, capped at ``limit``.

    Args:
        limit: Maximum number of games to return (non-positive returns none).
    """
    snapshot = load_snapshot()
    if snapshot is None:
        return {
            "total": 0,
            "returned": 0,
            "games": [],
            "note": "No snapshot found. Run 'scan' first.",
        }
    games = [GameInfo.from_snapshot(entry) for entry in snapshot]
    incomplete = sorted((g for g in games if not g.is_complete), key=_backlog_sort_key)
    capped = incomplete[: max(0, limit)]
    return {
        "total": len(incomplete),
        "returned": len(capped),
        "games": [
            {
                "app_id": g.app_id,
                "name": g.name,
                "completion_pct": round(g.completion_pct, 1),
                "completionist_hours": g.completionist_hours,
            }
            for g in capped
        ],
    }


# ──────────────────────────────────────────────────────────────
# Gated write tools (preview unless confirm=True; NEVER allowlist these)
# ──────────────────────────────────────────────────────────────


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
    state = State.load()
    refused = apply_manual_pick(
        state,
        app_id,
        game_name,
        max_picks=Config.load().max_manual_picks,
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
    }


@mcp.tool()
def abandon_pick(app_id: int, *, confirm: bool = False) -> dict[str, Any]:
    """Undo a manual pick inside its grace window (gated write).

    With ``confirm=False`` (the default) this performs **no** mutation and
    returns a preview. Only works within ``MANUAL_GRACE_DAYS`` days of the
    pick. Like ``pick_manual``, this mutates **state only** — the CLI's
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

    remaining = manual_pick_grace_remaining(state, app_id)
    if not can_abandon_manual_pick(state, app_id):
        return {
            "ok": False,
            "reason": (
                f"The {MANUAL_GRACE_DAYS}-day grace period has expired; "
                "the pick can no longer be abandoned."
            ),
        }

    game_name = str(pick["game_name"])
    if not confirm:
        return {
            "ok": True,
            "preview": True,
            "action": "abandon_pick",
            "app_id": app_id,
            "game_name": game_name,
            "grace_days_left": remaining,
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


def main() -> None:
    """Run the MCP server over stdio (STDOUT = JSON-RPC, STDERR = logs)."""
    logger.info(
        "Starting steam-backlog-enforcer MCP server (python=%s)", sys.executable
    )
    mcp.run()  # pragma: no cover


if __name__ == "__main__":
    main()
