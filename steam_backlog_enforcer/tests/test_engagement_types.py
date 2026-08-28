"""Tests for the engagement verdict value object."""

from __future__ import annotations

from steam_backlog_enforcer._engagement_types import (
    CAUSE_FOCUS,
    CAUSE_IDLE,
    STATE_ENGAGED,
    STATE_NOT_APPLICABLE,
    STATE_PAUSED,
    EngagementVerdict,
)


class TestEngaged:
    def test_engaged_state_bills(self) -> None:
        assert EngagementVerdict(state=STATE_ENGAGED).engaged is True

    def test_nothing_qualifying_still_bills(self) -> None:
        # Nothing accrues anyway; calling it "paused" would fill the audit log
        # with a pause reason during ordinary desktop use.
        assert EngagementVerdict(state=STATE_NOT_APPLICABLE).engaged is True

    def test_paused_state_does_not_bill(self) -> None:
        assert EngagementVerdict(state=STATE_PAUSED).engaged is False


class TestReason:
    def test_falls_back_to_the_state_when_there_are_no_causes(self) -> None:
        assert EngagementVerdict(state=STATE_ENGAGED).reason == STATE_ENGAGED

    def test_joins_every_cause(self) -> None:
        verdict = EngagementVerdict(
            state=STATE_PAUSED, causes=(CAUSE_IDLE, CAUSE_FOCUS)
        )
        assert verdict.reason == "idle+focus"


class TestIdleOnly:
    def test_true_for_a_sole_idle_cause(self) -> None:
        assert EngagementVerdict(state=STATE_PAUSED, causes=(CAUSE_IDLE,)).idle_only()

    def test_false_when_something_else_also_paused_the_tick(self) -> None:
        verdict = EngagementVerdict(
            state=STATE_PAUSED, causes=(CAUSE_IDLE, CAUSE_FOCUS)
        )
        assert verdict.idle_only() is False

    def test_false_when_engaged(self) -> None:
        assert EngagementVerdict(state=STATE_ENGAGED).idle_only() is False
