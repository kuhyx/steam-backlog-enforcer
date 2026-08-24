"""Tests for scanning module (part 3): TestPickNextGame continued."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import pick_next_game
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
    """Tests for pick_next_game (continued from test_scanning.py)."""

    def test_cached_confidence_overlay_avoids_refetch_for_zero_snapshot_fields(
        self,
    ) -> None:
        """Use cached confidence before deciding whether refresh is needed."""
        low = _game(app_id=1, name="Low", hours=1.0)
        low.comp_100_count = 0
        low.count_comp = 0
        fallback = _game(app_id=2, name="Fallback", hours=2.0)
        fallback.comp_100_count = 3
        fallback.count_comp = 20

        config = Config(steam_api_key="k", steam_id="i")
        state = State()

        with (
            patch(
                "steam_backlog_enforcer._scanning_confidence.load_hltb_polls_cache",
                return_value={1: 1, 2: 3},
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence.load_hltb_count_comp_cache",
                return_value={1: 8, 2: 20},
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence_batch"
            ) as mock_refresh_batch,
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
            pick_next_game([low, fallback], state, config)

        assert state.current_app_id == 2
        mock_refresh_batch.assert_not_called()

    def test_stops_collecting_after_n_qualified(self) -> None:
        """Collection stops once _PICK_LIST_SIZE candidates are qualified."""
        # Create 11 games that all pass filters; only the first 10 should be
        # presented and the 11th should never trigger a ProtonDB call.
        games = [_game(app_id=i, name=f"G{i}", hours=float(i)) for i in range(1, 12)]
        protondb_call_count = 0

        def playable_side_effect(c: list[GameInfo]) -> GameInfo | None:
            """Test playable side effect."""
            nonlocal protondb_call_count
            protondb_call_count += 1
            return c[0] if c else None

        config = Config(steam_api_key="k", steam_id="i")
        state = State()

        with (
            patch(
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                side_effect=playable_side_effect,
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
            pick_next_game(games, state, config)

        assert state.current_app_id == 1
        assert protondb_call_count == 10

    def test_user_picks_second_candidate(self) -> None:
        """User can select a game other than the shortest one."""
        g1 = _game(app_id=1, name="Short", hours=5.0)
        g2 = _game(app_id=2, name="Medium", hours=15.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
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
            patch("builtins.input", return_value="2"),
        ):
            pick_next_game([g1, g2], state, config)
        assert state.current_app_id == 2

    def test_invalid_input_then_valid(self) -> None:
        """Non-numeric input prints error and loops until valid input."""
        g1 = _game(app_id=1, name="G1", hours=5.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []
        with (
            patch(
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", side_effect=["abc", "1"]),
        ):
            pick_next_game([g1], state, config)
        assert state.current_app_id == 1
        assert any("Invalid input" in line for line in echoed)

    def test_out_of_range_then_valid(self) -> None:
        """Out-of-range number prints error and loops until valid input."""
        g1 = _game(app_id=1, name="G1", hours=5.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []
        with (
            patch(
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", side_effect=["99", "1"]),
        ):
            pick_next_game([g1], state, config)
        assert state.current_app_id == 1
        assert any("Out of range" in line for line in echoed)
