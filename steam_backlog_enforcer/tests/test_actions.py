"""Tests for the stdout-free, state-only cores in ``_actions``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from steam_backlog_enforcer import _actions
from steam_backlog_enforcer._actions import (
    apply_manual_pick,
    is_manual_pick_locked,
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
        state = State(manual_pick_app_id=5, finished_app_ids=[5])
        assert is_manual_pick_locked(state) is False

    def test_empty_timestamp_stays_locked(self) -> None:
        # manual pick set but no started_at → locked (no expiry to evaluate).
        state = State(manual_pick_app_id=5, manual_pick_started_at="")
        assert is_manual_pick_locked(state) is True

    def test_recent_pick_is_locked(self) -> None:
        state = State(manual_pick_app_id=5, manual_pick_started_at=_iso_days_ago(1))
        assert is_manual_pick_locked(state) is True

    def test_expired_pick_releases_lock(self) -> None:
        state = State(
            manual_pick_app_id=5,
            manual_pick_started_at=_iso_days_ago(_actions.MANUAL_LOCK_DAYS + 1),
        )
        assert is_manual_pick_locked(state) is False

    def test_malformed_timestamp_stays_locked(self) -> None:
        state = State(manual_pick_app_id=5, manual_pick_started_at="not-a-date")
        assert is_manual_pick_locked(state) is True


class TestApplyManualPick:
    def test_sets_all_fields_and_enforcement_start(self) -> None:
        state = State()
        apply_manual_pick(state, 440, "Team Fortress 2")
        assert state.manual_pick_app_id == 440
        assert state.manual_pick_game_name == "Team Fortress 2"
        assert state.current_app_id == 440
        assert state.current_game_name == "Team Fortress 2"
        assert state.manual_pick_started_at != ""
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
