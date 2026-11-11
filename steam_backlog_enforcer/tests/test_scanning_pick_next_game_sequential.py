"""Tests for scanning module (part 3): TestPickNextGame continued."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.scanning import pick_next_game
from steam_backlog_enforcer.tests._scanning_games import (
    first_candidate,
    make_config,
    make_game,
    pick_env,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from steam_backlog_enforcer.steam_api import GameInfo


@contextmanager
def _sequential_env(
    echoed: list[str],
    playable: Callable[[list[GameInfo]], GameInfo | None] = first_candidate,
) -> Iterator[None]:
    """Patch the on_select path: assign echo recorded, no prompt, no disk."""
    with (
        patch("steam_backlog_enforcer.config._atomic_write"),
        pick_env(
            echo=("_scanning_assign",),
            echoed=echoed,
            answers=None,
            playable=playable,
        ),
    ):
        yield


class TestPickNextGameSequential:
    """Tests for the on_select sequential branch of pick_next_game."""

    def test_on_select_accepts_pick(self) -> None:
        """Test on select accepts pick."""
        g1 = make_game(app_id=1, name="G1", hours=5.0)
        config = make_config()
        state = State()
        echoed: list[str] = []
        with _sequential_env(echoed):
            pick_next_game([g1], state, config, on_select=lambda _g: True)
        assert state.current_app_id == 1

    def test_on_select_rejection_records_skip_and_picks_next(self) -> None:
        """Test on select rejection records skip and picks next."""
        g1 = make_game(app_id=1, name="G1", hours=5.0)
        g2 = make_game(app_id=2, name="G2", hours=6.0)
        config = make_config()
        state = State()
        echoed: list[str] = []
        calls: list[int] = []

        def on_select(game: GameInfo) -> bool:
            """Test on select."""
            calls.append(game.app_id)
            return game.app_id == 2  # reject g1, accept g2

        with _sequential_env(echoed):
            pick_next_game([g1, g2], state, config, on_select=on_select)

        assert calls == [1, 2]
        assert state.current_app_id == 2
        assert "1" in state.skipped_until
        assert any("Skipped G1 for 7 days" in line for line in echoed)

    def test_on_select_no_candidates(self) -> None:
        """Sequential branch with no candidates keeps the current game."""
        complete = make_game(app_id=1, hours=1.0, total=10, unlocked=10)
        config = make_config()
        state = State(current_app_id=99, current_game_name="X")
        echoed: list[str] = []
        with _sequential_env(echoed):
            pick_next_game([complete], state, config, on_select=lambda _g: True)
        assert state.current_app_id == 99

    def test_on_select_no_playable_branch(self) -> None:
        """Sequential branch when all candidates lack Linux compatibility."""
        g1 = make_game(app_id=1, name="G1", hours=5.0)
        config = make_config()
        state = State()
        echoed: list[str] = []
        with _sequential_env(echoed, playable=lambda _c: None):
            pick_next_game([g1], state, config, on_select=lambda _g: True)
        assert state.current_app_id is None
        assert any("No playable games" in line for line in echoed)

    def test_on_select_no_confidence_branch(self) -> None:
        """Sequential branch when all candidates fail HLTB confidence."""
        g1 = make_game(app_id=1, name="G1", hours=5.0)
        g1.comp_100_count = 0
        g1.count_comp = 0
        config = make_config()
        state = State()
        echoed: list[str] = []
        with (
            patch(
                "steam_backlog_enforcer._scanning_confidence._refresh_candidate_confidence",
            ),
            _sequential_env(echoed),
        ):
            pick_next_game([g1], state, config, on_select=lambda _g: True)
        assert state.current_app_id is None
        assert any("No assignable games" in line for line in echoed)

    def test_enforcement_started_at_not_overwritten_when_set(self) -> None:
        """enforcement_started_at is preserved when already populated."""
        g1 = make_game(app_id=1, name="G1", hours=5.0)
        config = make_config()
        existing_ts = "2024-01-01T00:00:00+00:00"
        state = State(enforcement_started_at=existing_ts)
        with _sequential_env([]):
            pick_next_game([g1], state, config, on_select=lambda _g: True)
        assert state.current_app_id == 1
        assert state.enforcement_started_at == existing_ts
