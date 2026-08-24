"""Scanning tests (part 4): collect_top_candidates, do_check, confidence."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._scanning_confidence import (
    _filter_hltb_confident_candidates,
    _force_refresh_candidate_confidence,
    _refresh_candidate_confidence_batch,
)
from steam_backlog_enforcer.scanning import (
    _pick_next_shortest_candidate,
)
from steam_backlog_enforcer.steam_api import GameInfo


def _game(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 0,
    hours: float = -1,
) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
        comp_100_count=3,
        count_comp=15,
    )


class TestConfidenceHelpers:
    """Coverage-focused tests for scanning confidence helper branches."""

    def test_force_refresh_candidate_confidence_delegates(self) -> None:
        """Test force refresh candidate confidence delegates."""
        game = _game(app_id=10, name="A")
        with patch(
            "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence_batch",
        ) as mock_batch:
            _force_refresh_candidate_confidence(game)
        mock_batch.assert_called_once_with([game], force=True)

    def test_refresh_candidate_confidence_batch_no_missing_skips_fetch(self) -> None:
        """Test refresh candidate confidence batch no missing skips fetch."""
        game = _game(app_id=20, name="B", hours=12.0)
        game.comp_100_count = 3
        game.count_comp = 15
        with patch(
            "steam_backlog_enforcer._scanning_confidence.fetch_hltb_confidence_cached",
        ) as mock_fetch:
            _refresh_candidate_confidence_batch([game], force=False)
        mock_fetch.assert_not_called()

    def test_refresh_candidate_confidence_batch_preserves_existing_hours(self) -> None:
        """Test refresh candidate confidence batch preserves existing hours."""
        game = _game(app_id=30, name="C", hours=9.5)
        game.comp_100_count = 0
        game.count_comp = 0
        with (
            patch(
                "steam_backlog_enforcer._scanning_confidence.load_hltb_cache",
                side_effect=[{30: 9.5}, {30: -1.0}],
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence.load_hltb_polls_cache",
                return_value={30: 0},
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence.load_hltb_count_comp_cache",
                return_value={30: 0},
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence.fetch_hltb_confidence_cached",
                return_value={30: -1.0},
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence.save_hltb_cache",
            ) as mock_save,
        ):
            _refresh_candidate_confidence_batch([game], force=True)

        assert game.completionist_hours == 9.5
        saved_cache = mock_save.call_args.args[0]
        assert saved_cache[30] == 9.5

    def test_filter_hltb_confident_candidates_skips_low_confidence(self) -> None:
        """Test filter hltb confident candidates skips low confidence."""
        low = _game(app_id=40, name="Low", hours=2.0)
        low.comp_100_count = 1
        low.count_comp = 2
        with (
            patch(
                "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence_batch",
            ),
            patch("steam_backlog_enforcer._scanning_confidence._echo") as mock_echo,
        ):
            result = _filter_hltb_confident_candidates([low])
        assert result == []
        assert mock_echo.called

    def test_pick_next_shortest_candidate_logs_skipped_unplayable_batches(self) -> None:
        """Test pick next shortest candidate logs skipped unplayable batches."""
        bad = _game(app_id=50, name="Bad", hours=1.0)
        good = _game(app_id=51, name="Good", hours=2.0)
        bad.comp_100_count = 3
        bad.count_comp = 15
        good.comp_100_count = 3
        good.count_comp = 15

        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=[None, good],
            ),
            patch("steam_backlog_enforcer.scanning._echo") as mock_echo,
        ):
            picked, skipped_low_conf, skipped_linux = _pick_next_shortest_candidate(
                [bad, good],
            )

        assert picked is good
        assert skipped_low_conf == 0
        assert skipped_linux == 1
        assert any(
            "Skipped 1 game(s) with poor Linux compatibility" in str(call)
            for call in mock_echo.call_args_list
        )
