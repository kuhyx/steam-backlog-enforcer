"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from steam_backlog_enforcer._stats import (
    _GameTimes,
    cmd_stats,
)
from steam_backlog_enforcer._web_dataset import PaceVsHLTB
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.protondb import ProtonDBRating
from steam_backlog_enforcer.steam_api import GameInfo

_PKG = "steam_backlog_enforcer._stats"


def _game(
    app_id: int = 1,
    name: str = "G",
    hours: float = 10.0,
    total: int = 10,
    unlocked: int = 0,
) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
        comp_100_count=5,
        count_comp=20,
    )


def _unplayable_rating(app_id: int) -> ProtonDBRating:
    return ProtonDBRating(app_id=app_id, tier="borked")


class TestCmdStatsGroup2:
    """Tests for cmd_stats."""

    def _config(self) -> Config:
        """Test config."""
        return Config(steam_api_key="k", steam_id="i")

    def _snapshot_game(self, app_id: int = 1, hours: float = 20.0) -> dict[str, object]:
        """Test snapshot game."""
        return {
            "app_id": app_id,
            "name": f"Game{app_id}",
            "total_achievements": 10,
            "unlocked_achievements": 0,
            "playtime_minutes": 60,
            "completionist_hours": hours,
            "comp_100_count": 5,
            "count_comp": 20,
        }

    def _run_cmd_stats(
        self,
        state: State,
        hltb_skip: int = 0,
        linux_skip: int = 0,
        no_data_skip: int = 0,
    ) -> list[str]:
        """Test run cmd stats."""
        snapshot = [self._snapshot_game()]
        game = GameInfo.from_snapshot(snapshot[0])
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
        echoed: list[str] = []
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], hltb_skip, linux_skip, no_data_skip),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
        ):
            cmd_stats(self._config(), state)
        return echoed

    def test_refilter_called_when_ensure_rush_data_returns_true(self) -> None:
        """_filter_qualifying_games called twice when _ensure_rush_data returns True."""
        state = State()
        snapshot = [self._snapshot_game()]
        game = GameInfo.from_snapshot(snapshot[0])
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
        filter_calls: list[int] = []

        def count_filter(
            _games: object, _state: object
        ) -> tuple[list[_GameTimes], int, int, int]:
            """Test count filter."""
            filter_calls.append(1)
            return [entry], 0, 0, 0

        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{_PKG}._filter_qualifying_games", side_effect=count_filter),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._ensure_rush_data", return_value=True),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo"),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert len(filter_calls) == 2

    def test_games_done_since_start_passed_to_pace(self) -> None:
        """_print_pace_scenario gets only games completed after started_at."""

        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        state = State(enforcement_started_at=started.isoformat())

        after_ts = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())
        before_ts = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp())

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
            **self._snapshot_game(app_id=2),
            "unlocked_achievements": 10,
            "achievements": [_ach(after_ts)] * 10,
        }
        # app_id=3: completed BEFORE enforcement start → should NOT count
        snapshot_before = {
            **self._snapshot_game(app_id=3),
            "unlocked_achievements": 10,
            "achievements": [_ach(before_ts)] * 10,
        }
        snapshot = [self._snapshot_game(app_id=1), snapshot_after, snapshot_before]
        game = GameInfo.from_snapshot(self._snapshot_game())
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
        captured: dict[str, int] = {}

        def capture_pace(_state: object, _remaining: object, games_done: int) -> None:
            """Test capture pace."""
            captured["games_done"] = games_done

        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo"),
            patch(f"{_PKG}._print_pace_scenario", side_effect=capture_pace),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert captured["games_done"] == 1  # only the post-start game

    def test_player_speed_scenario_called_with_pace_and_totals(self) -> None:
        """_print_player_speed_scenario receives pace, rush_total, and leisure_total."""
        state = State()
        snapshot = [self._snapshot_game()]
        game = GameInfo.from_snapshot(snapshot[0])
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
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

        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}.compute_pace_vs_hltb", return_value=pace),
            patch(
                f"{_PKG}._print_player_speed_scenario",
                side_effect=capture_player_speed,
            ),
            patch(f"{_PKG}._echo"),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert captured["pace"] is pace
        assert captured["rush"] == 15.0
        assert captured["leisure"] == 25.0
