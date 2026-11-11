"""Tests for HLTB poll-count tracking, schema migration, and confidence display."""

from __future__ import annotations

from steam_backlog_enforcer.tests._polls_helpers import (
    assigned_confidence_echoes,
    poll_state,
)

_CHOSEN = {"app_id": 1, "name": "Chosen"}
_OLD = {"app_id": 2, "name": "Old"}


class TestReportAssignedConfidence:
    """Tests for Report Assigned Confidence."""

    def test_new_low_warning(self) -> None:
        """Test new low warning."""
        echoed = assigned_confidence_echoes(
            {1: 1, 2: 5, 3: 10},
            [
                _CHOSEN,
                {"app_id": 2, "name": "OldShortest"},
                {"app_id": 3, "name": "Other"},
            ],
            poll_state([2, 3], current=1),
        )
        assert any("NEW LOW" in s for s in echoed)
        assert any("Historical min" in s and "OldShortest" in s for s in echoed)

    def test_zero_polls_warning_with_history(self) -> None:
        """Test zero polls warning with history."""
        echoed = assigned_confidence_echoes(
            {1: 0, 2: 5}, [_CHOSEN, _OLD], poll_state([2], current=1)
        )
        assert any("no polls recorded" in s for s in echoed)

    def test_zero_polls_warning_no_history(self) -> None:
        """Test zero polls warning no history."""
        echoed = assigned_confidence_echoes(
            {1: 0}, [_CHOSEN], poll_state([], current=1)
        )
        assert any("no polls recorded" in s for s in echoed)
        assert not any("Historical min" in s for s in echoed)

    def test_healthy_no_warning(self) -> None:
        """Test healthy no warning."""
        echoed = assigned_confidence_echoes(
            {1: 50, 2: 5}, [_CHOSEN, _OLD], poll_state([2], current=1)
        )
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)
        assert any("HLTB confidence: 50" in s for s in echoed)

    def test_unknown_finished_uses_appid_label(self) -> None:
        """Test unknown finished uses appid label."""
        echoed = assigned_confidence_echoes(
            {1: 50, 99: 5}, [_CHOSEN], poll_state([99], current=1)
        )
        assert any("AppID=99" in s for s in echoed)

    def test_chosen_equals_min_no_warning(self) -> None:
        # Edge case: chosen_polls == min_polls (not a new low).
        """Test chosen equals min no warning."""
        echoed = assigned_confidence_echoes(
            {1: 5, 2: 5}, [_CHOSEN, _OLD], poll_state([2], current=1)
        )
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)
