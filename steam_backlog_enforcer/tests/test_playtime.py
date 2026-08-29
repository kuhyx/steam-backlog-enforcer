"""Tests for playtime day keys, state persistence and rule resolution."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    gaming_day_key,
    load_state,
    rules_for,
    save_state,
    state_path,
)
from steam_backlog_enforcer.config import Config

PKG = "steam_backlog_enforcer._playtime"
LOCAL = timezone(timedelta(hours=2))


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL)


class TestGamingDayKey:
    def test_just_before_the_boundary_is_the_previous_day(self) -> None:
        assert gaming_day_key(_at(2026, 7, 27, 5, 59)) == "2026-07-26"

    def test_exactly_at_the_boundary_starts_the_new_day(self) -> None:
        assert gaming_day_key(_at(2026, 7, 27, 6, 0)) == "2026-07-27"

    def test_evening_is_the_same_day(self) -> None:
        assert gaming_day_key(_at(2026, 7, 27, 23, 30)) == "2026-07-27"

    def test_after_midnight_belongs_to_the_day_it_started(self) -> None:
        assert gaming_day_key(_at(2026, 7, 28, 1, 15)) == "2026-07-27"

    def test_exact_midnight(self) -> None:
        assert gaming_day_key(_at(2026, 7, 28, 0, 0)) == "2026-07-27"

    def test_month_boundary(self) -> None:
        assert gaming_day_key(_at(2026, 8, 1, 3, 0)) == "2026-07-31"

    def test_dst_transition_day_still_yields_a_key(self) -> None:
        """The gaming day is 23h or 25h across DST; the budget is not rescaled."""
        warsaw_spring_forward = datetime(
            2026, 3, 29, 12, 0, tzinfo=timezone(timedelta(hours=2))
        )
        assert gaming_day_key(warsaw_spring_forward) == "2026-03-29"


class TestStatePath:
    def test_production_and_demo_differ(self) -> None:
        assert state_path(demo=False) != state_path(demo=True)

    def test_demo_path_is_named_demo(self) -> None:
        assert "demo" in state_path(demo=True).name


class TestPlaytimeState:
    def test_not_blocked_by_default(self) -> None:
        assert PlaytimeState().is_blocked() is False

    def test_blocked_when_stamped(self) -> None:
        assert PlaytimeState(blocked_at=1.0).is_blocked() is True

    def test_is_blocked_is_not_serialised(self) -> None:
        """A derived field would be persisted and could drift from blocked_at."""
        assert "is_blocked" not in PlaytimeState().__dict__


class TestSaveLoadRoundTrip:
    def test_round_trip(self) -> None:
        original = PlaytimeState(
            day_key="2026-07-27",
            seconds=123.5,
            last_tick_at=99.0,
            blocked_at=42.0,
            warned_seconds=[600, 300],
        )
        save_state(original, demo=False)
        loaded = load_state(demo=False)
        assert loaded == original

    def test_written_world_readable(self) -> None:
        # The daemon runs as root and mkstemp would leave this 0600, which made
        # every unprivileged reader see "no state recorded yet".
        save_state(PlaytimeState(day_key="d", seconds=1.0), demo=False)
        assert state_path(demo=False).stat().st_mode & 0o777 == 0o644

    def test_demo_and_production_are_independent(self) -> None:
        save_state(PlaytimeState(day_key="prod", seconds=10.0), demo=False)
        save_state(PlaytimeState(day_key="demo", seconds=20.0), demo=True)
        assert load_state(demo=False).day_key == "prod"
        assert load_state(demo=True).day_key == "demo"

    def test_missing_file_is_none(self) -> None:
        assert load_state(demo=False) is None

    def test_corrupt_json_is_none(self) -> None:
        state_path(demo=False).write_text("{not json", encoding="utf-8")
        assert load_state(demo=False) is None

    def test_unreadable_file_is_none(self) -> None:
        save_state(PlaytimeState(day_key="x"), demo=False)
        with patch("pathlib.Path.read_text", side_effect=OSError("nope")):
            assert load_state(demo=False) is None

    def test_wrong_schema_version_is_none(self) -> None:
        state_path(demo=False).write_text(
            json.dumps({"schema_version": 99, "day_key": "x"}), encoding="utf-8"
        )
        assert load_state(demo=False) is None

    def test_non_dict_json_is_none(self) -> None:
        state_path(demo=False).write_text("[1, 2, 3]", encoding="utf-8")
        assert load_state(demo=False) is None

    def test_unknown_keys_are_dropped(self) -> None:
        state_path(demo=False).write_text(
            json.dumps({"schema_version": 1, "day_key": "d", "bogus": 1}),
            encoding="utf-8",
        )
        loaded = load_state(demo=False)
        assert loaded is not None
        assert loaded.day_key == "d"


class TestSaveStateImmutability:
    def test_production_save_unlocks_then_relocks(self) -> None:
        """rename(2) onto an immutable file is EPERM, so the unlock is required."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_state.unlock_for_write"
            ) as mock_unlock,
            patch(
                "steam_backlog_enforcer._playtime_state._try_set_immutable"
            ) as mock_lock,
        ):
            save_state(PlaytimeState(day_key="x"), demo=False)
        mock_unlock.assert_called_once_with(state_path(demo=False))
        mock_lock.assert_called_once_with(state_path(demo=False), immutable=True)

    def test_demo_save_is_left_mutable(self) -> None:
        """An immutable demo file could not be deleted during cleanup."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_state.unlock_for_write"
            ) as mock_unlock,
            patch(
                "steam_backlog_enforcer._playtime_state._try_set_immutable"
            ) as mock_lock,
        ):
            save_state(PlaytimeState(day_key="x"), demo=True)
        mock_unlock.assert_not_called()
        mock_lock.assert_not_called()


class TestRulesFor:
    def test_production_budget_comes_from_config(self) -> None:
        rules = rules_for(Config(daily_gaming_seconds=100), demo=False)
        assert rules.budget_seconds == 100.0
        assert rules.demo is False

    def test_demo_budget_is_sixty_seconds(self) -> None:
        rules = rules_for(Config(daily_gaming_seconds=28800), demo=True)
        assert rules.budget_seconds == 60.0
        assert rules.demo is True

    def test_demo_warns_in_seconds_not_minutes(self) -> None:
        assert rules_for(Config(), demo=True).warn_at == (30, 10)
        assert rules_for(Config(), demo=False).warn_at == (3600, 1800, 600, 300)

    def test_demo_escalates_to_sigkill_sooner(self) -> None:
        assert rules_for(Config(), demo=True).sigkill_after == 10.0
        assert rules_for(Config(), demo=False).sigkill_after == 30.0

    def test_launcher_toggle_is_carried_through(self) -> None:
        assert (
            rules_for(
                Config(count_launcher_processes=False), demo=False
            ).count_launchers
            is False
        )
        assert (
            rules_for(Config(count_launcher_processes=True), demo=False).count_launchers
            is True
        )

    def test_enforcement_toggle_is_carried_through(self) -> None:
        assert (
            rules_for(Config(playtime_enforcement=False), demo=False).enforcement
            is False
        )

    def test_demo_uses_the_same_qualifying_predicate(self) -> None:
        """Demo may differ in budget and warnings only."""
        prod = rules_for(Config(count_launcher_processes=True), demo=False)
        demo = rules_for(Config(count_launcher_processes=True), demo=True)
        assert prod.count_launchers == demo.count_launchers

    def test_rules_are_frozen(self) -> None:
        """Frozen so the decision helpers stay pure and cheap to reason about."""
        rules = rules_for(Config(), demo=False)
        with pytest.raises(FrozenInstanceError):
            rules.budget_seconds = 1.0
