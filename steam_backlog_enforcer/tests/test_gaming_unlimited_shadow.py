"""With the watcher uninstalled, an unlimited day bills no shadow time at all.

Before 2026-11-16 a missing ``now.json`` fails closed and bills the shadow
budget (``failclosed:watcher``). Unlimited days must not read the watcher.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import DEFAULT, patch

import pytest

from steam_backlog_enforcer._budget_resolve import BudgetResolution
from steam_backlog_enforcer._playtime import playtime_tick
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    load_state,
    save_state,
)
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._fake_session import fake_session

PKG = "steam_backlog_enforcer._playtime"
NOW = datetime(2026, 11, 17, 20, 0, tzinfo=timezone(timedelta(hours=2)))


def _tick_with_no_watcher(*, enforced: bool) -> PlaytimeState:
    """One idle tick (no game, no ``now.json``) on a day that is or is not capped."""
    save_state(
        PlaytimeState(day_key="2026-11-17", last_tick_at=NOW.timestamp() - 3.0),
        demo=False,
    )
    day = BudgetResolution(0.0, 0.0, 0.0, 0.0, "stub", enforced=enforced)
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "steam_backlog_enforcer._playtime_state.resolve_budget",
                return_value=day,
            )
        )
        stack.enter_context(
            patch.multiple(
                f"{PKG}",
                qualifying_pids=lambda *_: {},
                mounted_targets=set,
                is_total_block_active=lambda: False,
            )
        )
        stack.enter_context(
            patch("steam_backlog_enforcer._playtime_cutoff.reconcile", DEFAULT)
        )
        clock = stack.enter_context(patch(f"{PKG}.datetime"))
        clock.now.return_value = NOW
        playtime_tick(Config(), interval=3.0, session=fake_session())
    stored = load_state(demo=False)
    assert stored is not None
    return stored


@pytest.mark.parametrize(("enforced", "billed"), [(True, 3.0), (False, 0.0)])
def test_shadow_bills_only_while_a_budget_exists(
    *, enforced: bool, billed: float
) -> None:
    """The fail-closed watcher bill is the old behaviour; unlimited bills nothing."""
    stored = _tick_with_no_watcher(enforced=enforced)
    assert stored.shadow.seconds == billed
    assert ("failclosed:watcher" in stored.shadow.per_source) is enforced
