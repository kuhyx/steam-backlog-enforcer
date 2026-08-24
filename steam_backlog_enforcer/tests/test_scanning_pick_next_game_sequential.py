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


class TestPickNextGameSequential:
    """Tests for the on_select sequential branch of pick_next_game."""

    @staticmethod
    def _common_patches(echoed: list[str]) -> contextlib.ExitStack:
        """Test common patches."""
        stack = contextlib.ExitStack()
        stack.enter_context(
            patch(
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            )
        )
        stack.enter_context(
            patch(
                "steam_backlog_enforcer._scanning_assign._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            )
        )
        stack.enter_context(
            patch(
                "steam_backlog_enforcer._scanning_assign.is_game_installed",
                return_value=True,
            )
        )
        stack.enter_context(
            patch(
                "steam_backlog_enforcer._scanning_assign.uninstall_other_games",
                return_value=0,
            )
        )
        stack.enter_context(patch("steam_backlog_enforcer.config._atomic_write"))
        return stack

    def test_on_select_accepts_pick(self) -> None:
        """Test on select accepts pick."""
        g1 = _game(app_id=1, name="G1", hours=5.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []
        with self._common_patches(echoed):
            pick_next_game([g1], state, config, on_select=lambda _g: True)
        assert state.current_app_id == 1

    def test_on_select_rejection_records_skip_and_picks_next(self) -> None:
        """Test on select rejection records skip and picks next."""
        g1 = _game(app_id=1, name="G1", hours=5.0)
        g2 = _game(app_id=2, name="G2", hours=6.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        echoed: list[str] = []
        calls: list[int] = []

        def on_select(game: GameInfo) -> bool:
            """Test on select."""
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
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                return_value=None,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign._echo",
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
                "steam_backlog_enforcer._scanning_candidates._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "steam_backlog_enforcer._scanning_assign._echo",
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
