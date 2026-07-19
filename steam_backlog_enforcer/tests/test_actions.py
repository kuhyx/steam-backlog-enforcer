"""Tests for the stdout-free, state-only cores in ``_actions``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _actions
from steam_backlog_enforcer._actions import (
    abandon_manual_pick,
    active_manual_picks,
    allowed_app_ids,
    allowed_games,
    apply_manual_pick,
    can_abandon_manual_pick,
    find_manual_pick,
    is_manual_pick_locked,
    manual_pick_grace_remaining,
    manual_pick_slots_left,
    status_payload,
)
from steam_backlog_enforcer._total_block import TotalBlockStatus
from steam_backlog_enforcer.config import State


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class TestIsManualPickLocked:
    def test_no_pick_is_unlocked(self) -> None:
        assert is_manual_pick_locked(State()) is False

    def test_finished_game_releases_lock(self) -> None:
        state = State(
            manual_picks=[{"app_id": 5, "game_name": "G", "started_at": ""}],
            finished_app_ids=[5],
        )
        assert is_manual_pick_locked(state) is False

    def test_empty_timestamp_stays_locked(self) -> None:
        # Pick set but no started_at → locked (no expiry to evaluate).
        state = State(manual_picks=[{"app_id": 5, "game_name": "G", "started_at": ""}])
        assert is_manual_pick_locked(state) is True

    def test_recent_pick_is_locked(self) -> None:
        state = State(
            manual_picks=[
                {"app_id": 5, "game_name": "G", "started_at": _iso_days_ago(1)}
            ]
        )
        assert is_manual_pick_locked(state) is True

    def test_expired_pick_releases_lock(self) -> None:
        state = State(
            manual_picks=[
                {
                    "app_id": 5,
                    "game_name": "G",
                    "started_at": _iso_days_ago(_actions.MANUAL_LOCK_DAYS + 1),
                }
            ]
        )
        assert is_manual_pick_locked(state) is False

    def test_one_active_pick_holds_the_lock_for_all(self) -> None:
        # Multi-pick: the lock only lifts when every pick is done/expired.
        state = State(
            manual_picks=[
                {"app_id": 5, "game_name": "Done", "started_at": _iso_days_ago(1)},
                {"app_id": 6, "game_name": "Live", "started_at": _iso_days_ago(1)},
            ],
            finished_app_ids=[5],
        )
        assert is_manual_pick_locked(state) is True


class TestLegacyManualPickMigration:
    """A lock written by the old single-slot code must survive the upgrade."""

    def test_legacy_pick_is_migrated_on_load(self) -> None:
        started = _iso_days_ago(1)
        State(
            manual_pick_app_id=5,
            manual_pick_game_name="Legacy",
            manual_pick_started_at=started,
        ).save()

        loaded = State.load()
        assert loaded.manual_picks == [
            {"app_id": 5, "game_name": "Legacy", "started_at": started}
        ]
        assert loaded.manual_pick_app_id is None
        assert loaded.manual_pick_game_name == ""
        assert loaded.manual_pick_started_at == ""
        assert is_manual_pick_locked(loaded) is True

    def test_new_format_is_left_alone(self) -> None:
        State(manual_picks=[{"app_id": 9, "game_name": "New", "started_at": ""}]).save()
        assert [p["app_id"] for p in State.load().manual_picks] == [9]

    def test_no_pick_needs_no_migration(self) -> None:
        State().save()
        assert State.load().manual_picks == []


class TestApplyManualPick:
    def test_sets_all_fields_and_enforcement_start(self) -> None:
        state = State()
        assert apply_manual_pick(state, 440, "Team Fortress 2") is None
        assert [p["app_id"] for p in state.manual_picks] == [440]
        assert state.manual_picks[0]["game_name"] == "Team Fortress 2"
        assert state.current_app_id == 440
        assert state.current_game_name == "Team Fortress 2"
        assert state.manual_picks[0]["started_at"] != ""
        # enforcement_started_at was empty, so it is set now.
        assert state.enforcement_started_at != ""

    def test_preserves_existing_enforcement_start(self) -> None:
        state = State(enforcement_started_at="2020-01-01T00:00:00+00:00")
        apply_manual_pick(state, 620, "Portal 2")
        assert state.enforcement_started_at == "2020-01-01T00:00:00+00:00"

    def test_persists_to_disk(self) -> None:
        state = State()
        apply_manual_pick(state, 70, "Half-Life")
        assert State.load().current_app_id == 70

    def test_default_cap_is_one(self) -> None:
        # Callers that do not opt in keep the historical single-slot behaviour.
        state = State()
        apply_manual_pick(state, 440, "TF2")
        assert apply_manual_pick(state, 620, "Portal 2") is not None


def _pick(app_id: int = 440, name: str = "TF2", days_ago: float = 1.0) -> dict:
    return {
        "app_id": app_id,
        "game_name": name,
        "started_at": _iso_days_ago(days_ago),
    }


class TestManualPickGraceRemaining:
    def test_no_pick_returns_none(self) -> None:
        assert manual_pick_grace_remaining(State(), 440) is None

    def test_unknown_app_id_returns_none(self) -> None:
        state = State(manual_picks=[_pick(440)])
        assert manual_pick_grace_remaining(state, 999) is None

    def test_missing_timestamp_returns_none(self) -> None:
        state = State(manual_picks=[{"app_id": 440, "game_name": "TF2"}])
        assert manual_pick_grace_remaining(state, 440) is None

    def test_malformed_timestamp_returns_none(self) -> None:
        state = State(
            manual_picks=[
                {"app_id": 440, "game_name": "TF2", "started_at": "not-a-date"}
            ]
        )
        assert manual_pick_grace_remaining(state, 440) is None

    def test_fresh_pick_has_almost_the_full_window(self) -> None:
        state = State(manual_picks=[_pick(days_ago=0)])
        remaining = manual_pick_grace_remaining(state, 440)
        assert remaining is not None
        assert remaining == pytest.approx(_actions.MANUAL_GRACE_DAYS, abs=0.01)

    def test_expired_window_is_negative(self) -> None:
        state = State(manual_picks=[_pick(days_ago=_actions.MANUAL_GRACE_DAYS + 1)])
        remaining = manual_pick_grace_remaining(state, 440)
        assert remaining is not None
        assert remaining == pytest.approx(-1.0, abs=0.01)


class TestCanAbandonManualPick:
    def test_inside_window(self) -> None:
        state = State(manual_picks=[_pick(days_ago=_actions.MANUAL_GRACE_DAYS - 1)])
        assert can_abandon_manual_pick(state, 440) is True

    def test_outside_window(self) -> None:
        state = State(manual_picks=[_pick(days_ago=_actions.MANUAL_GRACE_DAYS + 1)])
        assert can_abandon_manual_pick(state, 440) is False

    def test_no_pick(self) -> None:
        assert can_abandon_manual_pick(State(), 440) is False


class TestAbandonManualPick:
    def _state(self, *, picks: list[dict] | None = None) -> State:
        picks = picks if picks is not None else [_pick()]
        return State(
            manual_picks=picks,
            current_app_id=picks[-1]["app_id"],
            current_game_name=picks[-1]["game_name"],
        )

    def test_clears_lock_and_assignment(self) -> None:
        state = self._state()
        assert abandon_manual_pick(state, 440) is True
        assert state.manual_picks == []
        assert state.current_app_id is None
        assert state.current_game_name == ""
        assert is_manual_pick_locked(state) is False

    def test_records_cooldown(self) -> None:
        state = self._state()
        abandon_manual_pick(state, 440)
        expiry = datetime.fromisoformat(state.skipped_until["440"])
        expected = datetime.now(timezone.utc) + timedelta(
            days=_actions.ABANDON_COOLDOWN_DAYS
        )
        assert abs((expiry - expected).total_seconds()) < 60

    def test_persists_to_disk(self) -> None:
        abandon_manual_pick(self._state(), 440)
        assert State.load().manual_picks == []

    def test_refuses_after_grace_and_leaves_state_untouched(self) -> None:
        state = self._state(
            picks=[_pick(days_ago=_actions.MANUAL_GRACE_DAYS + 1)],
        )
        assert abandon_manual_pick(state, 440) is False
        assert [p["app_id"] for p in state.manual_picks] == [440]
        assert state.current_app_id == 440
        assert state.skipped_until == {}

    def test_other_pick_survives_and_takes_the_assignment(self) -> None:
        # The whole point of multi-pick: abandoning one keeps the other locked.
        state = self._state(picks=[_pick(440, "TF2"), _pick(620, "Portal 2")])
        assert abandon_manual_pick(state, 620) is True
        assert [p["app_id"] for p in state.manual_picks] == [440]
        assert state.current_app_id == 440
        assert state.current_game_name == "TF2"
        assert is_manual_pick_locked(state) is True

    def test_keeps_unrelated_assignment(self) -> None:
        # A pick that is not the current assignment must not clear it.
        state = self._state(picks=[_pick(440, "TF2")])
        state.current_app_id = 70
        state.current_game_name = "Half-Life"
        abandon_manual_pick(state, 440)
        assert state.current_app_id == 70
        assert state.current_game_name == "Half-Life"


class TestActiveManualPicksAndAllowedSet:
    def test_finished_pick_drops_out(self) -> None:
        state = State(manual_picks=[_pick(440)], finished_app_ids=[440])
        assert active_manual_picks(state) == []
        assert is_manual_pick_locked(state) is False

    def test_expired_pick_drops_out(self) -> None:
        state = State(
            manual_picks=[_pick(days_ago=_actions.MANUAL_LOCK_DAYS + 1)],
        )
        assert active_manual_picks(state) == []

    def test_missing_timestamp_stays_active(self) -> None:
        # No deadline to evaluate → stay locked (safe answer for an enforcer).
        state = State(manual_picks=[{"app_id": 440, "game_name": "TF2"}])
        assert len(active_manual_picks(state)) == 1

    def test_malformed_timestamp_stays_active(self) -> None:
        state = State(
            manual_picks=[
                {"app_id": 440, "game_name": "TF2", "started_at": "not-a-date"}
            ]
        )
        assert len(active_manual_picks(state)) == 1

    def test_entry_without_app_id_is_ignored(self) -> None:
        state = State(manual_picks=[{"game_name": "Corrupt"}])
        assert active_manual_picks(state) == []

    def test_allowed_set_unions_picks_and_assignment(self) -> None:
        state = State(
            manual_picks=[_pick(440, "TF2"), _pick(620, "Portal 2")],
            current_app_id=70,
            current_game_name="Half-Life",
        )
        assert allowed_app_ids(state) == {70, 440, 620}
        assert allowed_games(state)[0] == (70, "Half-Life")

    def test_allowed_set_deduplicates_assignment(self) -> None:
        state = State(
            manual_picks=[_pick(440, "TF2")],
            current_app_id=440,
            current_game_name="TF2",
        )
        assert allowed_app_ids(state) == {440}
        assert allowed_games(state) == [(440, "TF2")]

    def test_empty_state_allows_nothing(self) -> None:
        assert allowed_app_ids(State()) == set()
        assert allowed_games(State()) == []

    def test_find_manual_pick(self) -> None:
        state = State(manual_picks=[_pick(440, "TF2")])
        found = find_manual_pick(state, 440)
        assert found is not None
        assert found["game_name"] == "TF2"
        assert find_manual_pick(state, 999) is None


class TestApplyManualPickCap:
    def test_appends_second_pick(self) -> None:
        state = State(manual_picks=[_pick(440, "TF2")])
        assert apply_manual_pick(state, 620, "Portal 2", max_picks=2) is None
        assert [p["app_id"] for p in state.manual_picks] == [440, 620]
        # Newest pick becomes the assignment.
        assert state.current_app_id == 620

    def test_refuses_beyond_cap(self) -> None:
        state = State(manual_picks=[_pick(440, "TF2"), _pick(620, "Portal 2")])
        refused = apply_manual_pick(state, 70, "Half-Life", max_picks=2)
        assert refused is not None
        assert "cap is 2" in refused
        assert len(state.manual_picks) == 2

    def test_refuses_duplicate_pick(self) -> None:
        state = State(manual_picks=[_pick(440, "TF2")])
        refused = apply_manual_pick(state, 440, "TF2", max_picks=2)
        assert refused is not None
        assert "already one of your manual picks" in refused

    def test_prunes_finished_entries(self) -> None:
        state = State(manual_picks=[_pick(440, "TF2")], finished_app_ids=[440])
        assert apply_manual_pick(state, 620, "Portal 2", max_picks=2) is None
        assert [p["app_id"] for p in state.manual_picks] == [620]

    def test_slots_left(self) -> None:
        state = State(manual_picks=[_pick(440, "TF2")])
        assert manual_pick_slots_left(state, 2) == 1
        assert manual_pick_slots_left(state, 1) == 0


class TestStatusPayload:
    def _patch_leaves(
        self,
        *,
        total_block: TotalBlockStatus,
        installed: list[tuple[int, str]],
        store_blocked: bool,
        protected_ids: set[int],
    ) -> object:
        return patch.multiple(
            "steam_backlog_enforcer._actions",
            get_total_block_status=lambda: total_block,
            get_installed_games=lambda: installed,
            is_store_blocked=lambda: store_blocked,
            is_protected_app=lambda aid: aid in protected_ids,
        )

    def test_assigned_and_installed(self) -> None:
        block = TotalBlockStatus(
            active=False, started_at=None, until=None, days=0, days_remaining=0.0
        )
        with self._patch_leaves(
            total_block=block,
            installed=[(440, "TF2"), (70, "HL")],
            store_blocked=True,
            protected_ids=set(),
        ):
            payload = status_payload(State(current_app_id=440, current_game_name="TF2"))
        assert payload["current_app_id"] == 440
        assert payload["installed_count"] == 2
        assert payload["assigned_game_installed"] is True
        assert payload["store_blocked"] is True
        assert payload["manual_pick_locked"] is False

    def test_no_assignment_and_protected_filtering(self) -> None:
        block = TotalBlockStatus(
            active=True,
            started_at=None,
            until=datetime(2030, 1, 1, tzinfo=timezone.utc),
            days=3,
            days_remaining=2.55,
        )
        with self._patch_leaves(
            total_block=block,
            installed=[(440, "TF2"), (228980, "Steamworks")],
            store_blocked=False,
            protected_ids={228980},
        ):
            payload = status_payload(State())
        assert payload["current_app_id"] is None
        assert payload["current_game_name"] is None
        assert payload["assigned_game_installed"] is None
        # protected app filtered out of the count.
        assert payload["installed_count"] == 1
        assert payload["total_block"]["active"] is True
        assert payload["total_block"]["days_remaining"] == 2.5
        assert payload["total_block"]["until"] == "2030-01-01T00:00:00+00:00"
