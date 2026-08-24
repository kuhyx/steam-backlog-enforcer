"""Scanning tests (part 4): collect_top_candidates, do_check, confidence."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import (
    _collect_top_candidates,
    do_check,
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


class TestCollectTopCandidates:
    """Tests for _collect_top_candidates."""

    def test_collects_up_to_n(self) -> None:
        """Returns at most n qualified candidates."""
        games = [_game(app_id=i, name=f"G{i}", hours=float(i)) for i in range(1, 6)]
        with patch(
            "steam_backlog_enforcer.scanning._pick_playable_candidate",
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
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: None if c[0].app_id == 1 else c[0],
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            qualified, conf_skip, linux_skip = _collect_top_candidates([g1, g2], n=10)
        assert [g.app_id for g in qualified] == [2]
        assert linux_skip == 1
        assert conf_skip == 0

    def test_empty_candidates(self) -> None:
        """Test empty candidates."""
        qualified, conf_skip, linux_skip = _collect_top_candidates([])
        assert qualified == []
        assert conf_skip == 0
        assert linux_skip == 0

    def test_no_linux_skip_message_when_zero(self) -> None:
        """No skip message is printed when linux_skipped is 0."""
        g = _game(app_id=1, name="Good", hours=1.0)
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo") as mock_echo,
        ):
            _collect_top_candidates([g], n=10)
        mock_echo.assert_not_called()


class TestDoCheck:
    """Tests for do_check."""

    def test_no_assignment(self) -> None:
        """Test no assignment."""
        with patch("steam_backlog_enforcer.scanning._echo") as mock_echo:
            do_check(Config(), State())
            mock_echo.assert_called()

    def test_fetch_fails(self) -> None:
        """Test fetch fails."""
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = None
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch("steam_backlog_enforcer.scanning.detect_tampering"),
        ):
            state = State(current_app_id=440, current_game_name="TF2")
            do_check(Config(steam_api_key="k", steam_id="i"), state)
