"""Zero-achievement "always allowed": unknown status stays enforced."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _achievement_skip as skip
from steam_backlog_enforcer import config
from steam_backlog_enforcer.enforcer import enforce_allowed_game
from steam_backlog_enforcer.game_uninstall import (
    is_protected_app,
    uninstall_other_games,
)
from steam_backlog_enforcer.tests._zero_ach import (
    ASSIGNED,
    NOW,
    SIMS3,
    STEAM_ID,
    WITH_ACH,
    confirm_zero,
    recorder,
    write,
    write_snapshot,
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


class TestFailClosed:
    def test_no_cache_file(self) -> None:
        assert not is_protected_app(SIMS3)

    def test_corrupt_cache_file(self) -> None:
        write(config.CONFIG_FILE, {"steam_id": STEAM_ID})
        skip._cache_file().write_text("{nope", encoding="utf-8")
        assert not is_protected_app(SIMS3)

    def test_cache_of_another_account(self) -> None:
        confirm_zero(SIMS3, steam_id="someone-else")
        assert not is_protected_app(SIMS3)

    def test_unknown_account(self) -> None:
        confirm_zero(SIMS3)
        config.CONFIG_FILE.unlink()
        assert not is_protected_app(SIMS3)

    def test_account_id_of_the_wrong_type(self) -> None:
        confirm_zero(SIMS3)
        write(config.CONFIG_FILE, {"steam_id": 12345})
        assert not is_protected_app(SIMS3)

    def test_unreadable_snapshot(self) -> None:
        confirm_zero(SIMS3)
        config.SNAPSHOT_FILE.write_text("{nope", encoding="utf-8")
        assert not is_protected_app(SIMS3)

    def test_answer_is_reused_until_a_file_changes(self) -> None:
        confirm_zero(SIMS3)
        with patch.object(skip, "_derive_zero_ids", wraps=skip._derive_zero_ids) as d:
            assert is_protected_app(SIMS3)
            assert is_protected_app(SIMS3)
        assert d.call_count <= 1

    def test_unconfirmed_game_is_enforced(self) -> None:
        confirm_zero(SIMS3)
        assert not is_protected_app(WITH_ACH)

    def test_game_that_gained_achievements_is_enforced(self) -> None:
        confirm_zero(SIMS3)
        write_snapshot(SIMS3)
        assert not is_protected_app(SIMS3)

    def test_unknown_status_game_is_uninstalled(self) -> None:
        removed: list[int] = []
        with (
            patch(
                "steam_backlog_enforcer.game_uninstall.get_installed_games",
                return_value=[(SIMS3, "The Sims 3")],
            ),
            patch(
                "steam_backlog_enforcer.game_uninstall.uninstall_game",
                side_effect=recorder(removed),
            ),
        ):
            uninstall_other_games({ASSIGNED})
        assert removed == [SIMS3]

    def test_unknown_status_game_is_killed(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
                return_value={100: SIMS3},
            ),
            patch("steam_backlog_enforcer.enforcer.kill_process"),
        ):
            assert enforce_allowed_game({ASSIGNED}) == [(100, SIMS3)]


class TestRecordedByScan:
    def test_a_scan_that_finds_no_achievements_allows_the_game(self) -> None:
        write(config.CONFIG_FILE, {"steam_id": STEAM_ID})
        game = {"appid": SIMS3, "has_community_visible_stats": False}
        skip.record_scan(STEAM_ID, [game], set(), NOW)
        assert is_protected_app(SIMS3)

    def test_a_later_scan_that_finds_achievements_enforces_it_again(self) -> None:
        write(config.CONFIG_FILE, {"steam_id": STEAM_ID})
        game = {"appid": SIMS3, "has_community_visible_stats": False}
        skip.record_scan(STEAM_ID, [game], set(), NOW)
        assert is_protected_app(SIMS3)
        skip.record_scan(STEAM_ID, [game], {SIMS3}, NOW + 1)
        assert not is_protected_app(SIMS3)

    def test_old_confirmation_still_counts(self) -> None:
        """Presence is enough: only a scan seeing achievements revokes it."""
        confirm_zero(SIMS3)
        write(skip._cache_file(), {"steam_id": STEAM_ID, "checked": {str(SIMS3): 1.0}})
        assert is_protected_app(SIMS3)
