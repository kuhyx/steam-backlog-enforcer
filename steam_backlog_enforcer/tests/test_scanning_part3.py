"""Tests for scanning module (part 3): TestPickNextGame continued."""

from __future__ import annotations

import contextlib
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


class TestPickNextGame:
    """Tests for pick_next_game (continued from test_scanning.py)."""

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
                "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence",
                side_effect=refresh_side_effect,
            ) as mock_refresh,
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
                "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence_batch"
            ) as mock_refresh_batch,
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
            pick_next_game([low, fallback], state, config)

        assert state.current_app_id == 2
        mock_refresh_batch.assert_not_called()

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
            nonlocal protondb_call_count
            protondb_call_count += 1
            return c[0] if c else None

        config = Config(steam_api_key="k", steam_id="i")
        state = State()

        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=playable_side_effect,
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
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "steam_backlog_enforcer.scanning._echo",
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
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "steam_backlog_enforcer.scanning._echo",
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
            patch("builtins.input", side_effect=["99", "1"]),
        ):
            pick_next_game([g1], state, config)
        assert state.current_app_id == 1
        assert any("Out of range" in line for line in echoed)


class TestPickNextGameSequential:
    """Tests for the on_select sequential branch of pick_next_game."""

    @staticmethod
    def _common_patches(echoed: list[str]) -> contextlib.ExitStack:
        stack = contextlib.ExitStack()
        stack.enter_context(
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            )
        )
        stack.enter_context(
            patch(
                "steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            )
        )
        stack.enter_context(
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            )
        )
        stack.enter_context(
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            )
        )
        stack.enter_context(
            patch("steam_backlog_enforcer.config._atomic_write")
        )
        return stack

    def test_on_select_accepts_pick(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=5.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []
        with self._common_patches(echoed):
            pick_next_game([g1], state, config, on_select=lambda _g: True)
        assert state.current_app_id == 1

    def test_on_select_rejection_records_skip_and_picks_next(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=5.0)
        g2 = _game(app_id=2, name="G2", hours=6.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []
        calls: list[int] = []

        def on_select(game: GameInfo) -> bool:
            calls.append(game.app_id)
            return game.app_id == 2  # reject g1, accept g2

        with self._common_patches(echoed):
            pick_next_game([g1, g2], state, config, on_select=on_select)

        assert calls == [1, 2]
        assert state.current_app_id == 2
        assert "1" in state.skipped_until
        assert any("Skipped G1 for 7 days" in line for line in echoed)

    def test_on_select_no_candidates(self) -> None:
        """Sequential branch with no candidates clears state."""
        complete = _game(app_id=1, hours=1.0, total=10, unlocked=10)
        config = Config(steam_api_key="k", steam_id="i")
        state = State(current_app_id=99, current_game_name="X")
        echoed: list[str] = []
        with self._common_patches(echoed):
            pick_next_game([complete], state, config, on_select=lambda _g: True)
        assert state.current_app_id is None

    def test_on_select_no_playable_branch(self) -> None:
        """Sequential branch when all candidates lack Linux compatibility."""
        g1 = _game(app_id=1, name="G1", hours=5.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=None,
            ),
            patch(
                "steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch("steam_backlog_enforcer.config._atomic_write"),
        ):
            pick_next_game([g1], state, config, on_select=lambda _g: True)
        assert state.current_app_id is None
        assert any("No playable games" in line for line in echoed)

    def test_on_select_no_confidence_branch(self) -> None:
        """Sequential branch when all candidates fail HLTB confidence."""
        g1 = _game(app_id=1, name="G1", hours=5.0)
        g1.comp_100_count = 0
        g1.count_comp = 0
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []
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
                "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence",
            ),
            patch("steam_backlog_enforcer.config._atomic_write"),
        ):
            pick_next_game([g1], state, config, on_select=lambda _g: True)
        assert state.current_app_id is None
        assert any("No assignable games" in line for line in echoed)

    def test_enforcement_started_at_not_overwritten_when_set(self) -> None:
        """enforcement_started_at is preserved when already populated."""
        g1 = _game(app_id=1, name="G1", hours=5.0)
        config = Config(steam_api_key="k", steam_id="i")
        existing_ts = "2024-01-01T00:00:00+00:00"
        state = State(enforcement_started_at=existing_ts)
        with self._common_patches([]):
            pick_next_game([g1], state, config, on_select=lambda _g: True)
        assert state.current_app_id == 1
        assert state.enforcement_started_at == existing_ts
