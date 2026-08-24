"""Tests for scanning module."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import (
    pick_next_game,
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


class TestPickNextGame:
    """Tests for pick_next_game."""

    def test_picks_shortest(self) -> None:
        """Test picks shortest."""
        g1 = _game(app_id=1, name="Long", hours=100.0)
        g2 = _game(app_id=2, name="Short", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch("steam_backlog_enforcer._scanning_confidence._echo"),
            patch(
                "steam_backlog_enforcer._scanning_assign.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1, g2], state, config)
            assert state.current_app_id == 2

    def test_no_candidates(self) -> None:
        """Test no candidates."""
        g1 = _game(app_id=1, total=5, unlocked=5)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with patch("steam_backlog_enforcer.scanning._echo"):
            pick_next_game([g1], state, config)
            assert state.current_app_id is None

    def test_skips_finished(self) -> None:
        """Test skips finished."""
        g1 = _game(app_id=1, name="G1", hours=10.0)
        g2 = _game(app_id=2, name="G2", hours=20.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State(finished_app_ids=[1])
        with (
            patch(
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch(
                "steam_backlog_enforcer._scanning_assign.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1, g2], state, config)
            assert state.current_app_id == 2

    def test_no_playable(self) -> None:
        """Test no playable."""
        g1 = _game(app_id=1, name="G1")
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                return_value=None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id is None

    def test_uninstalls_others(self) -> None:
        """Test uninstalls others."""
        g1 = _game(app_id=1, name="G1", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i", uninstall_other_games=True)
        state = State()
        with (
            patch(
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch("steam_backlog_enforcer._scanning_confidence._echo"),
            patch(
                "steam_backlog_enforcer._scanning_assign.uninstall_other_games",
                return_value=2,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign.is_game_installed",
                return_value=True,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id == 1

    def test_auto_installs(self) -> None:
        """Test auto installs."""
        g1 = _game(app_id=1, name="G1", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i", uninstall_other_games=False)
        state = State()
        with (
            patch(
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch("steam_backlog_enforcer._scanning_confidence._echo"),
            patch(
                "steam_backlog_enforcer._scanning_assign.is_game_installed",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign.install_game"
            ) as mock_install,
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1], state, config)
            mock_install.assert_called_once()
