"""Collecting test_budget_view never reads the host's leisure switch file."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._playtime_state import rules_for
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests import test_budget_view
from steam_backlog_enforcer.tests._no_workout_http import earned_budget

if TYPE_CHECKING:
    from pathlib import Path


def test_a_live_host_switch_does_not_leak_into_rules(tmp_path: Path) -> None:
    with (
        patch("steam_backlog_enforcer._playtime_state.held_today", return_value=0.0),
        patch(
            "steam_backlog_enforcer._playtime_state.resolve_budget",
            side_effect=earned_budget,
        ),
    ):
        dormant = rules_for(Config(), demo=False)
    # The host went live long ago: what the import-time read would see.
    host = tmp_path / "host_leisure_from"
    host.write_text("2000-01-01\n", encoding="utf-8")
    with patch("earned_time._leisure.LEISURE_FROM_PATH", host):
        reloaded = importlib.reload(test_budget_view)
    assert dormant == reloaded.RULES
