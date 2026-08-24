"""Tests for the stdout-free, state-only cores in ``_actions``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from steam_backlog_enforcer import _actions, _allowed_games
from steam_backlog_enforcer._actions import (
    abandon_manual_pick,
    active_manual_picks,
    allowed_app_ids,
    allowed_games,
    apply_manual_pick,
    find_manual_pick,
    is_manual_pick_locked,
    manual_pick_slots_left,
)
from steam_backlog_enforcer.config import State


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _pick(app_id: int = 440, name: str = "TF2", days_ago: float = 1.0) -> dict:
    return {
        "app_id": app_id,
        "game_name": name,
        "started_at": _iso_days_ago(days_ago),
    }


class TestAbandonManualPick:
    """Tests for Abandon Manual Pick."""

    def _state(self, *, picks: list[dict] | None = None) -> State:
        """Test state."""
        picks = picks if picks is not None else [_pick()]
        return State(
            manual_picks=picks,
            current_app_id=picks[-1]["app_id"],
            current_game_name=picks[-1]["game_name"],
        )

    def test_clears_lock_and_assignment(self) -> None:
        """Test clears lock and assignment."""
        state = self._state()
        assert abandon_manual_pick(state, 440) is True
        assert state.manual_picks == []
        assert state.current_app_id is None
        assert state.current_game_name == ""
        assert is_manual_pick_locked(state) is False

    def test_records_cooldown(self) -> None:
        """Test records cooldown."""
        state = self._state()
        abandon_manual_pick(state, 440)
        expiry = datetime.fromisoformat(state.skipped_until["440"])
        expected = datetime.now(timezone.utc) + timedelta(
            days=_actions.ABANDON_COOLDOWN_DAYS
        )
        assert abs((expiry - expected).total_seconds()) < 60

    def test_persists_to_disk(self) -> None:
        """Test persists to disk."""
        abandon_manual_pick(self._state(), 440)
        assert State.load().manual_picks == []

    def test_refuses_after_grace_and_leaves_state_untouched(self) -> None:
        """Test refuses after grace and leaves state untouched."""
        state = self._state(
            picks=[_pick(days_ago=_actions.MANUAL_GRACE_DAYS + 1)],
        )
        assert abandon_manual_pick(state, 440) is False
        assert [p["app_id"] for p in state.manual_picks] == [440]
        assert state.current_app_id == 440
        assert state.skipped_until == {}

    def test_other_pick_survives_and_takes_the_assignment(self) -> None:
        # The whole point of multi-pick: abandoning one keeps the other locked.
        """Test other pick survives and takes the assignment."""
        state = self._state(picks=[_pick(440, "TF2"), _pick(620, "Portal 2")])
        assert abandon_manual_pick(state, 620) is True
        assert [p["app_id"] for p in state.manual_picks] == [440]
        assert state.current_app_id == 440
        assert state.current_game_name == "TF2"
        assert is_manual_pick_locked(state) is True

    def test_keeps_unrelated_assignment(self) -> None:
        # A pick that is not the current assignment must not clear it.
        """Test keeps unrelated assignment."""
        state = self._state(picks=[_pick(440, "TF2")])
        state.current_app_id = 70
        state.current_game_name = "Half-Life"
        abandon_manual_pick(state, 440)
        assert state.current_app_id == 70
        assert state.current_game_name == "Half-Life"


class TestActiveManualPicksAndAllowedSet:
    """Tests for Active Manual Picks And Allowed Set."""

    def test_finished_pick_drops_out(self) -> None:
        """Test finished pick drops out."""
        state = State(manual_picks=[_pick(440)], finished_app_ids=[440])
        assert active_manual_picks(state) == []
        assert is_manual_pick_locked(state) is False

    def test_expired_pick_drops_out(self) -> None:
        """Test expired pick drops out."""
        state = State(
            manual_picks=[_pick(days_ago=_allowed_games.MANUAL_LOCK_DAYS + 1)],
        )
        assert active_manual_picks(state) == []

    def test_missing_timestamp_stays_active(self) -> None:
        # No deadline to evaluate → stay locked (safe answer for an enforcer).
        """Test missing timestamp stays active."""
        state = State(manual_picks=[{"app_id": 440, "game_name": "TF2"}])
        assert len(active_manual_picks(state)) == 1

    def test_malformed_timestamp_stays_active(self) -> None:
        """Test malformed timestamp stays active."""
        state = State(
            manual_picks=[
                {"app_id": 440, "game_name": "TF2", "started_at": "not-a-date"}
            ]
        )
        assert len(active_manual_picks(state)) == 1

    def test_entry_without_app_id_is_ignored(self) -> None:
        """Test entry without app id is ignored."""
        state = State(manual_picks=[{"game_name": "Corrupt"}])
        assert active_manual_picks(state) == []

    def test_allowed_set_unions_picks_and_assignment(self) -> None:
        """Test allowed set unions picks and assignment."""
        state = State(
            manual_picks=[_pick(440, "TF2"), _pick(620, "Portal 2")],
            current_app_id=70,
            current_game_name="Half-Life",
        )
        assert allowed_app_ids(state) == {70, 440, 620}
        assert allowed_games(state)[0] == (70, "Half-Life")

    def test_allowed_set_deduplicates_assignment(self) -> None:
        """Test allowed set deduplicates assignment."""
        state = State(
            manual_picks=[_pick(440, "TF2")],
            current_app_id=440,
            current_game_name="TF2",
        )
        assert allowed_app_ids(state) == {440}
        assert allowed_games(state) == [(440, "TF2")]

    def test_empty_state_allows_nothing(self) -> None:
        """Test empty state allows nothing."""
        assert allowed_app_ids(State()) == set()
        assert allowed_games(State()) == []

    def test_find_manual_pick(self) -> None:
        """Test find manual pick."""
        state = State(manual_picks=[_pick(440, "TF2")])
        found = find_manual_pick(state, 440)
        assert found is not None
        assert found["game_name"] == "TF2"
        assert find_manual_pick(state, 999) is None


class TestApplyManualPickCap:
    """Tests for Apply Manual Pick Cap."""

    def test_appends_second_pick(self) -> None:
        """Test appends second pick."""
        state = State(manual_picks=[_pick(440, "TF2")])
        assert apply_manual_pick(state, 620, "Portal 2", max_picks=2) is None
        assert [p["app_id"] for p in state.manual_picks] == [440, 620]
        # Newest pick becomes the assignment.
        assert state.current_app_id == 620

    def test_refuses_beyond_cap(self) -> None:
        """Test refuses beyond cap."""
        state = State(manual_picks=[_pick(440, "TF2"), _pick(620, "Portal 2")])
        refused = apply_manual_pick(state, 70, "Half-Life", max_picks=2)
        assert refused is not None
        assert "cap is 2" in refused
        assert len(state.manual_picks) == 2

    def test_refuses_duplicate_pick(self) -> None:
        """Test refuses duplicate pick."""
        state = State(manual_picks=[_pick(440, "TF2")])
        refused = apply_manual_pick(state, 440, "TF2", max_picks=2)
        assert refused is not None
        assert "already one of your manual picks" in refused

    def test_prunes_finished_entries(self) -> None:
        """Test prunes finished entries."""
        state = State(manual_picks=[_pick(440, "TF2")], finished_app_ids=[440])
        assert apply_manual_pick(state, 620, "Portal 2", max_picks=2) is None
        assert [p["app_id"] for p in state.manual_picks] == [620]

    def test_slots_left(self) -> None:
        """Test slots left."""
        state = State(manual_picks=[_pick(440, "TF2")])
        assert manual_pick_slots_left(state, 2) == 1
        assert manual_pick_slots_left(state, 1) == 0
