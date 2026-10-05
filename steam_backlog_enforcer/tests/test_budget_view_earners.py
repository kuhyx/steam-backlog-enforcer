"""Tests for /api/budget's ``rules.earners``: the registry, listed generically.

Split from ``test_budget_view.py`` to keep both inside the 250-line cap.
"""

from __future__ import annotations

from earned_time import EARNERS

from steam_backlog_enforcer._budget_view import build_rules
from steam_backlog_enforcer._playtime_state import PlaytimeRules


def test_earners_list_the_registry_with_earned_and_size() -> None:
    """Every registered earner is listed, so the bar needs no per-earner code."""
    rules = PlaytimeRules(
        budget_seconds=0.0,
        warn_at=(),
        sigkill_after=0.0,
        count_launchers=False,
        enforcement=True,
        demo=False,
        earned_seconds={"anki": 1800.0},
    )
    listed = {e["name"]: e for e in build_rules(rules)["earners"]}
    assert list(listed) == [e.name for e in EARNERS]
    assert listed["anki"]["earned_seconds"] == 1800.0
    assert listed["anki"]["bonus_seconds"] == 1800
    assert listed["reading"]["earned_seconds"] == 0.0
