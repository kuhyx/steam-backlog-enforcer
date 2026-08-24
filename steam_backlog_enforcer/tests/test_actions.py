"""Tests for the stdout-free, state-only cores in ``_actions``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from steam_backlog_enforcer import _actions, _allowed_games
from steam_backlog_enforcer._actions import (
    apply_manual_pick,
    can_abandon_manual_pick,
    is_manual_pick_locked,
    manual_pick_grace_remaining,
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


class TestIsManualPickLocked:
    """Tests for Is Manual Pick Locked."""

    def test_no_pick_is_unlocked(self) -> None:
        """Test no pick is unlocked."""
        assert is_manual_pick_locked(State()) is False

    def test_finished_game_releases_lock(self) -> None:
        """Test finished game releases lock."""
        state = State(
            manual_picks=[{"app_id": 5, "game_name": "G", "started_at": ""}],
            finished_app_ids=[5],
        )
        assert is_manual_pick_locked(state) is False

    def test_empty_timestamp_stays_locked(self) -> None:
        # Pick set but no started_at → locked (no expiry to evaluate).
        """Test empty timestamp stays locked."""
        state = State(manual_picks=[{"app_id": 5, "game_name": "G", "started_at": ""}])
        assert is_manual_pick_locked(state) is True

    def test_recent_pick_is_locked(self) -> None:
        """Test recent pick is locked."""
        state = State(
            manual_picks=[
                {"app_id": 5, "game_name": "G", "started_at": _iso_days_ago(1)}
            ]
        )
        assert is_manual_pick_locked(state) is True

    def test_expired_pick_releases_lock(self) -> None:
        """Test expired pick releases lock."""
        state = State(
            manual_picks=[
                {
                    "app_id": 5,
                    "game_name": "G",
                    "started_at": _iso_days_ago(_allowed_games.MANUAL_LOCK_DAYS + 1),
                }
            ]
        )
        assert is_manual_pick_locked(state) is False

    def test_one_active_pick_holds_the_lock_for_all(self) -> None:
        # Multi-pick: the lock only lifts when every pick is done/expired.
        """Test one active pick holds the lock for all."""
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
        """Test legacy pick is migrated on load."""
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
        """Test new format is left alone."""
        State(manual_picks=[{"app_id": 9, "game_name": "New", "started_at": ""}]).save()
        assert [p["app_id"] for p in State.load().manual_picks] == [9]

    def test_no_pick_needs_no_migration(self) -> None:
        """Test no pick needs no migration."""
        State().save()
        assert State.load().manual_picks == []


class TestApplyManualPick:
    """Tests for Apply Manual Pick."""

    def test_sets_all_fields_and_enforcement_start(self) -> None:
        """Test sets all fields and enforcement start."""
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
        """Test preserves existing enforcement start."""
        state = State(enforcement_started_at="2020-01-01T00:00:00+00:00")
        apply_manual_pick(state, 620, "Portal 2")
        assert state.enforcement_started_at == "2020-01-01T00:00:00+00:00"

    def test_persists_to_disk(self) -> None:
        """Test persists to disk."""
        state = State()
        apply_manual_pick(state, 70, "Half-Life")
        assert State.load().current_app_id == 70

    def test_default_cap_is_one(self) -> None:
        # Callers that do not opt in keep the historical single-slot behaviour.
        """Test default cap is one."""
        state = State()
        apply_manual_pick(state, 440, "TF2")
        assert apply_manual_pick(state, 620, "Portal 2") is not None


class TestManualPickGraceRemaining:
    """Tests for Manual Pick Grace Remaining."""

    def test_no_pick_returns_none(self) -> None:
        """Test no pick returns none."""
        assert manual_pick_grace_remaining(State(), 440) is None

    def test_unknown_app_id_returns_none(self) -> None:
        """Test unknown app id returns none."""
        state = State(manual_picks=[_pick(440)])
        assert manual_pick_grace_remaining(state, 999) is None

    def test_missing_timestamp_returns_none(self) -> None:
        """Test missing timestamp returns none."""
        state = State(manual_picks=[{"app_id": 440, "game_name": "TF2"}])
        assert manual_pick_grace_remaining(state, 440) is None

    def test_malformed_timestamp_returns_none(self) -> None:
        """Test malformed timestamp returns none."""
        state = State(
            manual_picks=[
                {"app_id": 440, "game_name": "TF2", "started_at": "not-a-date"}
            ]
        )
        assert manual_pick_grace_remaining(state, 440) is None

    def test_fresh_pick_has_almost_the_full_window(self) -> None:
        """Test fresh pick has almost the full window."""
        state = State(manual_picks=[_pick(days_ago=0)])
        remaining = manual_pick_grace_remaining(state, 440)
        assert remaining is not None
        assert remaining == pytest.approx(_actions.MANUAL_GRACE_DAYS, abs=0.01)

    def test_expired_window_is_negative(self) -> None:
        """Test expired window is negative."""
        state = State(manual_picks=[_pick(days_ago=_actions.MANUAL_GRACE_DAYS + 1)])
        remaining = manual_pick_grace_remaining(state, 440)
        assert remaining is not None
        assert remaining == pytest.approx(-1.0, abs=0.01)


class TestCanAbandonManualPick:
    """Tests for Can Abandon Manual Pick."""

    def test_inside_window(self) -> None:
        """Test inside window."""
        state = State(manual_picks=[_pick(days_ago=_actions.MANUAL_GRACE_DAYS - 1)])
        assert can_abandon_manual_pick(state, 440) is True

    def test_outside_window(self) -> None:
        """Test outside window."""
        state = State(manual_picks=[_pick(days_ago=_actions.MANUAL_GRACE_DAYS + 1)])
        assert can_abandon_manual_pick(state, 440) is False

    def test_no_pick(self) -> None:
        """Test no pick."""
        assert can_abandon_manual_pick(State(), 440) is False
