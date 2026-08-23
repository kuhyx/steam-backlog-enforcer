"""Read-only MCP tools: dataset, status, stats and the backlog list.

Separated from the mutating tools in
:mod:`steam_backlog_enforcer._mcp_actions` so that "what can this server
change?" is answerable by looking at one file.
"""

from __future__ import annotations

from typing import Any

from steam_backlog_enforcer._actions import (
    status_payload,
)
from steam_backlog_enforcer._mcp_server import (
    _DEFAULT_LIST_LIMIT,
    _backlog_sort_key,
    mcp,
)
from steam_backlog_enforcer._web_dataset import build_web_dataset, dataset_to_payload
from steam_backlog_enforcer.config import State, load_snapshot
from steam_backlog_enforcer.steam_api import GameInfo


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
