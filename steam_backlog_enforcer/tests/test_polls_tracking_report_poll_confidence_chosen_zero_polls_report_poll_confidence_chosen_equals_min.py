"""Tests for HLTB poll-count tracking — scanning integration (part 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._scanning_confidence import (
    _filter_hltb_confident_candidates,
    _refresh_candidate_confidence,
)
from steam_backlog_enforcer.tests._polls_helpers import (
    FETCH_CONFIDENCE,
    SCANCONF,
    hltb_cache_patched,
    make_game,
    poll_confidence_echoes,
    poll_state,
    write_cache,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestScanningPollsIntegrationGroup2Group2:
    """Tests for Scanning Polls Integration Group2."""

    def test_report_poll_confidence_chosen_equals_min(self) -> None:
        """Covers scanning.py 301->304: chosen_polls >= min_polls, no warning."""
        chosen = make_game(1, "Chosen", polls=(5, 0))
        old = make_game(2, "Old", unlocked=10)
        echoed = poll_confidence_echoes(
            chosen, [chosen, old], {1: 5, 2: 5}, poll_state([2], current=1)
        )
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)

    def test_refresh_candidate_confidence_noop_when_present(self) -> None:
        """Test refresh candidate confidence noop when present."""
        game = make_game(1, "Known", unlocked=1, polls=(3, 15))
        with patch(FETCH_CONFIDENCE) as mock_fetch:
            _refresh_candidate_confidence(game)
        mock_fetch.assert_not_called()

    def test_refresh_candidate_confidence_backfills_zeroes(
        self, tmp_path: Path
    ) -> None:
        """Test refresh candidate confidence backfills zeroes."""
        cache_file = write_cache(
            tmp_path, {"1": {"hours": 4.0, "polls": 0, "count_comp": 0}}
        )
        game = make_game(1, "NeedsRefresh", unlocked=1)

        def fake_fetch(
            games: list[tuple[int, str]],
            cache: dict[int, float],
            polls: dict[int, int],
            count_comp: dict[int, int],
            **_kw: object,
        ) -> list[object]:
            """Test fake search: write into the caches it is handed."""
            del games
            cache[1], polls[1], count_comp[1] = 4.0, 3, 15
            return []

        with (
            hltb_cache_patched(cache_file, tmp_path, fake_fetch),
            patch(f"{SCANCONF}._echo"),
        ):
            _refresh_candidate_confidence(game)

        assert game.comp_100_count == 3
        assert game.count_comp == 15

    def test_filter_hltb_confidence_batches_refreshes(self, tmp_path: Path) -> None:
        """Filtering refreshes missing confidence in one batched cache lookup."""
        cache_file = write_cache(
            tmp_path,
            {
                "1": {"hours": 4.0, "polls": 0, "count_comp": 0},
                "2": {"hours": 5.0, "polls": 0, "count_comp": 0},
            },
        )
        game_a = make_game(1, "A", unlocked=1)
        game_b = make_game(2, "B", unlocked=1)

        def fake_fetch(
            games: list[tuple[int, str]],
            cache: dict[int, float],
            polls: dict[int, int],
            count_comp: dict[int, int],
            **_kw: object,
        ) -> list[object]:
            """Test fake search: write into the caches it is handed."""
            assert sorted(games) == [(1, "A"), (2, "B")]
            cache[1], polls[1], count_comp[1] = 4.0, 3, 15
            cache[2], polls[2], count_comp[2] = 5.0, 3, 15
            return []

        with (
            hltb_cache_patched(cache_file, tmp_path, fake_fetch) as mock_fetch,
            patch(f"{SCANCONF}._echo"),
        ):
            kept = _filter_hltb_confident_candidates([game_a, game_b])

        assert [game.app_id for game in kept] == [1, 2]
        mock_fetch.assert_called_once()
