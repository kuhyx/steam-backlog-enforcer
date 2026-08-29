"""Tests for the playtime tick state machine and cutoff sequence."""

from contextlib import ExitStack
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._playtime import (
    _state_or_recover,
    playtime_tick,
)
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    load_state,
    rules_for,
    save_state,
)
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._fake_session import fake_session

PKG = "steam_backlog_enforcer._playtime"
LOCAL = timezone(timedelta(hours=2))
NOW = datetime(2026, 7, 27, 20, 0, tzinfo=LOCAL)
TODAY = "2026-07-27"


@pytest.fixture
def quiet_tick() -> object:
    """Neutralise every side effect the tick can produce."""
    with ExitStack() as stack:
        # Each name is patched in the module that *resolves* it, not in the
        # package that re-exports it -- otherwise the patch never bites.
        cutoff = "steam_backlog_enforcer._playtime_cutoff"
        mocks = {
            name: stack.enter_context(patch(f"{where}.{name}"))
            for name, where in (
                ("reconcile", PKG),
                ("request_steam_shutdown", cutoff),
                ("kill_gaming_processes", cutoff),
                ("notify_desktop_user", cutoff),
                ("mounted_targets", PKG),
            )
        }
        mocks["mounted_targets"].return_value = set()
        stack.enter_context(patch(f"{PKG}.is_total_block_active", return_value=False))
        yield mocks


def _rules(*, demo: bool = False, **cfg: object) -> object:
    return rules_for(Config(**cfg), demo=demo)


class TestStateOrRecover:
    def test_loads_existing_state(self) -> None:
        save_state(PlaytimeState(day_key=TODAY, seconds=42.0), demo=False)
        with patch(f"{PKG}.mounted_targets", return_value=set()):
            out = _state_or_recover(_rules(), now=NOW)
        assert out.seconds == 42.0

    def test_fresh_state_when_nothing_stored_and_nothing_mounted(self) -> None:
        with patch(f"{PKG}.mounted_targets", return_value=set()):
            out = _state_or_recover(_rules(), now=NOW)
        assert out.seconds == 0.0
        assert out.is_blocked() is False
        assert out.day_key == TODAY

    def test_fails_closed_when_state_is_gone_but_mounts_remain(self) -> None:
        """Deleting the state file must not be a way to lift the block."""
        rules = _rules(daily_gaming_seconds=100)
        with patch(f"{PKG}.mounted_targets", return_value={"/usr/bin/steam"}):
            out = _state_or_recover(rules, now=NOW)
        assert out.seconds == 100.0
        assert out.is_blocked() is True

    def test_fails_closed_on_corrupt_state(self) -> None:
        from steam_backlog_enforcer._playtime_state import state_path

        state_path(demo=False).write_text("{bad", encoding="utf-8")
        with patch(f"{PKG}.mounted_targets", return_value={"/usr/bin/steam"}):
            out = _state_or_recover(_rules(daily_gaming_seconds=50), now=NOW)
        assert out.is_blocked() is True


class TestPlaytimeTick:
    def test_accumulates_while_a_game_runs(self, quiet_tick: dict) -> None:
        save_state(
            PlaytimeState(day_key=TODAY, last_tick_at=NOW.timestamp() - 3.0),
            demo=False,
        )
        with (
            patch(f"{PKG}.qualifying_pids", return_value={7: "app:440"}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=fake_session())
        assert load_state(demo=False).seconds == 3.0

    def test_records_the_day_in_the_history(self, quiet_tick: dict) -> None:
        del quiet_tick
        save_state(
            PlaytimeState(day_key=TODAY, last_tick_at=NOW.timestamp() - 3.0),
            demo=False,
        )
        session = fake_session()
        with (
            patch(f"{PKG}.qualifying_pids", return_value={7: "app:440"}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=session)
        assert session.history.recorded == [(TODAY, 3.0)]

    def test_records_the_day_even_under_a_total_block(self, quiet_tick: dict) -> None:
        """The counter still needs a history point while the block is up."""
        del quiet_tick
        save_state(
            PlaytimeState(
                day_key=TODAY, seconds=5.0, last_tick_at=NOW.timestamp() - 3.0
            ),
            demo=False,
        )
        session = fake_session()
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.qualifying_pids", return_value={7: "app:440"}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=session)
        assert session.history.recorded == [(TODAY, 5.0)]

    def test_total_block_releases_and_stops_accruing(self, quiet_tick: dict) -> None:
        """Our mounts would make the total block's `pacman -R steam` fail."""
        save_state(
            PlaytimeState(
                day_key=TODAY, seconds=5.0, last_tick_at=NOW.timestamp() - 3.0
            ),
            demo=False,
        )
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.qualifying_pids", return_value={7: "app:440"}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=fake_session())
        quiet_tick["reconcile"].assert_called_once_with(should_block=False)
        assert load_state(demo=False).seconds == 5.0

    def test_rollover_clears_a_stale_block(self, quiet_tick: dict) -> None:
        save_state(
            PlaytimeState(
                day_key="2026-07-26",
                seconds=10**6,
                blocked_at=1.0,
                last_tick_at=NOW.timestamp() - 3.0,
            ),
            demo=False,
        )
        with (
            patch(f"{PKG}.qualifying_pids", return_value={}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=fake_session())
        stored = load_state(demo=False)
        assert stored.day_key == TODAY
        assert stored.seconds == 0.0
        assert stored.is_blocked() is False
        quiet_tick["reconcile"].assert_called_with(should_block=False)

    def test_cutoff_engages_at_the_budget(self, quiet_tick: dict) -> None:
        save_state(
            PlaytimeState(
                day_key=TODAY, seconds=59.0, last_tick_at=NOW.timestamp() - 3.0
            ),
            demo=True,
        )
        with (
            patch(f"{PKG}.qualifying_pids", return_value={7: "app:440"}),
            patch(
                "steam_backlog_enforcer._playtime_cutoff._kill_set", return_value={7}
            ),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=fake_session(), demo=True)
        stored = load_state(demo=True)
        assert stored.is_blocked() is True
        quiet_tick["request_steam_shutdown"].assert_called_once()

    def test_demo_uses_a_separate_state_file(self, quiet_tick: dict) -> None:
        """A demo run must never consume the real day's budget."""
        with (
            patch(f"{PKG}.qualifying_pids", return_value={7: "app:440"}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=fake_session(), demo=True)
        assert load_state(demo=True) is not None
        assert load_state(demo=False) is None

    def test_first_tick_writes_state(self, quiet_tick: dict) -> None:
        with (
            patch(f"{PKG}.qualifying_pids", return_value={}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=fake_session())
        stored = load_state(demo=False)
        assert stored is not None
        assert stored.day_key == TODAY
