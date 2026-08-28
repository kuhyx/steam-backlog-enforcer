"""Tests for turning each engagement signal into a pause cause.

The rule under test everywhere: a probe that *fails* must not pause the tick.
Failing closed keeps a broken detector from becoming free gaming.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._engagement_probes import (
    assess_focus,
    assess_idle,
    assess_screen,
    focus_qualifies,
)
from steam_backlog_enforcer._engagement_types import CauseTally
from steam_backlog_enforcer._playtime_state import PlaytimeRules
from steam_backlog_enforcer._screen_hold import ScreenHold, ScreenHoldError
from steam_backlog_enforcer._x_probe import XProbeError

EP = "steam_backlog_enforcer._engagement_probes"

RULES = PlaytimeRules(
    budget_seconds=28800.0,
    warn_at=(3600,),
    sigkill_after=30.0,
    count_launchers=True,
    enforcement=True,
    demo=False,
    engagement_gate=True,
    idle_grace_seconds=300.0,
    require_game_focus=True,
)


def _probe(idle: float = 0.0) -> MagicMock:
    probe = MagicMock(name="XProbe")
    probe.idle_seconds.return_value = idle
    return probe


class TestAssessScreen:
    def test_a_held_screen_pauses(self) -> None:
        tally = CauseTally()
        held = ScreenHold(held=True, holder_pid=99)
        with patch(f"{EP}.screen_hold", return_value=held):
            assert assess_screen(Path("x"), tally) == (True, 99)
        assert tally.causes == ["screen_held"]
        assert tally.degraded == []

    def test_a_free_screen_does_not_pause(self) -> None:
        tally = CauseTally()
        with patch(f"{EP}.screen_hold", return_value=ScreenHold(held=False)):
            assert assess_screen(Path("x"), tally) == (False, None)
        assert tally.causes == []

    def test_a_failed_probe_bills_and_is_recorded(self) -> None:
        tally = CauseTally()
        with patch(f"{EP}.screen_hold", side_effect=ScreenHoldError("boom")):
            assert assess_screen(Path("x"), tally) == (None, None)
        assert tally.causes == []
        assert tally.degraded == ["screen_held"]


class TestAssessFocus:
    def test_disabled_criterion_reports_nothing(self) -> None:
        tally = CauseTally()
        relaxed = replace(RULES, require_game_focus=False)
        assert assess_focus(_probe(), relaxed, {1}, tally) is None
        assert tally.causes == []

    def test_the_game_owning_focus_does_not_pause(self) -> None:
        tally = CauseTally()
        with patch(f"{EP}.focused_pid", return_value=42):
            assert assess_focus(_probe(), RULES, {42}, tally) == 42
        assert tally.causes == []

    def test_another_window_owning_focus_pauses(self) -> None:
        tally = CauseTally()
        with patch(f"{EP}.focused_pid", return_value=7):
            assert assess_focus(_probe(), RULES, {42}, tally) == 7
        assert tally.causes == ["focus"]

    def test_a_failed_probe_bills_and_drops_the_connection(self) -> None:
        tally = CauseTally()
        probe = _probe()
        with patch(f"{EP}.focused_pid", side_effect=XProbeError("no display")):
            assert assess_focus(probe, RULES, {42}, tally) is None
        assert tally.causes == []
        assert tally.degraded == ["focus"]
        probe.close.assert_called_once()


class TestAssessIdle:
    def test_recent_input_does_not_pause(self) -> None:
        tally = CauseTally()
        controller = MagicMock()
        controller.seconds_since_activity.return_value = None
        assert assess_idle(_probe(1.0), controller, RULES, tally, 5.0) == (1.0, None)
        assert tally.causes == []

    def test_silence_past_the_grace_pauses(self) -> None:
        tally = CauseTally()
        controller = MagicMock()
        controller.seconds_since_activity.return_value = None
        assess_idle(_probe(400.0), controller, RULES, tally, 5.0)
        assert tally.causes == ["idle"]

    def test_recent_controller_input_keeps_the_tick_alive(self) -> None:
        # The X idle counter cannot see a gamepad; without this, a controller
        # session would pause the budget and hand out free gaming.
        tally = CauseTally()
        controller = MagicMock()
        controller.seconds_since_activity.return_value = 2.0
        assert assess_idle(_probe(9999.0), controller, RULES, tally, 5.0) == (2.0, 2.0)
        assert tally.causes == []

    def test_a_failed_probe_bills_and_drops_the_connection(self) -> None:
        tally = CauseTally()
        probe = _probe()
        probe.idle_seconds.side_effect = XProbeError("no display")
        controller = MagicMock()
        controller.seconds_since_activity.return_value = 7.0
        assert assess_idle(probe, controller, RULES, tally, 5.0) == (None, 7.0)
        assert tally.causes == []
        assert tally.degraded == ["idle"]
        probe.close.assert_called_once()


class TestFocusQualifies:
    def test_nothing_focused_does_not_qualify(self) -> None:
        assert focus_qualifies(None, {1234}) is False

    def test_the_process_itself_qualifies(self) -> None:
        assert focus_qualifies(1234, {1234}) is True

    def test_a_descendant_window_qualifies(self) -> None:
        # Proton games commonly own their window from a child process.
        with patch(f"{EP}._read_ppid", side_effect=[500, 42]):
            assert focus_qualifies(9000, {42}) is True

    def test_reaching_init_does_not_qualify(self) -> None:
        with patch(f"{EP}._read_ppid", return_value=1):
            assert focus_qualifies(9000, {42}) is False

    def test_an_unreadable_parent_does_not_qualify(self) -> None:
        with patch(f"{EP}._read_ppid", return_value=None):
            assert focus_qualifies(9000, {42}) is False

    def test_a_pathological_chain_terminates(self) -> None:
        with patch(f"{EP}._read_ppid", side_effect=lambda pid: pid + 1):
            assert focus_qualifies(9000, {42}) is False
