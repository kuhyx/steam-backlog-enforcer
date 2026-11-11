"""Tests for scanning module."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.game_uninstall import uninstall_other_games
from steam_backlog_enforcer.scanning import (
    pick_next_game,
)
from steam_backlog_enforcer.tests._main_helpers import STARTED_AT
from steam_backlog_enforcer.tests._scanning_games import (
    make_config,
    make_game,
    pick_env,
)

_CONF_ECHO = ("scanning", "_scanning_confidence")


class TestPickNextGame:
    """Tests for pick_next_game."""

    def test_picks_shortest(self) -> None:
        """Test picks shortest."""
        g1 = make_game(app_id=1, name="Long", hours=100.0)
        g2 = make_game(app_id=2, name="Short", hours=10.0)
        state = State()
        with pick_env(echo=_CONF_ECHO):
            pick_next_game([g1, g2], state, make_config())
            assert state.current_app_id == 2

    def test_no_candidates(self) -> None:
        """Test no candidates."""
        g1 = make_game(app_id=1, total=5, unlocked=5)
        state = State()
        with patch("steam_backlog_enforcer.scanning._echo"):
            pick_next_game([g1], state, make_config())
            assert state.current_app_id is None

    def test_skips_finished(self) -> None:
        """Test skips finished."""
        g1 = make_game(app_id=1, name="G1", hours=10.0)
        g2 = make_game(app_id=2, name="G2", hours=20.0)
        state = State(finished_app_ids=[1])
        with pick_env():
            pick_next_game([g1, g2], state, make_config())
            assert state.current_app_id == 2

    def test_no_playable(self) -> None:
        """Test no playable."""
        g1 = make_game(app_id=1, name="G1")
        state = State()
        with pick_env(playable=lambda _c: None):
            pick_next_game([g1], state, make_config())
            assert state.current_app_id is None

    def test_uninstalls_others(self) -> None:
        """Test uninstalls others."""
        g1 = make_game(app_id=1, name="G1", hours=10.0)
        config = make_config(uninstall_other_games=True)
        state = State()
        with pick_env(echo=_CONF_ECHO) as mocks:
            mocks.uninstall.return_value = 2
            pick_next_game([g1], state, config)
            assert state.current_app_id == 1

    def test_auto_installs(self) -> None:
        """Test auto installs."""
        g1 = make_game(app_id=1, name="G1", hours=10.0)
        config = make_config(uninstall_other_games=False)
        state = State()
        with pick_env(echo=_CONF_ECHO, installed=False) as mocks:
            pick_next_game([g1], state, config)
            mocks.install.assert_called_once()


class TestAssignUninstallsAgainstTheAllowedSet:
    """_assign_chosen_game must pass the allowed *set*, never a bare app id."""

    def test_passes_set_including_concurrent_manual_pick(self) -> None:
        """Uninstall keeps both the new assignment and an existing manual pick."""
        g = make_game(app_id=2, name="Short", hours=10.0)
        state = State(
            manual_picks=[
                {"app_id": 900, "game_name": "Pick", "started_at": STARTED_AT}
            ],
        )
        with pick_env(echo=_CONF_ECHO) as mocks:
            pick_next_game([g], state, make_config())
        (allowed,) = mocks.uninstall.call_args.args
        assert isinstance(allowed, set)
        # The new assignment survives, and so does the untouched manual pick.
        assert allowed == {2, 900}

    def test_real_uninstall_accepts_that_argument(self) -> None:
        """Guards the contract the mock above cannot: a bare int raises.

        ``uninstall_other_games`` membership-tests every installed game against
        its argument, so an int made it raise TypeError as soon as anything was
        installed. The suite hid that because no games are installed by default.
        """
        with (
            patch(
                "steam_backlog_enforcer.game_uninstall.get_installed_games",
                return_value=[(2, "Short"), (900, "Pick"), (55, "Other")],
            ),
            patch(
                "steam_backlog_enforcer.game_uninstall.is_protected_app",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.game_uninstall.uninstall_game",
                return_value=True,
            ) as mock_rm,
        ):
            assert uninstall_other_games({2, 900}) == 1
        assert [c.args[0] for c in mock_rm.call_args_list] == [55]

        # Typed as Any so the wrong-type call is a runtime check, not a
        # suppressed type error.
        bare_app_id: Any = 2
        with (
            patch(
                "steam_backlog_enforcer.game_uninstall.get_installed_games",
                return_value=[(2, "Short")],
            ),
            patch("steam_backlog_enforcer.game_uninstall.uninstall_game"),
            pytest.raises(TypeError),
        ):
            uninstall_other_games(bare_app_id)
