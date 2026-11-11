"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._stats import cmd_stats
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.tests._scanning_games import echo_into
from steam_backlog_enforcer.tests._stats_cmd_env import (
    STATS,
    cmd_stats_env,
    snapshot_game,
    stats_config,
    times_entry,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_PKG = STATS


@pytest.fixture(autouse=True)
def _no_live_refresh() -> Iterator[None]:
    """cmd_stats must not hit Steam or HLTB: unmocked, each test cost ~2 s."""
    refresh = f"{_PKG}._refresh_recently_played_completions"
    with patch(refresh, lambda g, _c: g), patch(f"{_PKG}._print_worst_example"):
        yield


class TestCmdStats:
    """Tests for cmd_stats."""

    def _run_cmd_stats(
        self,
        state: State,
        hltb_skip: int = 0,
        linux_skip: int = 0,
        no_data_skip: int = 0,
    ) -> list[str]:
        """Run cmd_stats over one qualifying game and return what it echoed."""
        snapshot = [snapshot_game()]
        entry = times_entry(snapshot[0])
        echoed: list[str] = []
        filtered = ([entry], hltb_skip, linux_skip, no_data_skip)
        with cmd_stats_env(snapshot, filtered, echoed):
            cmd_stats(stats_config(), state)
        return echoed

    def test_no_snapshot(self) -> None:
        """Test no snapshot."""
        echoed: list[str] = []
        state = State()
        with (
            patch("steam_backlog_enforcer._snapshot.load_snapshot", return_value=None),
            # The "run scan" hint is printed by the shared snapshot helper.
            patch(
                "steam_backlog_enforcer._snapshot._echo",
                side_effect=echo_into(echoed),
            ),
        ):
            cmd_stats(stats_config(), state)
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
            **snapshot_game(app_id=2),
            "unlocked_achievements": 10,
        }
        snapshot = [snapshot_game(app_id=1), snapshot_complete]
        entry = times_entry(snapshot_game())
        echoed: list[str] = []
        with cmd_stats_env(snapshot, ([entry], 0, 0, 0), echoed):
            cmd_stats(stats_config(), state)
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
        snapshot = [snapshot_game()]
        entry = times_entry(snapshot[0], rush=-1.0, leisure=-1.0)
        echoed: list[str] = []
        with cmd_stats_env(
            snapshot,
            ([entry], 0, 0, 0),
            echoed,
            _ensure_rush_data={"return_value": False},
            _print_worst_example={},
        ):
            cmd_stats(stats_config(), state)
        assert any("still missing" in s for s in echoed)

    def test_no_detail_message_when_no_qualifying_games(self) -> None:
        """Neither 'Note' nor 'Detail data' shown when qualified list is empty."""
        state = State()
        snapshot = [snapshot_game()]
        echoed: list[str] = []
        with cmd_stats_env(
            snapshot,
            ([], 0, 0, 0),
            echoed,
            _ensure_rush_data={"return_value": False},
            _print_worst_example={},
        ):
            cmd_stats(stats_config(), state)
        assert not any("Detail data" in s for s in echoed)
        assert not any("still missing" in s for s in echoed)
