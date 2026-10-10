"""Tests for reporting_progress_cb: HLTB lookups reporting web-job progress."""

from __future__ import annotations

from unittest.mock import MagicMock

from steam_backlog_enforcer._hltb_cached import reporting_progress_cb
from steam_backlog_enforcer._progress import use_progress


class TestReportingProgressCb:
    def test_starts_a_phase_and_advances_by_the_done_count(self) -> None:
        progress = MagicMock()
        with use_progress(progress):
            report = reporting_progress_cb("Fetching", 5, None)
            report(2, 5, 1, "Doom")
        progress.phase.assert_called_once_with("Fetching", 5)
        progress.advance.assert_called_once_with("Doom", step=2)

    def test_forwards_to_the_callers_own_meter(self) -> None:
        inner = MagicMock()
        with use_progress(MagicMock()):
            report = reporting_progress_cb("Fetching", 5, inner)
            report(3, 5, 2, "Quake")
        inner.assert_called_once_with(3, 5, 2, "Quake")
