"""Read-side compatibility for the removed Friday-Monday carry-over.

Exists only to read ``playtime_state.json`` records written before carry-over
was removed on 2026-10-18. Such a record lives at most one gaming day (the
next ``save_state`` drops the ``carry`` key), so this module can be deleted
once no such record can remain.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only: _playtime_state imports this module at runtime.
    from steam_backlog_enforcer._playtime_state import PlaytimeState

logger = logging.getLogger(__name__)


def without_legacy_carry(state: PlaytimeState, carry: object) -> PlaytimeState:
    """Take a removed carry ledger's share for the day out of its high-water.

    Records written before 2026-10-18 folded the Friday-Monday carry into
    ``budget_seconds``, and ``held_today`` would keep paying it out for the
    rest of that day. The key itself is dropped by the next ``save_state``.

    Args:
        state: The record as loaded.
        carry: The raw ``carry`` value from the file, if any.

    Returns:
        *state*, its ``budget_seconds`` lowered by the day's carried share.
    """
    if not isinstance(carry, dict):
        return state
    share = carry.get(state.day_key, 0.0)
    if not isinstance(share, int | float) or share <= 0:
        return state
    logger.warning(
        "Dropping %.0fs of legacy carry-over from %s's budget.", share, state.day_key
    )
    return replace(state, budget_seconds=max(0.0, state.budget_seconds - share))
