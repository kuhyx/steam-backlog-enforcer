"""A released game stays playable until the user explicitly picks another.

Covers the state upgrade, the allowed set, abandoning and pick order under
the "one new achievement" rule (tampering: ``test_release_tampering``).
"""

from __future__ import annotations

import json
from unittest.mock import patch

from steam_backlog_enforcer import config as config_mod
from steam_backlog_enforcer._actions import (
    allowed_app_ids,
    apply_manual_pick,
    is_manual_pick_locked,
)
from steam_backlog_enforcer._allowed_games import drop_inactive_picks
from steam_backlog_enforcer._config_groups import AssignmentTimes
from steam_backlog_enforcer._manual_pick_lifecycle import abandon_manual_pick
from steam_backlog_enforcer._scanning_assign import _open_candidates
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.tests._main_helpers import EXPIRED_AT, STARTED_AT
from steam_backlog_enforcer.tests._release_helpers import (
    game,
    pick,
    write_state,
)


class TestLoadBackfill:
    """Loading old state backfills assignment times and saves once."""

    def test_plain_assignment_is_stamped_once_and_persisted(self) -> None:
        """A plain assignment gets one timestamp that later loads keep."""
        write_state({"current_app_id": 5, "current_game_name": "G5"})
        first = State.load()
        assert first.assignment.current_assigned_at
        assert (
            State.load().assignment.current_assigned_at
            == first.assignment.current_assigned_at
        )
        assert first.assignment.last_assigned_at == {
            "5": first.assignment.current_assigned_at
        }

    def test_current_pick_keeps_its_pick_time(self) -> None:
        """An assigned pick is timed from when it was picked."""
        write_state({"current_app_id": 5, "manual_picks": [pick(5), pick(6)]})
        state = State.load()
        assert state.assignment.current_assigned_at == STARTED_AT
        assert state.assignment.last_assigned_at == {"5": STARTED_AT, "6": STARTED_AT}

    def test_legacy_pick_migration_is_persisted(self) -> None:
        """A legacy single-pick state is migrated and written back."""
        write_state({"manual_pick_app_id": 9, "manual_pick_started_at": ""})
        State.load()
        saved = json.loads(config_mod.STATE_FILE.read_text(encoding="utf-8"))
        assert saved["manual_picks"][0]["app_id"] == 9
        assert saved["manual_pick_app_id"] is None

    def test_up_to_date_state_is_not_rewritten(self) -> None:
        """State that needs no upgrade is never rewritten."""
        write_state({"current_app_id": None})
        with patch.object(State, "save") as mock_save:
            State.load()
        mock_save.assert_not_called()


class TestReleasedPicksStayPlayable:
    """Released and expired picks stay playable but no longer lock."""

    def test_released_and_expired_picks_stay_allowed_but_unlocked(self) -> None:
        """Released and expired picks are allowed but leave nothing locked."""
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
        """An explicit choice drops released picks and keeps active ones."""
        state = State(manual_picks=[pick(2, released_at=STARTED_AT), pick(3)])
        dropped = drop_inactive_picks(state)
        assert [p["app_id"] for p in dropped] == [2]
        assert [p["app_id"] for p in state.manual_picks] == [3]

    def test_new_manual_pick_keeps_released_ones(self) -> None:
        """A new manual pick leaves earlier released picks playable."""
        state = State(current_app_id=2, manual_picks=[pick(2, released_at=STARTED_AT)])
        with patch.object(State, "save"):
            assert apply_manual_pick(state, 4, "G4", max_picks=1) is None
        assert allowed_app_ids(state) == {2, 4}
        assert (
            state.assignment.current_assigned_at == state.manual_picks[-1]["started_at"]
        )

    def test_released_pick_can_be_abandoned(self) -> None:
        """A released pick can be abandoned and the active pick takes over."""
        state = State(
            current_app_id=2, manual_picks=[pick(2, released_at="R"), pick(3)]
        )
        with patch.object(State, "save"):
            assert abandon_manual_pick(state, 2) is True
        # The active pick inherits the assignment, timed from its pick.
        assert (state.current_app_id, state.assignment.current_assigned_at) == (
            3,
            STARTED_AT,
        )

    def test_abandoning_the_last_pick_clears_the_assignment(self) -> None:
        """Abandoning the only pick clears the assignment."""
        state = State(
            current_app_id=2,
            assignment=AssignmentTimes(current_assigned_at="T"),
            manual_picks=[pick(2)],
        )
        with patch.object(State, "save"):
            abandon_manual_pick(state, 2)
        assert (state.current_app_id, state.assignment.current_assigned_at) == (
            None,
            "",
        )


class TestPickOrder:
    """Candidates are ordered by least recent assignment, then length."""

    def test_least_recently_assigned_first_then_shortest(self) -> None:
        """Never-assigned games come first, then the oldest assignment."""
        state = State(
            assignment=AssignmentTimes(
                last_assigned_at={
                    "1": "2026-09-01T00:00:00+00:00",
                    "2": "2026-08-01T00:00:00+00:00",
                }
            )
        )
        games = [game(1, hours=1.0), game(2, hours=2.0), game(3, hours=9.0)]
        with patch(
            "steam_backlog_enforcer._scanning_assign"
            "._apply_cached_confidence_to_candidates"
        ):
            order = [g.app_id for g in _open_candidates(games, state)]
        assert order == [3, 2, 1]
