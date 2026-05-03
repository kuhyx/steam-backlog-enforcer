"""Tests for scanning module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from python_pkg.steam_backlog_enforcer.config import Config, State
from python_pkg.steam_backlog_enforcer.protondb import ProtonDBRating
from python_pkg.steam_backlog_enforcer.scanning import (
    _filter_hltb_confident_candidates,
    _force_refresh_candidate_confidence,
    _pick_next_shortest_candidate,
    _pick_playable_candidate,
    _refresh_candidate_confidence_batch,
    do_check,
    do_scan,
    pick_next_game,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from collections.abc import Callable


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


class TestDoScan:
    """Tests for do_scan."""

    def test_scans_and_picks(self) -> None:
        game = _game(app_id=440, name="TF2", total=10, unlocked=5)
        mock_client = MagicMock()

        def build_game_list(
            skip_app_ids: object = None,
            progress_callback: Callable[..., object] | None = None,
        ) -> list[GameInfo]:
            # Trigger progress callback to cover those lines.
            if progress_callback:
                progress_callback(50, 100)
                progress_callback(100, 100)
            return [game]

        mock_client.build_game_list.side_effect = build_game_list
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.fetch_hltb_times_cached",
                side_effect=lambda _games, progress_cb=None: (
                    progress_cb(1, 1, 1, "TF2") if progress_cb else None,
                    {440: 20.0},
                )[1],
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.save_snapshot",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.pick_next_game",
            ) as mock_pick,
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._echo",
            ),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State()
            result = do_scan(config, state)
            assert len(result) == 1
            mock_pick.assert_called_once()

    def test_scan_all_complete(self) -> None:
        game = _game(app_id=440, name="TF2", total=10, unlocked=10)
        mock_client = MagicMock()

        def build_game_list(
            skip_app_ids: object = None,
            progress_callback: Callable[..., object] | None = None,
        ) -> list[GameInfo]:
            if progress_callback:
                # current=1, total=2 → not %50 and not ==total → covers False branch
                progress_callback(1, 2)
            return [game]

        mock_client.build_game_list.side_effect = build_game_list
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.save_snapshot",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.pick_next_game",
            ) as mock_pick,
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State()
            result = do_scan(config, state)
            assert len(result) == 1
            mock_pick.assert_called_once()

    def test_scan_already_assigned(self) -> None:
        game = _game(app_id=440, total=10, unlocked=5)
        mock_client = MagicMock()
        mock_client.build_game_list.return_value = [game]
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.fetch_hltb_times_cached",
                return_value={440: 20.0},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.save_snapshot",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.pick_next_game",
            ) as mock_pick,
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State(current_app_id=440)
            result = do_scan(config, state)
            assert len(result) == 1
            mock_pick.assert_not_called()


class TestPickPlayableCandidate:
    """Tests for _pick_playable_candidate."""

    def test_finds_playable(self) -> None:
        game = _game(app_id=440, name="TF2")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    440: ProtonDBRating(app_id=440, tier="gold"),
                },
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
        ):
            result = _pick_playable_candidate([game])
            assert result is not None
            assert result.app_id == 440

    def test_skips_bad_rating(self) -> None:
        bad = _game(app_id=1, name="Bad")
        good = _game(app_id=2, name="Good")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    1: ProtonDBRating(app_id=1, tier="borked"),
                    2: ProtonDBRating(app_id=2, tier="platinum"),
                },
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
        ):
            result = _pick_playable_candidate([bad, good])
            assert result is not None
            assert result.app_id == 2

    def test_all_unplayable(self) -> None:
        game = _game(app_id=1, name="Bad")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    1: ProtonDBRating(app_id=1, tier="borked"),
                },
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
        ):
            assert _pick_playable_candidate([game]) is None

    def test_empty_list(self) -> None:
        assert _pick_playable_candidate([]) is None

    def test_first_in_batch_playable(self) -> None:
        """First game in first batch is playable — no skip message."""
        game = _game(app_id=440, name="TF2")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    440: ProtonDBRating(app_id=440, tier="platinum"),
                },
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
        ):
            result = _pick_playable_candidate([game])
            assert result is not None


class TestPickNextGame:
    """Tests for pick_next_game."""

    def test_picks_shortest(self) -> None:
        g1 = _game(app_id=1, name="Long", hours=100.0)
        g2 = _game(app_id=2, name="Short", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._force_refresh_candidate_confidence"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
        ):
            pick_next_game([g1, g2], state, config)
            assert state.current_app_id == 2

    def test_no_candidates(self) -> None:
        g1 = _game(app_id=1, total=5, unlocked=5)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with patch("python_pkg.steam_backlog_enforcer.scanning._echo"):
            pick_next_game([g1], state, config)
            assert state.current_app_id is None

    def test_skips_finished(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=10.0)
        g2 = _game(app_id=2, name="G2", hours=20.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State(finished_app_ids=[1])
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
        ):
            pick_next_game([g1, g2], state, config)
            assert state.current_app_id == 2

    def test_no_playable(self) -> None:
        g1 = _game(app_id=1, name="G1")
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id is None

    def test_uninstalls_others(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i", uninstall_other_games=True)
        state = State()
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._force_refresh_candidate_confidence"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=2,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id == 1

    def test_auto_installs(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i", uninstall_other_games=False)
        state = State()
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._force_refresh_candidate_confidence"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.install_game"
            ) as mock_install,
        ):
            pick_next_game([g1], state, config)
            mock_install.assert_called_once()

    def test_unknown_hours(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=-1)
        g2 = _game(app_id=2, name="G2", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
        ):
            pick_next_game([g1, g2], state, config)
            assert state.current_app_id == 2

    def test_picks_game_no_hours(self) -> None:
        """Chosen game has no HLTB hours — covers no-hours output branch."""
        g1 = _game(app_id=1, name="G1", hours=-1)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id == 1

    def test_skips_low_confidence_and_picks_next(self) -> None:
        low = _game(app_id=1, name="LowConfidence", hours=1.0)
        low.comp_100_count = 1
        low.count_comp = 5
        valid = _game(app_id=2, name="ValidConfidence", hours=2.0)
        valid.comp_100_count = 3
        valid.count_comp = 15
        echoed: list[str] = []
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._force_refresh_candidate_confidence"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
        ):
            pick_next_game([low, valid], state, config)
        assert state.current_app_id == 2
        assert any("Skipping LowConfidence" in line for line in echoed)
        assert any("comp_100 polls 1 < 3" in line for line in echoed)

    def test_all_candidates_filtered_by_confidence(self) -> None:
        low_a = _game(app_id=1, name="LowA", hours=1.0)
        low_a.comp_100_count = 2
        low_a.count_comp = 15
        low_b = _game(app_id=2, name="LowB", hours=2.0)
        low_b.comp_100_count = 3
        low_b.count_comp = 14
        echoed: list[str] = []
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._force_refresh_candidate_confidence"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=None,
            ) as mock_pick,
        ):
            pick_next_game([low_a, low_b], state, config)
        assert state.current_app_id is None
        mock_pick.assert_not_called()
        assert any("No assignable games found" in line for line in echoed)

    def test_zero_confidence_is_refreshed_before_skipping(self) -> None:
        """Missing confidence fields are refreshed once before final skip decision."""
        stale = _game(app_id=1, name="Celeste", hours=1.0)
        stale.comp_100_count = 0
        stale.count_comp = 0
        fallback = _game(app_id=2, name="Fallback", hours=2.0)

        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []

        def refresh_side_effect(game: GameInfo) -> None:
            if game.app_id == 1:
                game.comp_100_count = 899
                game.count_comp = 14055

        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._refresh_candidate_confidence",
                side_effect=refresh_side_effect,
            ) as mock_refresh,
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
        ):
            pick_next_game([stale, fallback], state, config)

        assert state.current_app_id == 1
        mock_refresh.assert_called_once_with(stale)
        assert not any("Skipping Celeste" in line for line in echoed)

    def test_nonzero_low_confidence_does_not_force_refetch(self) -> None:
        """Non-zero low-confidence entries are skipped using cached values."""
        low = _game(app_id=1, name="Low", hours=1.0)
        low.comp_100_count = 1
        low.count_comp = 8
        fallback = _game(app_id=2, name="Fallback", hours=2.0)

        config = Config(steam_api_key="k", steam_id="i")
        state = State()

        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._refresh_candidate_confidence_batch"
            ) as mock_refresh_batch,
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
        ):
            pick_next_game([low, fallback], state, config)

        assert state.current_app_id == 2
        mock_refresh_batch.assert_not_called()

    def test_stops_after_first_confident_assignment(self) -> None:
        """Only candidates up to the winning one are checked/skipped."""
        low = _game(app_id=1, name="Low", hours=1.0)
        low.comp_100_count = 1
        low.count_comp = 2
        good = _game(app_id=2, name="Good", hours=2.0)
        good.comp_100_count = 10
        good.count_comp = 50
        never_checked = _game(app_id=3, name="NeverChecked", hours=3.0)
        never_checked.comp_100_count = 0
        never_checked.count_comp = 0

        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []

        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._refresh_candidate_confidence"
            ) as mock_refresh,
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
        ):
            pick_next_game([low, good, never_checked], state, config)

        assert state.current_app_id == 2
        mock_refresh.assert_called_once_with(low)
        assert any("Skipping Low" in line for line in echoed)
        assert not any("Skipping NeverChecked" in line for line in echoed)


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
            "python_pkg.steam_backlog_enforcer.scanning._refresh_candidate_confidence_batch",
        ) as mock_batch:
            _force_refresh_candidate_confidence(game)
        mock_batch.assert_called_once_with([game], force=True)

    def test_refresh_candidate_confidence_batch_no_missing_skips_fetch(self) -> None:
        game = _game(app_id=20, name="B", hours=12.0)
        game.comp_100_count = 3
        game.count_comp = 15
        with patch(
            "python_pkg.steam_backlog_enforcer.scanning.fetch_hltb_confidence_cached",
        ) as mock_fetch:
            _refresh_candidate_confidence_batch([game], force=False)
        mock_fetch.assert_not_called()

    def test_refresh_candidate_confidence_batch_preserves_existing_hours(self) -> None:
        game = _game(app_id=30, name="C", hours=9.5)
        game.comp_100_count = 0
        game.count_comp = 0
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.load_hltb_cache",
                side_effect=[{30: 9.5}, {30: -1.0}],
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.load_hltb_polls_cache",
                return_value={30: 0},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.load_hltb_count_comp_cache",
                return_value={30: 0},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.fetch_hltb_confidence_cached",
                return_value={30: -1.0},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.save_hltb_cache",
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
                "python_pkg.steam_backlog_enforcer.scanning._refresh_candidate_confidence_batch",
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo") as mock_echo,
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

    def test_complete(self) -> None:
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
