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


class TestPickNextGameGroup2:
    """Tests for pick_next_game."""

    def test_unknown_hours(self) -> None:
        """Test unknown hours."""
        g1 = _game(app_id=1, name="G1", hours=-1)
        g2 = _game(app_id=2, name="G2", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
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
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id == 1

    def test_skips_low_confidence_and_picks_next(self) -> None:
        """Test skips low confidence and picks next."""
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
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([low, valid], state, config)
        assert state.current_app_id == 2
        assert any("Skipping LowConfidence" in line for line in echoed)
        assert any("comp_100 polls 1 < 3" in line for line in echoed)

    def test_all_candidates_filtered_by_confidence(self) -> None:
        """Test all candidates filtered by confidence."""
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
                "steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=None,
            ) as mock_pick,
        ):
            pick_next_game([low_a, low_b], state, config)
        assert state.current_app_id is None
        mock_pick.assert_not_called()
        assert any("No assignable games found" in line for line in echoed)
