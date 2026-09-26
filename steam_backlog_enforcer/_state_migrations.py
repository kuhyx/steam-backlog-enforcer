"""Load-time upgrades of an older ``state.json``.

Each function mutates a freshly loaded ``State`` in place and reports whether
it changed anything, so ``State.load`` can persist an upgrade exactly once.
Split out of :mod:`steam_backlog_enforcer.config` to keep it under the
250-line cap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State


def migrate_legacy_manual_pick(state: State) -> bool:
    """Fold a pre-multi-pick single manual pick into ``manual_picks``.

    A live lock written by the old single-slot code must survive the
    upgrade, so the legacy fields are read once, converted, and cleared.

    Args:
        state: The loaded enforcer state to mutate.

    Returns:
        Whether a legacy pick was migrated.
    """
    if state.manual_pick_app_id is None or state.manual_picks:
        return False
    state.manual_picks = [
        {
            "app_id": state.manual_pick_app_id,
            "game_name": state.manual_pick_game_name,
            "started_at": state.manual_pick_started_at,
        }
    ]
    state.manual_pick_app_id = None
    state.manual_pick_game_name = ""
    state.manual_pick_started_at = ""
    return True


def backfill_assignment_times(state: State) -> bool:
    """Stamp assignments made before assignment times were recorded.

    The current game gets "now": achievements earned before this upgrade
    cannot be shown to come after the assignment, so they do not count.
    Manual picks already carry ``started_at``, which is reused, including for
    a current game that is also a pick.

    Args:
        state: The loaded enforcer state to mutate.

    Returns:
        Whether anything changed. The caller must persist it, or every load
        would re-stamp "now" and no achievement could ever count.
    """
    changed = False
    pick_started = {
        p["app_id"]: p["started_at"]
        for p in state.manual_picks
        if p.get("app_id") is not None and p.get("started_at")
    }
    for app_id, started_at in pick_started.items():
        changed |= _stamp_if_missing(state, app_id, started_at)
    current = state.current_app_id
    if current is not None:
        if not state.current_assigned_at:
            # A current game that is also a pick was assigned when picked.
            state.current_assigned_at = pick_started.get(current) or (
                datetime.now(UTC).isoformat()
            )
            changed = True
        changed |= _stamp_if_missing(state, current, state.current_assigned_at)
    return changed


def _stamp_if_missing(state: State, app_id: int, stamp: str) -> bool:
    if str(app_id) in state.last_assigned_at:
        return False
    state.last_assigned_at[str(app_id)] = stamp
    return True
