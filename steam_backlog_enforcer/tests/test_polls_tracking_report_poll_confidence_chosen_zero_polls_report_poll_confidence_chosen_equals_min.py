"""Tests for HLTB poll-count tracking — scanning integration (part 2)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer import _scanning_confidence, scanning
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from pathlib import Path

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


class TestScanningPollsIntegrationGroup2Group2:
    """Tests for Scanning Polls Integration Group2."""

    def test_report_poll_confidence_chosen_equals_min(self) -> None:
        """Covers scanning.py 301->304: chosen_polls >= min_polls, no warning."""
        echoed: list[str] = []
        chosen = GameInfo(
            app_id=1,
            name="Chosen",
            total_achievements=10,
            unlocked_achievements=0,
            playtime_minutes=0,
            comp_100_count=5,
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
                return_value={1: 5, 2: 5},
            ),
            patch(
                f"{_POLLS}._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
        ):
            scanning._report_poll_confidence(
                chosen, [chosen, old], _state([2], current=1)
            )
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)

    def test_refresh_candidate_confidence_noop_when_present(self) -> None:
        """Test refresh candidate confidence noop when present."""
        game = GameInfo(
            app_id=1,
            name="Known",
            total_achievements=10,
            unlocked_achievements=1,
            playtime_minutes=0,
            comp_100_count=3,
            count_comp=15,
        )
        with patch(f"{_SCANCONF}.fetch_hltb_confidence_cached") as mock_fetch:
            _scanning_confidence._refresh_candidate_confidence(game)
        mock_fetch.assert_not_called()

    def test_refresh_candidate_confidence_backfills_zeroes(
        self, tmp_path: Path
    ) -> None:
        """Test refresh candidate confidence backfills zeroes."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"1": {"hours": 4.0, "polls": 0, "count_comp": 0}}),
            encoding="utf-8",
        )
        game = GameInfo(
            app_id=1,
            name="NeedsRefresh",
            total_achievements=10,
            unlocked_achievements=1,
            playtime_minutes=0,
            comp_100_count=0,
            count_comp=0,
        )

        def fake_fetch(_games: list[tuple[int, str]]) -> dict[int, float]:
            """Test fake fetch."""
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            data["1"] = {"hours": 4.0, "polls": 3, "count_comp": 15}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {1: 4.0}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(
                f"{_SCANCONF}.fetch_hltb_confidence_cached",
                side_effect=fake_fetch,
            ),
            patch(f"{_SCANCONF}._echo"),
        ):
            _scanning_confidence._refresh_candidate_confidence(game)

        assert game.comp_100_count == 3
        assert game.count_comp == 15

    def test_filter_hltb_confidence_batches_refreshes(self, tmp_path: Path) -> None:
        """Filtering refreshes missing confidence in one batched cache lookup."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps(
                {
                    "1": {"hours": 4.0, "polls": 0, "count_comp": 0},
                    "2": {"hours": 5.0, "polls": 0, "count_comp": 0},
                }
            ),
            encoding="utf-8",
        )
        game_a = GameInfo(
            app_id=1,
            name="A",
            total_achievements=10,
            unlocked_achievements=1,
            playtime_minutes=0,
            comp_100_count=0,
            count_comp=0,
        )
        game_b = GameInfo(
            app_id=2,
            name="B",
            total_achievements=10,
            unlocked_achievements=1,
            playtime_minutes=0,
            comp_100_count=0,
            count_comp=0,
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            """Test fake fetch."""
            assert sorted(games) == [(1, "A"), (2, "B")]
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            data["1"] = {"hours": 4.0, "polls": 3, "count_comp": 15}
            data["2"] = {"hours": 5.0, "polls": 3, "count_comp": 15}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {1: 4.0, 2: 5.0}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(
                f"{_SCANCONF}.fetch_hltb_confidence_cached",
                side_effect=fake_fetch,
            ) as mock_fetch,
            patch(f"{_SCANCONF}._echo"),
        ):
            kept = _scanning_confidence._filter_hltb_confident_candidates(
                [game_a, game_b]
            )

        assert [game.app_id for game in kept] == [1, 2]
        mock_fetch.assert_called_once()
