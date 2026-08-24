"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._stats import (
    _GameTimes,
    cmd_stats,
)
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


class TestCmdStats:
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

    def test_no_snapshot(self) -> None:
        """Test no snapshot."""
        echoed: list[str] = []
        state = State()
        with (
            patch(f"{_PKG}.load_snapshot", return_value=None),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            cmd_stats(self._config(), state)
        assert any("No snapshot found" in s for s in echoed)

    def test_with_no_current_game(self) -> None:
        """Test with no current game."""
        state = State()
        echoed = self._run_cmd_stats(state)
        assert any("Qualifying games" in s for s in echoed)
        assert not any("Current game:" in s for s in echoed)

    def test_with_current_game(self) -> None:
        """Test with current game."""
        state = State(current_app_id=42, current_game_name="Hollow Knight")
        echoed = self._run_cmd_stats(state)
        assert any("Current game:" in s and "Hollow Knight" in s for s in echoed)

    def test_hltb_skipped_shown(self) -> None:
        """Test hltb skipped shown."""
        state = State()
        echoed = self._run_cmd_stats(state, hltb_skip=3)
        assert any("HLTB-skipped" in s for s in echoed)

    def test_linux_skipped_shown(self) -> None:
        """Test linux skipped shown."""
        state = State()
        echoed = self._run_cmd_stats(state, linux_skip=2)
        assert any("Linux-skipped" in s for s in echoed)

    def test_no_data_skipped_shown(self) -> None:
        """Test no data skipped shown."""
        state = State()
        echoed = self._run_cmd_stats(state, no_data_skip=1)
        assert any("No-data-skipped" in s for s in echoed)

    def test_zero_skips_not_shown(self) -> None:
        """Test zero skips not shown."""
        state = State()
        echoed = self._run_cmd_stats(state)
        assert not any("HLTB-skipped" in s for s in echoed)
        assert not any("Linux-skipped" in s for s in echoed)
        assert not any("No-data-skipped" in s for s in echoed)

    def test_finished_games_count_uses_snapshot_complete(self) -> None:
        """'Finished games' count uses snapshot is_complete, not finished_app_ids."""
        state = State()
        # finished_app_ids has 1 entry, but snapshot has 2 complete games — count = 2.
        state.finished_app_ids = [99]
        snapshot_complete = {
            **self._snapshot_game(app_id=2),
            "unlocked_achievements": 10,
        }
        snapshot = [self._snapshot_game(app_id=1), snapshot_complete]
        game = GameInfo.from_snapshot(self._snapshot_game())
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
        echoed: list[str] = []
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
        ):
            cmd_stats(self._config(), state)
        assert any("Finished games" in s and "1" in s for s in echoed)

    def test_detail_data_complete_message_shown(self) -> None:
        """'Detail data: ...' shown when all qualifying games have rush hours."""
        state = State()
        echoed = self._run_cmd_stats(state)
        # entry has rush_hours=15.0 > 0, so missing_rush_final == 0 and total_q == 1
        assert any("Detail data" in s for s in echoed)

    def test_note_missing_rush_shown_when_rush_absent(self) -> None:
        """'Note: X games still missing...' shown when rush_hours <= 0 after fetch."""
        state = State()
        snapshot = [self._snapshot_game()]
        game = GameInfo.from_snapshot(snapshot[0])
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=-1.0, leisure_100h=-1.0
        )
        echoed: list[str] = []
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._ensure_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert any("still missing" in s for s in echoed)

    def test_no_detail_message_when_no_qualifying_games(self) -> None:
        """Neither 'Note' nor 'Detail data' shown when qualified list is empty."""
        state = State()
        snapshot = [self._snapshot_game()]
        echoed: list[str] = []
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._ensure_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert not any("Detail data" in s for s in echoed)
        assert not any("still missing" in s for s in echoed)
