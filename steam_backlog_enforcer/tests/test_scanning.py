"""Tests for scanning module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from python_pkg.steam_backlog_enforcer.config import Config, State
from python_pkg.steam_backlog_enforcer.protondb import ProtonDBRating
from python_pkg.steam_backlog_enforcer.scanning import (
    _pick_playable_candidate,
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
                "python_pkg.steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("python_pkg.steam_backlog_enforcer.scanning._echo"),
            patch(
                "python_pkg.steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
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
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id == 1


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
