"""MCP, CLI and web report "unlimited" with no number once the budget is gone."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _budget_view as view
from steam_backlog_enforcer import _mcp_gaming_time as mcp_gaming_time
from steam_backlog_enforcer._budget_resolve import BudgetResolution
from steam_backlog_enforcer._cmd_playtime import cmd_gaming_status
from steam_backlog_enforcer._playtime_state import PlaytimeState
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.tests._cmd_playtime_patches import cli_as, echoed

_RESOLVER = "steam_backlog_enforcer._playtime_state.resolve_budget"
_STORED = PlaytimeState(day_key="2026-11-17", seconds=40_000.0, budget_seconds=18_000.0)


def _resolution(*, enforced: bool) -> BudgetResolution:
    """A resolution that would be a 5 h budget if it were enforced."""
    return BudgetResolution(
        seconds=18_000.0,
        base_seconds=18_000.0,
        workout_seconds=0.0,
        leetcode_seconds=0.0,
        reason="5.0h: base" if enforced else "unlimited",
        enforced=enforced,
    )


def _snapshot(*, enforced: bool) -> dict[str, Any]:
    with (
        patch(_RESOLVER, return_value=_resolution(enforced=enforced)),
        patch.object(view, "load_state", return_value=_STORED),
        patch.object(view, "mounted_targets", return_value=set()),
    ):
        return view.build_budget_snapshot()


class TestWebView:
    """``/api/budget`` payload."""

    def test_unlimited_has_no_number(self) -> None:
        """No budget, remaining, fraction or warning; the flag says why."""
        snap = _snapshot(enforced=False)
        today, rules = snap["today"], snap["rules"]
        assert today["unlimited"] is True
        assert rules["unlimited"] is True
        for field in ("budget_seconds", "seconds_remaining", "fraction_used"):
            assert today[field] is None
        assert today["next_warning_seconds"] is None
        assert today["shadow"]["budget_seconds"] is None
        assert rules["budget_seconds"] is None
        assert rules["warn_at"] == []
        assert rules["earners"] == []
        assert today["seconds_used"] == 40_000.0

    def test_enforced_day_keeps_its_numbers(self) -> None:
        """Before the switch the payload is what it always was."""
        snap = _snapshot(enforced=True)
        today = snap["today"]
        assert today["unlimited"] is False
        assert snap["rules"]["unlimited"] is False
        assert today["budget_seconds"] == 18_000.0
        assert today["seconds_remaining"] == 0.0
        assert today["fraction_used"] == 1.0


class TestMcp:
    """``get_gaming_time`` tool."""

    @pytest.mark.parametrize("recorded", [True, False])
    def test_unlimited(self, *, recorded: bool) -> None:
        """Recorded or not, the reply says unlimited and carries no budget."""
        stored = _STORED if recorded else None
        with (
            patch(_RESOLVER, return_value=_resolution(enforced=False)),
            patch.object(view, "load_state", return_value=stored),
            patch.object(view, "mounted_targets", return_value=set()),
        ):
            out = mcp_gaming_time.get_gaming_time()
        assert out["unlimited"] is True
        assert out["budget_seconds"] is None
        assert out.get("seconds_remaining") is None


class TestCli:
    """``gaming-status``."""

    def test_unlimited_prints_no_budget_number(self) -> None:
        """The status says unlimited, not a remaining count."""
        with (
            patch(_RESOLVER, return_value=_resolution(enforced=False)),
            patch(
                "steam_backlog_enforcer._cmd_playtime.load_state",
                side_effect=lambda demo: None if demo else _STORED,
            ),
            patch(
                "steam_backlog_enforcer._cmd_playtime.mounted_targets",
                return_value=set(),
            ),
            cli_as(None) as cli,
        ):
            cmd_gaming_status(Config(), State())
        text = echoed(cli.echo)
        assert "unlimited" in text
        assert "budget_seconds" not in text
        assert "remaining" not in text
