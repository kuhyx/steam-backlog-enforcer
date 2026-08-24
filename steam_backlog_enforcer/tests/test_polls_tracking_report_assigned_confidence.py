"""Tests for HLTB poll-count tracking, schema migration, and confidence display."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer import _cmd_done
from steam_backlog_enforcer.config import State

_TYPES = "steam_backlog_enforcer._hltb_types"
_CMD = "steam_backlog_enforcer._cmd_done"
_SCAN = "steam_backlog_enforcer.scanning"


def _state(finished: list[int], current: int | None = None) -> State:
    s = State()
    s.finished_app_ids = list(finished)
    s.current_app_id = current
    s.current_game_name = ""
    return s


class TestReportAssignedConfidence:
    """Tests for Report Assigned Confidence."""

    def test_new_low_warning(self) -> None:
        """Test new low warning."""
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 1, 2: 5, 3: 10},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                    {"app_id": 2, "name": "OldShortest"},
                    {"app_id": 3, "name": "Other"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([2, 3], current=1))
        assert any("NEW LOW" in s for s in echoed)
        assert any("Historical min" in s and "OldShortest" in s for s in echoed)

    def test_zero_polls_warning_with_history(self) -> None:
        """Test zero polls warning with history."""
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 0, 2: 5},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                    {"app_id": 2, "name": "Old"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([2], current=1))
        assert any("no polls recorded" in s for s in echoed)

    def test_zero_polls_warning_no_history(self) -> None:
        """Test zero polls warning no history."""
        echoed: list[str] = []
        with (
            patch(f"{_CMD}._backfill_polls_for_finished", return_value={1: 0}),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([], current=1))
        assert any("no polls recorded" in s for s in echoed)
        assert not any("Historical min" in s for s in echoed)

    def test_healthy_no_warning(self) -> None:
        """Test healthy no warning."""
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 50, 2: 5},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                    {"app_id": 2, "name": "Old"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([2], current=1))
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)
        assert any("HLTB confidence: 50" in s for s in echoed)

    def test_unknown_finished_uses_appid_label(self) -> None:
        """Test unknown finished uses appid label."""
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 50, 99: 5},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([99], current=1))
        assert any("AppID=99" in s for s in echoed)

    def test_chosen_equals_min_no_warning(self) -> None:
        # Edge case: chosen_polls == min_polls (not a new low).
        """Test chosen equals min no warning."""
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 5, 2: 5},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                    {"app_id": 2, "name": "Old"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([2], current=1))
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)
