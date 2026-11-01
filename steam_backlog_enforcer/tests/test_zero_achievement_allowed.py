"""Owned games with zero achievements are always allowed, except by the budget."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from leisure_watch.procscan import qualifying_pids
import pytest

from steam_backlog_enforcer import config
from steam_backlog_enforcer._enforce_guards import guard_installed_games
from steam_backlog_enforcer._playtime_cutoff import _kill_set
from steam_backlog_enforcer._scanning_tampering import _legitimately_played
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.enforcer import enforce_allowed_game
from steam_backlog_enforcer.game_uninstall import (
    is_protected_app,
    uninstall_other_games,
)
from steam_backlog_enforcer.library_hider import hide_other_games
from steam_backlog_enforcer.tests._zero_ach import (
    ASSIGNED,
    SIMS3,
    WITH_ACH,
    confirm_zero,
    js_list,
    recorder,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _no_exceptions() -> Iterator[None]:
    """No approved exceptions, so only the zero-achievement rule can protect."""
    with patch(
        "steam_backlog_enforcer.game_uninstall.get_approved_exception_ids",
        return_value=frozenset(),
    ):
        yield


class TestUninstall:
    def test_zero_achievement_game_is_kept(self) -> None:
        confirm_zero(SIMS3)
        removed: list[int] = []
        with (
            patch(
                "steam_backlog_enforcer.game_uninstall.get_installed_games",
                return_value=[(SIMS3, "The Sims 3"), (WITH_ACH, "Other")],
            ),
            patch(
                "steam_backlog_enforcer.game_uninstall.uninstall_game",
                side_effect=recorder(removed),
            ),
        ):
            uninstall_other_games({ASSIGNED})
        assert removed == [WITH_ACH]

    def test_guard_keeps_it_and_removes_game_with_achievements(self) -> None:
        confirm_zero(SIMS3)
        removed: list[int] = []
        with (
            patch(
                "steam_backlog_enforcer._enforce_guards.get_installed_games",
                return_value=[(SIMS3, "The Sims 3"), (WITH_ACH, "Other")],
            ),
            patch(
                "steam_backlog_enforcer._enforce_guards.uninstall_game",
                side_effect=recorder(removed),
            ),
            patch("steam_backlog_enforcer._enforce_guards.send_notification"),
        ):
            assert guard_installed_games({ASSIGNED}) == 1
        assert removed == [WITH_ACH]


class TestHiding:
    def test_zero_achievement_game_stays_visible(self) -> None:
        confirm_zero(SIMS3)
        pkg = "steam_backlog_enforcer.library_hider"
        captured: dict[str, str] = {}

        def fake_eval(js: str) -> dict[str, object]:
            captured["js"] = js
            return {}

        with (
            patch(f"{pkg}.ensure_steam_debug_port"),
            patch(f"{pkg}._evaluate_js", side_effect=fake_eval),
            patch(f"{pkg}._cdp_result_value", return_value='{"totalHidden": 0}'),
            patch(f"{pkg}.get_approved_exception_ids", return_value=frozenset()),
        ):
            hide_other_games([SIMS3, ASSIGNED, WITH_ACH], {ASSIGNED})
        visible = js_list(r"new Set\((\[.*?\])\)", captured["js"])
        to_hide = js_list(r"const extraIds = (\[.*?\]);", captured["js"])
        assert SIMS3 in visible
        assert to_hide == [WITH_ACH]


class TestTampering:
    def test_zero_achievement_game_is_exempt(self) -> None:
        confirm_zero(SIMS3)
        with patch(
            "steam_backlog_enforcer._scanning_tampering.get_approved_exception_ids",
            return_value=frozenset(),
        ):
            exempt = _legitimately_played(State(current_app_id=ASSIGNED))
        assert SIMS3 in exempt


class TestUnauthorizedKill:
    def test_not_killed_but_other_games_are(self) -> None:
        confirm_zero(SIMS3)
        with (
            patch(
                "steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
                return_value={100: SIMS3, 200: WITH_ACH},
            ),
            patch("steam_backlog_enforcer.enforcer.kill_process") as kill,
        ):
            assert enforce_allowed_game({ASSIGNED}) == [(200, WITH_ACH)]
        kill.assert_called_once_with(200, WITH_ACH)


class TestBudgetStillApplies:
    """The playtime budget never asks is_protected_app, so it still bites."""

    def test_running_zero_game_is_counted_and_in_the_kill_set(self) -> None:
        confirm_zero(SIMS3)
        rules = MagicMock(count_launchers=False)
        with (
            patch(
                "leisure_watch.procscan._qualifying.get_running_steam_game_pids",
                return_value={100: SIMS3},
            ),
            patch(
                "steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
                return_value={100: SIMS3},
            ),
            patch(
                "steam_backlog_enforcer._playtime_cutoff.steam_and_launcher_pids",
                return_value=set(),
            ),
            patch("steam_backlog_enforcer._playtime_cutoff.config_mod") as cfg,
        ):
            cfg.CONFIG_FILE = config.CONFIG_FILE
            assert is_protected_app(SIMS3)
            assert enforce_allowed_game({ASSIGNED}) == []
            assert qualifying_pids(rules, config.CONFIG_FILE) == {100: f"app:{SIMS3}"}
            assert 100 in _kill_set(rules)
