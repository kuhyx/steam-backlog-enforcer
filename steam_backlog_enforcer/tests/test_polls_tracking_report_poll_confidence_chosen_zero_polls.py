"""Tests for HLTB poll-count tracking — scanning integration (part 2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _cmd_done, scanning
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import GameInfo

_TYPES = "steam_backlog_enforcer._hltb_types"
_CMD = "steam_backlog_enforcer._cmd_done"
_SCAN = "steam_backlog_enforcer.scanning"
_SCANCONF = "steam_backlog_enforcer._scanning_confidence"
_POLLS = "steam_backlog_enforcer._polls_reporting"


def _state(finished: list[int], current: int | None = None) -> State:
    s = State()
    s.finished_app_ids = list(finished)
    s.current_app_id = current
    s.current_game_name = ""
    return s


class TestScanningPollsIntegrationGroup2:
    """Tests for Scanning Polls Integration Group2."""

    def test_report_poll_confidence_chosen_zero_polls(self) -> None:
        """Covers scanning.py 301-302: 0-poll chosen with history yields warning."""
        echoed: list[str] = []
        chosen = GameInfo(
            app_id=1,
            name="Chosen",
            total_achievements=10,
            unlocked_achievements=0,
            playtime_minutes=0,
            comp_100_count=0,
        )
        old = GameInfo(
            app_id=2,
            name="Old",
            total_achievements=10,
            unlocked_achievements=10,
            playtime_minutes=0,
        )
        with (
            patch(
                f"{_POLLS}._backfill_polls_for_finished",
                return_value={1: 0, 2: 5},
            ),
            patch(
                f"{_POLLS}._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
        ):
            scanning._report_poll_confidence(
                chosen, [chosen, old], _state([2], current=1)
            )
        assert any("no polls recorded" in s for s in echoed)

    def test_do_scan_kept_assignment_missing_game(self) -> None:
        """Covers scanning.py 110->116: current_app_id set but game absent."""
        from steam_backlog_enforcer.config import Config
        from steam_backlog_enforcer.scanning import do_scan

        other = GameInfo(
            app_id=999,
            name="Other",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=0,
        )

        mock_client = MagicMock()
        mock_client.build_game_list.return_value = [other]
        with (
            patch(f"{_SCAN}.SteamAPIClient", return_value=mock_client),
            patch(f"{_SCAN}.fetch_hltb_times_cached", return_value={999: 10.0}),
            patch(f"{_SCAN}.save_snapshot"),
            patch(f"{_SCAN}.pick_next_game") as mock_pick,
            patch(f"{_SCAN}._echo"),
            patch(f"{_SCAN}._report_poll_confidence") as mock_report,
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State(current_app_id=440)  # not in games
            do_scan(config, state)
        mock_pick.assert_not_called()
        mock_report.assert_not_called()

    def test_cmd_done_no_finished_history_chosen_has_polls(self) -> None:
        """Covers _cmd_done.py 100->103: no finished history, chosen has >0 polls."""
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 7},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([], current=1))
        assert any("HLTB confidence: 7" in s for s in echoed)
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)
