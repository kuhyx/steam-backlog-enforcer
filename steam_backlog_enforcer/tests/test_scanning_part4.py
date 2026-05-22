"""Scanning tests (part 4): collect_top_candidates, do_check, confidence."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from python_pkg.steam_backlog_enforcer._scanning_confidence import (
    _filter_hltb_confident_candidates,
    _force_refresh_candidate_confidence,
    _refresh_candidate_confidence_batch,
)
from python_pkg.steam_backlog_enforcer.config import Config, State
from python_pkg.steam_backlog_enforcer.scanning import (
    _collect_top_candidates,
    _pick_next_shortest_candidate,
    do_check,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo


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


class TestCollectTopCandidates:
    """Tests for _collect_top_candidates."""

    def test_collects_up_to_n(self) -> None:
        """Returns at most n qualified candidates."""
        games = [_game(app_id=i, name=f"G{i}", hours=float(i)) for i in range(1, 6)]
        with patch(
            "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
            side_effect=lambda c: c[0] if c else None,
        ):
            qualified, conf_skip, linux_skip = _collect_top_candidates(games, n=3)
        assert len(qualified) == 3
        assert [g.app_id for g in qualified] == [1, 2, 3]
        assert conf_skip == 0
        assert linux_skip == 0

    def test_skips_linux_incompatible(self) -> None:
        """Games failing ProtonDB are counted in linux_skipped."""
        g1 = _game(app_id=1, name="Borked", hours=1.0)
        g2 = _game(app_id=2, name="Good", hours=2.0)
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: None if c[0].app_id == 1 else c[0],
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
        ):
            qualified, conf_skip, linux_skip = _collect_top_candidates([g1, g2], n=10)
        assert [g.app_id for g in qualified] == [2]
        assert linux_skip == 1
        assert conf_skip == 0

    def test_empty_candidates(self) -> None:
        qualified, conf_skip, linux_skip = _collect_top_candidates([])
        assert qualified == []
        assert conf_skip == 0
        assert linux_skip == 0

    def test_no_linux_skip_message_when_zero(self) -> None:
        """No skip message is printed when linux_skipped is 0."""
        g = _game(app_id=1, name="Good", hours=1.0)
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo") as mock_echo,
        ):
            _collect_top_candidates([g], n=10)
        mock_echo.assert_not_called()


class TestDoCheck:
    """Tests for do_check."""

    def test_no_assignment(self) -> None:
        with patch("python_pkg.steam_backlog_enforcer.scanning._echo") as mock_echo:
            do_check(Config(), State())
            mock_echo.assert_called()

    def test_fetch_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = None
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch("python_pkg.steam_backlog_enforcer.scanning.detect_tampering"),
        ):
            state = State(current_app_id=440, current_game_name="TF2")
            do_check(Config(steam_api_key="k", steam_id="i"), state)


class TestConfidenceHelpers:
    """Coverage-focused tests for scanning confidence helper branches."""

    def test_force_refresh_candidate_confidence_delegates(self) -> None:
        game = _game(app_id=10, name="A")
        with patch(
            "python_pkg.steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence_batch",
        ) as mock_batch:
            _force_refresh_candidate_confidence(game)
        mock_batch.assert_called_once_with([game], force=True)

    def test_refresh_candidate_confidence_batch_no_missing_skips_fetch(self) -> None:
        game = _game(app_id=20, name="B", hours=12.0)
        game.comp_100_count = 3
        game.count_comp = 15
        with patch(
            "python_pkg.steam_backlog_enforcer._scanning_confidence.fetch_hltb_confidence_cached",
        ) as mock_fetch:
            _refresh_candidate_confidence_batch([game], force=False)
        mock_fetch.assert_not_called()

    def test_refresh_candidate_confidence_batch_preserves_existing_hours(self) -> None:
        game = _game(app_id=30, name="C", hours=9.5)
        game.comp_100_count = 0
        game.count_comp = 0
        with (
            patch(
                "python_pkg.steam_backlog_enforcer._scanning_confidence.load_hltb_cache",
                side_effect=[{30: 9.5}, {30: -1.0}],
            ),
            patch(
                "python_pkg.steam_backlog_enforcer._scanning_confidence.load_hltb_polls_cache",
                return_value={30: 0},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer._scanning_confidence.load_hltb_count_comp_cache",
                return_value={30: 0},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer._scanning_confidence.fetch_hltb_confidence_cached",
                return_value={30: -1.0},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer._scanning_confidence.save_hltb_cache",
            ) as mock_save,
        ):
            _refresh_candidate_confidence_batch([game], force=True)

        assert game.completionist_hours == 9.5
        saved_cache = mock_save.call_args.args[0]
        assert saved_cache[30] == 9.5

    def test_filter_hltb_confident_candidates_skips_low_confidence(self) -> None:
        low = _game(app_id=40, name="Low", hours=2.0)
        low.comp_100_count = 1
        low.count_comp = 2
        with (
            patch(
                "python_pkg.steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence_batch",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer._scanning_confidence._echo"
            ) as mock_echo,
        ):
            result = _filter_hltb_confident_candidates([low])
        assert result == []
        assert mock_echo.called

    def test_pick_next_shortest_candidate_logs_skipped_unplayable_batches(self) -> None:
        bad = _game(app_id=50, name="Bad", hours=1.0)
        good = _game(app_id=51, name="Good", hours=2.0)
        bad.comp_100_count = 3
        bad.count_comp = 15
        good.comp_100_count = 3
        good.count_comp = 15

        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=[None, good],
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo") as mock_echo,
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

    def test_pick_next_shortest_candidate_no_echo_when_linux_skipped_zero(
        self,
    ) -> None:
        """Covers 419->423: no echo printed when linux_skipped == 0."""
        good = _game(app_id=51, name="Good", hours=2.0)
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=good,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo") as mock_echo,
        ):
            picked, _skipped_low_conf, skipped_linux = _pick_next_shortest_candidate(
                [good],
            )
        assert picked is good
        assert skipped_linux == 0
        mock_echo.assert_not_called()

    def test_pick_next_shortest_candidate_skips_low_confidence(self) -> None:
        """Covers lines 413-414: confidence_skipped += 1; continue."""
        low_conf = _game(app_id=10, name="Low", hours=1.0)
        low_conf.comp_100_count = 0
        low_conf.count_comp = 0
        with (
            patch(
                "python_pkg.steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence"
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
        ):
            picked, skipped_low_conf, skipped_linux = _pick_next_shortest_candidate(
                [low_conf],
            )
        assert picked is None
        assert skipped_low_conf == 1
        assert skipped_linux == 0

    def test_pick_next_shortest_candidate_all_protondb_fail(self) -> None:
        """Covers lines 426-428: linux_skipped > 0 after loop, return None."""
        g1 = _game(app_id=10, name="Borked", hours=1.0)
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo") as mock_echo,
        ):
            picked, _skipped_low_conf, skipped_linux = _pick_next_shortest_candidate(
                [g1],
            )
        assert picked is None
        assert skipped_linux == 1
        assert any(
            "Skipped 1 game(s) with poor Linux compatibility" in str(call)
            for call in mock_echo.call_args_list
        )

        game = _game(app_id=440, name="TF2", total=5, unlocked=5)
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        snap = [game.to_snapshot()]
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.send_notification",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.load_snapshot",
                return_value=snap,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.pick_next_game",
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning.detect_tampering"),
        ):
            state = State(current_app_id=440, current_game_name="TF2")
            do_check(Config(steam_api_key="k", steam_id="i"), state)
            assert 440 in state.finished_app_ids

    def test_complete_no_snapshot(self) -> None:
        game = _game(app_id=440, name="TF2", total=5, unlocked=5)
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.send_notification",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.load_snapshot",
                return_value=None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning.detect_tampering"),
        ):
            state = State(current_app_id=440, current_game_name="TF2")
            do_check(Config(steam_api_key="k", steam_id="i"), state)

    def test_not_complete(self) -> None:
        game = _game(app_id=440, name="TF2", total=10, unlocked=5)
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch("python_pkg.steam_backlog_enforcer.scanning.detect_tampering"),
        ):
            state = State(current_app_id=440, current_game_name="TF2")
            do_check(Config(steam_api_key="k", steam_id="i"), state)
