"""Tests for HLTB poll-count tracking — scanning integration (part 2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import do_scan
from steam_backlog_enforcer.tests._polls_helpers import (
    SCAN,
    assigned_confidence_echoes,
    make_game,
    poll_confidence_echoes,
    poll_state,
)


class TestScanningPollsIntegrationGroup2:
    """Tests for Scanning Polls Integration Group2."""

    def test_report_poll_confidence_chosen_zero_polls(self) -> None:
        """Covers scanning.py 301-302: 0-poll chosen with history yields warning."""
        chosen = make_game(1, "Chosen")
        old = make_game(2, "Old", unlocked=10)
        echoed = poll_confidence_echoes(
            chosen, [chosen, old], {1: 0, 2: 5}, poll_state([2], current=1)
        )
        assert any("no polls recorded" in s for s in echoed)

    def test_do_scan_kept_assignment_missing_game(self) -> None:
        """Covers scanning.py 110->116: current_app_id set but game absent."""
        other = make_game(999, "Other", unlocked=5)

        mock_client = MagicMock()
        mock_client.build_game_list.return_value = [other]
        with (
            patch(f"{SCAN}.SteamAPIClient", return_value=mock_client),
            patch(f"{SCAN}.fetch_hltb_times_cached", return_value={999: 10.0}),
            patch(f"{SCAN}.save_snapshot"),
            patch(f"{SCAN}.pick_next_game") as mock_pick,
            patch(f"{SCAN}._echo"),
            patch(f"{SCAN}._report_poll_confidence") as mock_report,
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State(current_app_id=440)  # not in games
            do_scan(config, state)
        mock_pick.assert_not_called()
        mock_report.assert_not_called()

    def test_cmd_done_no_finished_history_chosen_has_polls(self) -> None:
        """Covers _cmd_done.py 100->103: no finished history, chosen has >0 polls."""
        echoed = assigned_confidence_echoes(
            {1: 7}, [{"app_id": 1, "name": "Chosen"}], poll_state([], current=1)
        )
        assert any("HLTB confidence: 7" in s for s in echoed)
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)
