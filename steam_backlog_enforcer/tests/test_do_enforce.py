"""Tests for the do_enforce driver loop.

Split to keep every test file under the 250-line cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._enforce_loop import (
    do_enforce,
)
from steam_backlog_enforcer.config import Config, State

if TYPE_CHECKING:
    from collections.abc import Iterator

PKG = "steam_backlog_enforcer._enforce_loop"
ENFORCE_STEPS_PKG = "steam_backlog_enforcer._enforce_steps"


class TestDoEnforce:
    """Tests for do_enforce."""

    @pytest.fixture(autouse=True)
    def _steam_present(self) -> Iterator[None]:
        """Pretend Steam is installed for every test in this class.

        Without it do_enforce takes the "not installed" branch and never
        reaches the normal enforcement path these tests are about. The
        absent case is covered by test_steam_absent_idles_without_setup,
        which opts back out.
        """
        with patch(f"{PKG}.steam_is_installed", return_value=True):
            yield

    def test_no_game_says_so_but_keeps_looping(self) -> None:
        """No assignment is reported, but the loop still runs.

        The daily gaming budget is accounted for from inside this loop, so
        returning here would stop enforcing it whenever a game is finished
        but not yet rescanned.
        """
        state = State()
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch.object(State, "load", return_value=state),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=KeyboardInterrupt,
            ) as mock_iter,
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(Config(), state)
        assert any("No game" in str(c) for c in mock_echo.call_args_list)
        mock_iter.assert_called_once()

    def test_steam_absent_idles_without_setup(self) -> None:
        """With Steam gone, say so and keep looping - never exit.

        Returning here would end the process, and under Restart=always that
        is the crash loop again by another name. Staying alive also lets a
        later reinstall be picked up without a restart.
        """
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_total_block_active", return_value=False),
            patch(f"{PKG}.steam_is_installed", return_value=False),
            patch(f"{PKG}._enforce_setup") as mock_setup,
            patch(f"{PKG}._echo") as mock_echo,
            patch.object(State, "load", return_value=state),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=KeyboardInterrupt,
            ),
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(Config(), state)

        mock_setup.assert_not_called()
        assert any("not installed" in str(c) for c in mock_echo.call_args_list)

    def test_keyboard_interrupt(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        config = Config()
        fresh = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}._enforce_setup"),
            patch(f"{PKG}._echo"),
            patch.object(State, "load", return_value=fresh),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=KeyboardInterrupt,
            ),
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(config, state)

    def test_runs_iterations(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        config = Config()
        fresh = State(current_app_id=1, current_game_name="G")
        call_count = 0

        def side_effect(*_args: object, **_kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt

        with (
            patch(f"{PKG}._enforce_setup"),
            patch(f"{PKG}._echo"),
            patch.object(State, "load", return_value=fresh),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=side_effect,
            ),
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(config, state)
            assert call_count == 2

    def test_state_load_failure_continues(self) -> None:
        """Corrupt state file should not crash the daemon."""
        import json as json_mod

        state = State(current_app_id=1, current_game_name="G")
        config = Config()
        call_count = 0

        def load_side_effect() -> State:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "bad"
                raise json_mod.JSONDecodeError(msg, "", 0)
            if call_count == 2:
                raise KeyboardInterrupt
            return State(current_app_id=1)  # pragma: no cover

        with (
            patch(f"{PKG}._enforce_setup"),
            patch(f"{PKG}._echo"),
            patch.object(State, "load", side_effect=load_side_effect),
            patch(f"{PKG}._enforce_loop_iteration") as mock_iter,
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(config, state)
            mock_iter.assert_not_called()
