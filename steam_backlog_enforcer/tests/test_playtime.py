"""Tests for playtime day keys, state persistence and rule resolution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

from steam_backlog_enforcer._gaming_days import gaming_day_key
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    load_state,
    save_state,
    state_path,
)

PKG = "steam_backlog_enforcer._playtime"
LOCAL = timezone(timedelta(hours=2))


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL)


class TestGamingDayKey:
    """The gaming day runs from 06:00 to 06:00 local time."""

    def test_just_before_the_boundary_is_the_previous_day(self) -> None:
        """05:59 still belongs to yesterday."""
        assert gaming_day_key(_at(2026, 7, 27, 5, 59)) == "2026-07-26"

    def test_exactly_at_the_boundary_starts_the_new_day(self) -> None:
        """06:00 starts the new day."""
        assert gaming_day_key(_at(2026, 7, 27, 6, 0)) == "2026-07-27"

    def test_evening_is_the_same_day(self) -> None:
        """A late evening keeps today's key."""
        assert gaming_day_key(_at(2026, 7, 27, 23, 30)) == "2026-07-27"

    def test_after_midnight_belongs_to_the_day_it_started(self) -> None:
        """01:15 belongs to the day before."""
        assert gaming_day_key(_at(2026, 7, 28, 1, 15)) == "2026-07-27"

    def test_exact_midnight(self) -> None:
        """Midnight belongs to the day before."""
        assert gaming_day_key(_at(2026, 7, 28, 0, 0)) == "2026-07-27"

    def test_month_boundary(self) -> None:
        """Early hours on the 1st belong to the last day of the previous month."""
        assert gaming_day_key(_at(2026, 8, 1, 3, 0)) == "2026-07-31"

    def test_dst_transition_day_still_yields_a_key(self) -> None:
        """The gaming day is 23h or 25h across DST; the budget is not rescaled."""
        warsaw_spring_forward = datetime(
            2026, 3, 29, 12, 0, tzinfo=timezone(timedelta(hours=2))
        )
        assert gaming_day_key(warsaw_spring_forward) == "2026-03-29"


class TestStatePath:
    """Production and demo state live in separate files."""

    def test_production_and_demo_differ(self) -> None:
        """The two modes never share a path."""
        assert state_path(demo=False) != state_path(demo=True)

    def test_demo_path_is_named_demo(self) -> None:
        """The demo file is recognisable by name."""
        assert "demo" in state_path(demo=True).name


class TestPlaytimeState:
    """Blocked status derives from blocked_at."""

    def test_not_blocked_by_default(self) -> None:
        """A fresh state is not blocked."""
        assert PlaytimeState().is_blocked() is False

    def test_blocked_when_stamped(self) -> None:
        """A blocked_at stamp makes the state blocked."""
        assert PlaytimeState(blocked_at=1.0).is_blocked() is True

    def test_is_blocked_is_not_serialised(self) -> None:
        """A derived field would be persisted and could drift from blocked_at."""
        assert "is_blocked" not in PlaytimeState().__dict__


class TestSaveLoadRoundTrip:
    """Saving and loading state, and every unreadable case."""

    def test_round_trip(self) -> None:
        """A saved state loads back equal."""
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
        """The state file is written 0644 so unprivileged readers see it."""
        # The daemon runs as root and mkstemp would leave this 0600, which made
        # every unprivileged reader see "no state recorded yet".
        save_state(PlaytimeState(day_key="d", seconds=1.0), demo=False)
        assert state_path(demo=False).stat().st_mode & 0o777 == 0o644

    def test_demo_and_production_are_independent(self) -> None:
        """Demo and production saves do not overwrite each other."""
        save_state(PlaytimeState(day_key="prod", seconds=10.0), demo=False)
        save_state(PlaytimeState(day_key="demo", seconds=20.0), demo=True)
        assert load_state(demo=False).day_key == "prod"
        assert load_state(demo=True).day_key == "demo"

    def test_missing_file_is_none(self) -> None:
        """No file loads as None."""
        assert load_state(demo=False) is None

    def test_corrupt_json_is_none(self) -> None:
        """Invalid JSON loads as None."""
        state_path(demo=False).write_text("{not json", encoding="utf-8")
        assert load_state(demo=False) is None

    def test_unreadable_file_is_none(self) -> None:
        """A read error loads as None."""
        save_state(PlaytimeState(day_key="x"), demo=False)
        with patch("pathlib.Path.read_text", side_effect=OSError("nope")):
            assert load_state(demo=False) is None

    def test_wrong_schema_version_is_none(self) -> None:
        """An unknown schema version loads as None."""
        state_path(demo=False).write_text(
            json.dumps({"schema_version": 99, "day_key": "x"}), encoding="utf-8"
        )
        assert load_state(demo=False) is None

    def test_non_dict_json_is_none(self) -> None:
        """A JSON list loads as None."""
        state_path(demo=False).write_text("[1, 2, 3]", encoding="utf-8")
        assert load_state(demo=False) is None

    def test_unknown_keys_are_dropped(self) -> None:
        """Unknown keys are ignored and known ones kept."""
        state_path(demo=False).write_text(
            json.dumps({"schema_version": 1, "day_key": "d", "bogus": 1}),
            encoding="utf-8",
        )
        loaded = load_state(demo=False)
        assert loaded is not None
        assert loaded.day_key == "d"


class TestSaveStateImmutability:
    """Production saves toggle the immutable bit; demo saves do not."""

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
