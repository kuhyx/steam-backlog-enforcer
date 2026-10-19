"""The shadow leisure block (contract C4) for ``/api/budget`` and MCP.

Read-only and display-only: what the leisure budget *would* say, beside the
enforced gaming numbers it never changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_state import PlaytimeState


def shadow_view(state: PlaytimeState) -> dict[str, Any]:
    """Compose the shadow block from stored state.

    Args:
        state: Loaded accounting state.

    Returns:
        Used/budget/remaining seconds, whether the leisure budget would block
        now, paused seconds, and the per-source split.
    """
    remaining = max(0.0, state.shadow_budget_seconds - state.shadow_seconds)
    return {
        "seconds_used": round(state.shadow_seconds, 1),
        "budget_seconds": state.shadow_budget_seconds,
        "seconds_remaining": round(remaining, 1),
        "would_block": remaining <= 0.0,
        "paused_seconds": round(state.shadow_paused_seconds, 1),
        "per_source": {k: round(v, 1) for k, v in state.shadow_per_source.items()},
    }
