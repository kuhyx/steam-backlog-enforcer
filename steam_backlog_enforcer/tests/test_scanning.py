"""Tests for scanning module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.protondb import ProtonDBRating
from steam_backlog_enforcer.scanning import (
    _pick_playable_candidate,
    do_scan,
)
from steam_backlog_enforcer.steam_api import GameInfo

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
        """Test scans and picks."""
        game = _game(app_id=440, name="TF2", total=10, unlocked=5)
        mock_client = MagicMock()

        def build_game_list(
            progress_callback: Callable[..., object] | None = None,
        ) -> list[GameInfo]:
            # Trigger progress callback to cover those lines.
            """Test build game list."""
            if progress_callback:
                progress_callback(50, 100)
                progress_callback(100, 100)
            return [game]

        mock_client.build_game_list.side_effect = build_game_list
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch(
                "steam_backlog_enforcer.scanning.fetch_hltb_times_cached",
                side_effect=lambda _games, progress_cb=None: (
                    progress_cb(1, 1, 1, "TF2") if progress_cb else None,
                    {440: 20.0},
                )[1],
            ),
            patch(
                "steam_backlog_enforcer.scanning.save_snapshot",
            ),
            patch(
                "steam_backlog_enforcer.scanning.pick_next_game",
            ) as mock_pick,
            patch(
                "steam_backlog_enforcer.scanning._echo",
            ),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State()
            result = do_scan(config, state)
            assert len(result) == 1
            mock_pick.assert_called_once()

    def test_scan_all_complete(self) -> None:
        """Test scan all complete."""
        game = _game(app_id=440, name="TF2", total=10, unlocked=10)
        mock_client = MagicMock()

        def build_game_list(
            progress_callback: Callable[..., object] | None = None,
        ) -> list[GameInfo]:
            """Test build game list."""
            if progress_callback:
                # current=1, total=2 → not %50 and not ==total → covers False branch
                progress_callback(1, 2)
            return [game]

        mock_client.build_game_list.side_effect = build_game_list
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch(
                "steam_backlog_enforcer.scanning.save_snapshot",
            ),
            patch(
                "steam_backlog_enforcer.scanning.pick_next_game",
            ) as mock_pick,
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State()
            result = do_scan(config, state)
            assert len(result) == 1
            mock_pick.assert_called_once()

    def test_scan_already_assigned(self) -> None:
        """Test scan already assigned."""
        game = _game(app_id=440, total=10, unlocked=5)
        mock_client = MagicMock()
        mock_client.build_game_list.return_value = [game]
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch(
                "steam_backlog_enforcer.scanning.fetch_hltb_times_cached",
                return_value={440: 20.0},
            ),
            patch(
                "steam_backlog_enforcer.scanning.save_snapshot",
            ),
            patch(
                "steam_backlog_enforcer.scanning.pick_next_game",
            ) as mock_pick,
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State(current_app_id=440)
            result = do_scan(config, state)
            assert len(result) == 1
            mock_pick.assert_not_called()


class TestPickPlayableCandidate:
    """Tests for _pick_playable_candidate."""

    def test_finds_playable(self) -> None:
        """Test finds playable."""
        game = _game(app_id=440, name="TF2")
        with (
            patch(
                "steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    440: ProtonDBRating(app_id=440, tier="gold"),
                },
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            result = _pick_playable_candidate([game])
            assert result is not None
            assert result.app_id == 440

    def test_skips_bad_rating(self) -> None:
        """Test skips bad rating."""
        bad = _game(app_id=1, name="Bad")
        good = _game(app_id=2, name="Good")
        with (
            patch(
                "steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    1: ProtonDBRating(app_id=1, tier="borked"),
                    2: ProtonDBRating(app_id=2, tier="platinum"),
                },
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            result = _pick_playable_candidate([bad, good])
            assert result is not None
            assert result.app_id == 2

    def test_all_unplayable(self) -> None:
        """Test all unplayable."""
        game = _game(app_id=1, name="Bad")
        with (
            patch(
                "steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    1: ProtonDBRating(app_id=1, tier="borked"),
                },
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            assert _pick_playable_candidate([game]) is None

    def test_empty_list(self) -> None:
        """Test empty list."""
        assert _pick_playable_candidate([]) is None

    def test_first_in_batch_playable(self) -> None:
        """First game in first batch is playable — no skip message."""
        game = _game(app_id=440, name="TF2")
        with (
            patch(
                "steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    440: ProtonDBRating(app_id=440, tier="platinum"),
                },
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            result = _pick_playable_candidate([game])
            assert result is not None
