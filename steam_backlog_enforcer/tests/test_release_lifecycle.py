"""A released game stays playable until the user explicitly picks another.

Covers the state upgrade, the allowed set, abandoning, pick order, tampering
and the ``check`` command under the "one new achievement" rule.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import config as config_mod
from steam_backlog_enforcer._actions import (
    allowed_app_ids,
    apply_manual_pick,
    is_manual_pick_locked,
)
from steam_backlog_enforcer._allowed_games import drop_inactive_picks
from steam_backlog_enforcer._manual_pick_lifecycle import abandon_manual_pick
from steam_backlog_enforcer._scanning_assign import _open_candidates
from steam_backlog_enforcer._scanning_tampering import _check_game_tampering
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import do_check
from steam_backlog_enforcer.steam_api import AchievementInfo, GameInfo
from steam_backlog_enforcer.tests._main_helpers import EXPIRED_AT, STARTED_AT

RELEASED = datetime(2026, 9, 20, tzinfo=UTC)


def pick(app_id: int, **extra: str) -> dict[str, object]:
    """Build one manual-pick entry started a day ago."""
    return {
        "app_id": app_id,
        "game_name": f"G{app_id}",
        "started_at": STARTED_AT,
    } | dict(extra.items())


def game(app_id: int, *unlock_times: int, hours: float = 5.0) -> GameInfo:
    """Build a GameInfo with one unlocked achievement per epoch given."""
    return GameInfo(
        app_id=app_id,
        name=f"G{app_id}",
        total_achievements=10,
        unlocked_achievements=len(unlock_times),
        playtime_minutes=60,
        completionist_hours=hours,
        achievements=[
            AchievementInfo(f"a{t}", f"A{t}", achieved=True, unlock_time=t)
            for t in unlock_times
        ],
    )


def write_state(data: dict[str, object]) -> None:
    """Write raw JSON to the (conftest-redirected) state file."""
    config_mod.STATE_FILE.write_text(json.dumps(data), encoding="utf-8")


class TestLoadBackfill:
    def test_plain_assignment_is_stamped_once_and_persisted(self) -> None:
        write_state({"current_app_id": 5, "current_game_name": "G5"})
        first = State.load()
        assert first.current_assigned_at
        assert State.load().current_assigned_at == first.current_assigned_at
        assert first.last_assigned_at == {"5": first.current_assigned_at}

    def test_current_pick_keeps_its_pick_time(self) -> None:
        write_state({"current_app_id": 5, "manual_picks": [pick(5), pick(6)]})
        state = State.load()
        assert state.current_assigned_at == STARTED_AT
        assert state.last_assigned_at == {"5": STARTED_AT, "6": STARTED_AT}

    def test_legacy_pick_migration_is_persisted(self) -> None:
        write_state({"manual_pick_app_id": 9, "manual_pick_started_at": ""})
        State.load()
        saved = json.loads(config_mod.STATE_FILE.read_text(encoding="utf-8"))
        assert saved["manual_picks"][0]["app_id"] == 9
        assert saved["manual_pick_app_id"] is None

    def test_up_to_date_state_is_not_rewritten(self) -> None:
        write_state({"current_app_id": None})
        with patch.object(State, "save") as mock_save:
            State.load()
        mock_save.assert_not_called()


class TestReleasedPicksStayPlayable:
    def test_released_and_expired_picks_stay_allowed_but_unlocked(self) -> None:
        state = State(
            current_app_id=1,
            manual_picks=[
                pick(2, released_at=STARTED_AT),
                pick(3) | {"started_at": EXPIRED_AT},
            ],
        )
        assert allowed_app_ids(state) == {1, 2, 3}
        assert is_manual_pick_locked(state) is False

    def test_explicit_choice_drops_only_inactive_picks(self) -> None:
        state = State(manual_picks=[pick(2, released_at=STARTED_AT), pick(3)])
        dropped = drop_inactive_picks(state)
        assert [p["app_id"] for p in dropped] == [2]
        assert [p["app_id"] for p in state.manual_picks] == [3]

    def test_new_manual_pick_replaces_released_ones(self) -> None:
        state = State(current_app_id=2, manual_picks=[pick(2, released_at=STARTED_AT)])
        with patch.object(State, "save"):
            assert apply_manual_pick(state, 4, "G4", max_picks=1) is None
        assert allowed_app_ids(state) == {4}
        assert state.current_assigned_at == state.manual_picks[0]["started_at"]

    def test_released_pick_can_be_abandoned(self) -> None:
        state = State(
            current_app_id=2, manual_picks=[pick(2, released_at="R"), pick(3)]
        )
        with patch.object(State, "save"):
            assert abandon_manual_pick(state, 2) is True
        # The active pick inherits the assignment, timed from its pick.
        assert (state.current_app_id, state.current_assigned_at) == (3, STARTED_AT)

    def test_abandoning_the_last_pick_clears_the_assignment(self) -> None:
        state = State(current_app_id=2, current_assigned_at="T", manual_picks=[pick(2)])
        with patch.object(State, "save"):
            abandon_manual_pick(state, 2)
        assert (state.current_app_id, state.current_assigned_at) == (None, "")


class TestPickOrder:
    def test_least_recently_assigned_first_then_shortest(self) -> None:
        state = State(
            last_assigned_at={
                "1": "2026-09-01T00:00:00+00:00",
                "2": "2026-08-01T00:00:00+00:00",
            }
        )
        games = [game(1, hours=1.0), game(2, hours=2.0), game(3, hours=9.0)]
        with patch(
            "steam_backlog_enforcer._scanning_assign"
            "._apply_cached_confidence_to_candidates"
        ):
            order = [g.app_id for g in _open_candidates(games, state)]
        assert order == [3, 2, 1]


class TestTamperingAfterRelease:
    def entry(self) -> dict[str, object]:
        return {
            "app_id": 7,
            "name": "G7",
            "total_achievements": 10,
            "unlocked_achievements": 0,
            "playtime_minutes": 60,
        }

    def check(self, *unlock_times: int) -> tuple[str, int, int] | None:
        client = MagicMock()
        client.refresh_single_game.return_value = game(7, *unlock_times)
        state = State(current_app_id=1, released_at={"7": RELEASED.isoformat()})
        return _check_game_tampering(client, self.entry(), state)

    def test_unlocks_earned_while_assigned_are_legitimate(self) -> None:
        before = int((RELEASED - timedelta(hours=1)).timestamp())
        assert self.check(before, before) is None

    def test_unlocks_after_release_are_flagged(self) -> None:
        before = int((RELEASED - timedelta(hours=1)).timestamp())
        after = int((RELEASED + timedelta(hours=1)).timestamp())
        assert self.check(before, after) == ("G7", 7, 1)

    def test_unreadable_game_is_not_flagged(self) -> None:
        client = MagicMock()
        client.refresh_single_game.return_value = None
        assert _check_game_tampering(client, self.entry(), State()) is None


class TestCheckCommand:
    def run_check(self, state: State, refreshed: GameInfo) -> MagicMock:
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
        state = State(current_app_id=7, current_assigned_at=RELEASED.isoformat())
        after = int((RELEASED + timedelta(hours=1)).timestamp())
        self.run_check(state, game(7, after))
        assert "7" in state.released_at
        assert state.finished_app_ids == []
        # No snapshot, so no replacement: the game stays assigned.
        assert state.current_app_id == 7

    def test_no_new_achievement_changes_nothing(self) -> None:
        state = State(current_app_id=7, current_assigned_at=RELEASED.isoformat())
        before = int((RELEASED - timedelta(hours=1)).timestamp())
        mock_pick = self.run_check(state, game(7, before))
        assert state.released_at == {}
        mock_pick.assert_not_called()
