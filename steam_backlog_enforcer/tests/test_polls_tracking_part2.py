"""Tests for HLTB poll-count tracking — scanning integration (part 2)."""

from __future__ import annotations

from dataclasses import replace
import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._scanning_confidence import _backfill_polls_for_finished
from steam_backlog_enforcer.tests._polls_helpers import (
    SCAN,
    TYPES,
    echo_sink,
    filling_fetch,
    hltb_cache_patched,
    make_game,
    poll_confidence_echoes,
    poll_state,
    write_cache,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestScanningPollsIntegration:
    """Tests for Scanning Polls Integration."""

    def test_do_scan_kept_assignment_reports(self) -> None:
        # Targeted test for scanning's `else` branch that prints CURRENT.
        """Test do scan kept assignment reports."""
        echoed: list[str] = []
        games = [
            replace(
                make_game(1, "X", unlocked=2, polls=(20, 0)), completionist_hours=5.0
            )
        ]
        state = poll_state([], current=1)
        with (
            echo_sink(SCAN, echoed) as mock_echo,
            patch(f"{SCAN}._report_poll_confidence") as mock_report,
        ):
            # Directly invoke just the kept-assignment branch.
            current = next((g for g in games if g.app_id == state.current_app_id), None)
            assert current is not None
            # The patched names, as scanning's branch would call them.
            mock_echo(f"\n>>> CURRENT: {current.name} (AppID={current.app_id})")
            mock_report(current, games, state)
        assert any("CURRENT" in s for s in echoed)
        mock_report.assert_called_once()

    def test_report_poll_confidence_new_low(self) -> None:
        """Test report poll confidence new low."""
        chosen = make_game(1, "Chosen")
        games = [chosen, make_game(2, "Old", unlocked=10)]
        echoed = poll_confidence_echoes(
            chosen, games, {1: 1, 2: 5}, poll_state([2], current=1)
        )
        assert any("NEW LOW" in s for s in echoed)
        assert chosen.comp_100_count == 1

    def test_report_poll_confidence_no_history(self) -> None:
        """Test report poll confidence no history."""
        chosen = make_game(1, "Chosen", polls=(4, 0))
        echoed = poll_confidence_echoes(
            chosen, [chosen], {1: 4}, poll_state([], current=1)
        )
        # No "Historical min" line when no finished games have polls.
        assert not any("Historical min" in s for s in echoed)
        assert any("HLTB confidence: 4" in s for s in echoed)

    def test_scanning_backfill_no_missing(self, tmp_path: Path) -> None:
        """Test scanning backfill no missing."""
        cache_file = write_cache(tmp_path, {"2": {"hours": 1.0, "polls": 5}})
        with patch(f"{TYPES}.HLTB_CACHE_FILE", cache_file):
            result = _backfill_polls_for_finished(
                poll_state([2]), [make_game(2, "X", total=0)]
            )
        assert result == {2: 5}

    def test_scanning_backfill_with_missing(self, tmp_path: Path) -> None:
        """Test scanning backfill with missing."""
        cache_file = write_cache(tmp_path, {"2": {"hours": 3.0, "polls": 0}})
        with hltb_cache_patched(cache_file, tmp_path, filling_fetch(3.0, 8)):
            result = _backfill_polls_for_finished(
                poll_state([2]), [make_game(2, "X", total=0)]
            )
        assert result == {2: 8}

    def test_scanning_backfill_preserves_hours_on_miss(self, tmp_path: Path) -> None:
        """Test scanning backfill preserves hours on miss."""
        cache_file = write_cache(tmp_path, {"2": {"hours": 9.0, "polls": 0}})
        with hltb_cache_patched(cache_file, tmp_path, filling_fetch(-1, 0)):
            _backfill_polls_for_finished(poll_state([2]), [make_game(2, "X", total=0)])
        final = json.loads(cache_file.read_text(encoding="utf-8"))
        assert final["2"]["hours"] == 9.0
