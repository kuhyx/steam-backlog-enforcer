"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from steam_backlog_enforcer._stats import cmd_stats
from steam_backlog_enforcer._web_dataset import PaceVsHLTB
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.tests._stats_cmd_env import (
    cmd_stats_env,
    snapshot_game,
    stats_config,
    times_entry,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer._stats import _GameTimes


class TestCmdStatsGroup2:
    """Tests for cmd_stats."""

    def test_refilter_called_when_ensure_rush_data_returns_true(self) -> None:
        """_filter_qualifying_games called twice when _ensure_rush_data returns True."""
        state = State()
        snapshot = [snapshot_game()]
        entry = times_entry(snapshot[0])
        filter_calls: list[int] = []

        def count_filter(
            _games: object, _state: object
        ) -> tuple[list[_GameTimes], int, int, int]:
            """Test count filter."""
            filter_calls.append(1)
            return [entry], 0, 0, 0

        with cmd_stats_env(
            snapshot,
            count_filter,
            _ensure_rush_data={"return_value": True},
            _print_worst_example={},
        ):
            cmd_stats(stats_config(), state)
        assert len(filter_calls) == 2

    def test_games_done_since_start_passed_to_pace(self) -> None:
        """_print_pace_scenario gets only games completed after started_at."""

        started = datetime(2026, 1, 1, tzinfo=UTC)
        state = State(enforcement_started_at=started.isoformat())

        after_ts = int(datetime(2026, 3, 1, tzinfo=UTC).timestamp())
        before_ts = int(datetime(2025, 6, 1, tzinfo=UTC).timestamp())

        def _ach(ts: int) -> dict[str, object]:
            """Test ach."""
            return {
                "api_name": "A",
                "display_name": "A",
                "achieved": True,
                "unlock_time": ts,
            }

        # app_id=2: completed AFTER enforcement start → should count
        snapshot_after = {
            **snapshot_game(app_id=2),
            "unlocked_achievements": 10,
            "achievements": [_ach(after_ts)] * 10,
        }
        # app_id=3: completed BEFORE enforcement start → should NOT count
        snapshot_before = {
            **snapshot_game(app_id=3),
            "unlocked_achievements": 10,
            "achievements": [_ach(before_ts)] * 10,
        }
        snapshot = [snapshot_game(app_id=1), snapshot_after, snapshot_before]
        entry = times_entry(snapshot_game())
        captured: dict[str, int] = {}

        def capture_pace(_state: object, _remaining: object, games_done: int) -> None:
            """Test capture pace."""
            captured["games_done"] = games_done

        with cmd_stats_env(
            snapshot,
            ([entry], 0, 0, 0),
            _print_pace_scenario={"side_effect": capture_pace},
            _print_worst_example={},
        ):
            cmd_stats(stats_config(), state)
        assert captured["games_done"] == 1  # only the post-start game

    def test_player_speed_scenario_called_with_pace_and_totals(self) -> None:
        """_print_player_speed_scenario receives pace, rush_total, and leisure_total."""
        state = State()
        snapshot = [snapshot_game()]
        entry = times_entry(snapshot[0])
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.1,
            ratio_vs_leisure=0.4,
            interpolation_t=0.05,
            player_style="rush_to_leisure",
        )
        captured: dict[str, object] = {}

        def capture_player_speed(p: object, rush: float, leisure: float) -> None:
            """Test capture player speed."""
            captured["pace"] = p
            captured["rush"] = rush
            captured["leisure"] = leisure

        with cmd_stats_env(
            snapshot,
            ([entry], 0, 0, 0),
            compute_pace_vs_hltb={"return_value": pace},
            _print_player_speed_scenario={"side_effect": capture_player_speed},
            _print_worst_example={},
        ):
            cmd_stats(stats_config(), state)
        assert captured["pace"] is pace
        assert captured["rush"] == 15.0
        assert captured["leisure"] == 25.0
