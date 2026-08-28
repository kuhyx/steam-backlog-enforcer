"""Tests for the per-tick engagement verdict and the idle backdate.

The backdate is deliberately hard to trigger: it is the only place the budget
counter ever moves backwards, so every guard around it is tested here.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._engagement_types import (
    CAUSE_FOCUS,
    CAUSE_IDLE,
    STATE_ENGAGED,
    STATE_NOT_APPLICABLE,
    STATE_PAUSED,
    CauseTally,
    EngagementVerdict,
)
from steam_backlog_enforcer._playtime_engagement import EngagementTracker
from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState

PE = "steam_backlog_enforcer._playtime_engagement"

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


def _tracker(**kwargs: object) -> EngagementTracker:
    return EngagementTracker(
        uid=1000,
        probe=MagicMock(name="XProbe"),
        controller=MagicMock(name="ControllerActivity"),
        holder_path=Path("/nonexistent/holder.lock"),
        **kwargs,
    )


def _engaged() -> EngagementVerdict:
    return EngagementVerdict(state=STATE_ENGAGED)


def _idle_paused() -> EngagementVerdict:
    return EngagementVerdict(state=STATE_PAUSED, causes=(CAUSE_IDLE,))


class TestAssess:
    def test_nothing_qualifying_is_not_applicable(self) -> None:
        verdict = _tracker().assess(RULES, qualifying=set(), now_monotonic=1.0)
        assert verdict.state == STATE_NOT_APPLICABLE
        assert verdict.engaged is True

    def test_a_disabled_gate_bills_without_probing(self) -> None:
        tracker = _tracker()
        with patch(f"{PE}.assess_screen") as screen:
            verdict = tracker.assess(
                replace(RULES, engagement_gate=False),
                qualifying={7},
                now_monotonic=1.0,
            )
        assert verdict.state == STATE_ENGAGED
        assert verdict.qualifying == (7,)
        screen.assert_not_called()

    def test_every_cause_is_recorded_not_just_the_first(self) -> None:
        # The log has to be able to answer "was the screen ALSO locked?", and
        # the backdate must be able to tell an idle-only pause from a compound.
        tracker = _tracker()
        with (
            patch(f"{PE}.assess_screen", side_effect=_add("screen_held", (True, 5))),
            patch(f"{PE}.assess_focus", side_effect=_add_focus("focus", 9)),
            patch(f"{PE}.assess_idle", side_effect=_add_idle("idle", (900.0, None))),
        ):
            verdict = tracker.assess(RULES, qualifying={7}, now_monotonic=1.0)
        assert verdict.state == STATE_PAUSED
        assert set(verdict.causes) == {"screen_held", "focus", "idle"}
        assert verdict.holder_pid == 5
        assert verdict.focus_pid == 9

    def test_no_causes_means_engaged(self) -> None:
        tracker = _tracker()
        with (
            patch(f"{PE}.assess_screen", return_value=(False, None)),
            patch(f"{PE}.assess_focus", return_value=7),
            patch(f"{PE}.assess_idle", return_value=(1.0, None)),
        ):
            verdict = tracker.assess(RULES, qualifying={7}, now_monotonic=1.0)
        assert verdict.state == STATE_ENGAGED


class TestClose:
    def test_releases_both_resources(self) -> None:
        probe = MagicMock()
        controller = MagicMock()
        tracker = EngagementTracker(
            uid=1000, probe=probe, controller=controller, holder_path=Path("x")
        )
        tracker.close()
        probe.close.assert_called_once()
        controller.close.assert_called_once()


class TestBackdate:
    def _state(self, seconds: float = 1000.0) -> PlaytimeState:
        return PlaytimeState(day_key="2026-08-28", seconds=seconds)

    def test_refunds_the_grace_on_the_engaged_to_idle_edge(self) -> None:
        tracker = _tracker()
        state = tracker.backdate(self._state(), _engaged(), rules=RULES)
        state = tracker.backdate(state, _idle_paused(), rules=RULES)
        assert state.seconds == 700.0

    def test_refunds_only_once_per_walk_away(self) -> None:
        tracker = _tracker()
        state = tracker.backdate(self._state(), _engaged(), rules=RULES)
        state = tracker.backdate(state, _idle_paused(), rules=RULES)
        state = tracker.backdate(state, _idle_paused(), rules=RULES)
        assert state.seconds == 700.0

    def test_never_refunds_below_zero(self) -> None:
        tracker = _tracker()
        state = tracker.backdate(self._state(seconds=10.0), _engaged(), rules=RULES)
        state = tracker.backdate(state, _idle_paused(), rules=RULES)
        assert state.seconds == 0.0

    def test_no_refund_on_the_first_tick_after_a_restart(self) -> None:
        # With no previous verdict there is no edge to recognise, and inventing
        # one would hand out a free refund on every daemon restart.
        tracker = _tracker()
        state = tracker.backdate(self._state(), _idle_paused(), rules=RULES)
        assert state.seconds == 1000.0

    def test_no_refund_across_a_day_rollover(self) -> None:
        tracker = _tracker()
        tracker.backdate(self._state(), _engaged(), rules=RULES)
        tomorrow = PlaytimeState(day_key="2026-08-29", seconds=1000.0)
        assert tracker.backdate(tomorrow, _idle_paused(), rules=RULES).seconds == 1000.0

    def test_no_refund_when_something_else_also_paused_the_tick(self) -> None:
        tracker = _tracker()
        state = tracker.backdate(self._state(), _engaged(), rules=RULES)
        compound = EngagementVerdict(
            state=STATE_PAUSED, causes=(CAUSE_IDLE, CAUSE_FOCUS)
        )
        assert tracker.backdate(state, compound, rules=RULES).seconds == 1000.0

    def test_no_refund_while_still_engaged(self) -> None:
        tracker = _tracker()
        state = tracker.backdate(self._state(), _engaged(), rules=RULES)
        assert tracker.backdate(state, _engaged(), rules=RULES).seconds == 1000.0

    def test_reports_the_measured_idle_time(self) -> None:
        tracker = _tracker()
        tracker.backdate(self._state(), _engaged(), rules=RULES)
        verdict = EngagementVerdict(
            state=STATE_PAUSED, causes=(CAUSE_IDLE,), idle_seconds=301.0
        )
        assert tracker.backdate(self._state(), verdict, rules=RULES).seconds == 700.0


def _add(cause: str, result: tuple[bool | None, int | None]) -> object:
    def impl(_path: object, tally: CauseTally) -> object:
        tally.causes.append(cause)
        return result

    return impl


def _add_focus(cause: str, pid: int) -> object:
    def impl(
        _probe: object, _rules: object, _qualifying: object, tally: CauseTally
    ) -> int:
        tally.causes.append(cause)
        return pid

    return impl


def _add_idle(cause: str, result: tuple[float | None, float | None]) -> object:
    def impl(
        _probe: object,
        _controller: object,
        _rules: object,
        tally: CauseTally,
        _now: float,
    ) -> object:
        tally.causes.append(cause)
        return result

    return impl
