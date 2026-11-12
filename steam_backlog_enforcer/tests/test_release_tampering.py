"""Tampering checks after a game was released, and the check command."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._config_groups import AssignmentTimes
from steam_backlog_enforcer._scanning_tampering import _check_game_tampering
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import do_check
from steam_backlog_enforcer.tests._release_helpers import (
    RELEASED,
    game,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo


class TestTamperingAfterRelease:
    """Unlocks after a release are tampering; earlier ones are not."""

    def entry(self) -> dict[str, object]:
        """Return the catalogue entry for the released game."""
        return {
            "app_id": 7,
            "name": "G7",
            "total_achievements": 10,
            "unlocked_achievements": 0,
            "playtime_minutes": 60,
        }

    def check(self, *unlock_times: int) -> tuple[str, int, int] | None:
        """Run the tampering check against a refresh with these unlocks."""
        client = MagicMock()
        client.refresh_single_game.return_value = game(7, *unlock_times)
        state = State(
            current_app_id=1,
            assignment=AssignmentTimes(released_at={"7": RELEASED.isoformat()}),
        )
        return _check_game_tampering(client, self.entry(), state)

    def test_unlocks_earned_while_assigned_are_legitimate(self) -> None:
        """Unlocks earned while the game was assigned are legitimate."""
        before = int((RELEASED - timedelta(hours=1)).timestamp())
        assert self.check(before, before) is None

    def test_unlocks_after_release_are_flagged(self) -> None:
        """Unlocks made after the release are flagged as tampering."""
        before = int((RELEASED - timedelta(hours=1)).timestamp())
        after = int((RELEASED + timedelta(hours=1)).timestamp())
        assert self.check(before, after) == ("G7", 7, 1)

    def test_unreadable_game_is_not_flagged(self) -> None:
        """A game whose refresh fails is not flagged."""
        client = MagicMock()
        client.refresh_single_game.return_value = None
        assert _check_game_tampering(client, self.entry(), State()) is None


class TestCheckCommand:
    """The check command applies the one-new-achievement rule."""

    def run_check(self, state: State, refreshed: GameInfo) -> MagicMock:
        """Run do_check with every side effect patched; return the pick mock."""
        client = MagicMock()
        client.refresh_single_game.return_value = refreshed
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient", return_value=client
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch("steam_backlog_enforcer.scanning.report_completion"),
            patch("steam_backlog_enforcer.scanning.detect_tampering"),
            patch("steam_backlog_enforcer.scanning.send_notification"),
            patch("steam_backlog_enforcer.scanning.load_snapshot", return_value=[]),
            patch("steam_backlog_enforcer.scanning.pick_next_game") as mock_pick,
            patch.object(State, "save"),
        ):
            do_check(Config(), state)
        return mock_pick

    def test_new_achievement_releases_and_keeps_the_game(self) -> None:
        """A new achievement releases the game and keeps it assigned."""
        state = State(
            current_app_id=7,
            assignment=AssignmentTimes(current_assigned_at=RELEASED.isoformat()),
        )
        after = int((RELEASED + timedelta(hours=1)).timestamp())
        self.run_check(state, game(7, after))
        assert "7" in state.assignment.released_at
        assert state.finished_app_ids == []
        # No snapshot, so no replacement: the game stays assigned.
        assert state.current_app_id == 7

    def test_no_new_achievement_changes_nothing(self) -> None:
        """No new achievement leaves the state and the pick untouched."""
        state = State(
            current_app_id=7,
            assignment=AssignmentTimes(current_assigned_at=RELEASED.isoformat()),
        )
        before = int((RELEASED - timedelta(hours=1)).timestamp())
        mock_pick = self.run_check(state, game(7, before))
        assert state.assignment.released_at == {}
        mock_pick.assert_not_called()
