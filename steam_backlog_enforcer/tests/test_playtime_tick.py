"""Tests for the playtime tick state machine and cutoff sequence."""

from contextlib import ExitStack
from dataclasses import replace
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
    state_path,
)
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._fake_session import StubHistory, fake_session
from steam_backlog_enforcer.tests._no_workout_http import fixed_budget

PKG = "steam_backlog_enforcer._playtime"
LOCAL = timezone(timedelta(hours=2))
NOW = datetime(2026, 7, 27, 20, 0, tzinfo=LOCAL)
TODAY = "2026-07-27"


@pytest.fixture(name="quiet_tick")
def fixture_quiet_tick() -> object:
    """Neutralise every side effect the tick can produce."""
    with ExitStack() as stack:
        # Each name is patched in the module that *resolves* it, not in the
        # package that re-exports it -- otherwise the patch never bites.
        cutoff = "steam_backlog_enforcer._playtime_cutoff"
        mocks = {
            name: stack.enter_context(patch(f"{where}.{name}"))
            for name, where in (
                ("reconcile", cutoff),
                ("request_steam_shutdown", cutoff),
                ("kill_gaming_processes", cutoff),
                ("notify_desktop_user", cutoff),
                ("mounted_targets", PKG),
            )
        }
        mocks["mounted_targets"].return_value = set()
        stack.enter_context(patch(f"{PKG}.is_total_block_active", return_value=False))
        yield mocks


def _rules(*, demo: bool = False, budget: float | None = None) -> object:
    if budget is None:
        return rules_for(Config(), demo=demo)
    with fixed_budget(budget):
        return rules_for(Config(), demo=demo)


class TestStateOrRecover:
    """_state_or_recover loads state or fails closed without it."""

    def test_loads_existing_state(self) -> None:
        """Stored state for today is loaded as is."""
        save_state(PlaytimeState(day_key=TODAY, seconds=42.0), demo=False)
        with patch(f"{PKG}.mounted_targets", return_value=set()):
            out = _state_or_recover(_rules(), now=NOW)
        assert out.seconds == 42.0

    def test_fresh_state_when_nothing_stored_and_nothing_mounted(self) -> None:
        """With nothing stored and nothing mounted the day starts fresh."""
        with patch(f"{PKG}.mounted_targets", return_value=set()):
            out = _state_or_recover(_rules(), now=NOW)
        assert out.seconds == 0.0
        assert out.is_blocked() is False
        assert out.day_key == TODAY

    def test_fails_closed_when_state_is_gone_but_mounts_remain(self) -> None:
        """Deleting the state file must not be a way to lift the block."""
        rules = _rules(budget=100.0)
        with patch(f"{PKG}.mounted_targets", return_value={"/usr/bin/steam"}):
            out = _state_or_recover(rules, now=NOW)
        assert out.seconds == 100.0
        assert out.is_blocked() is True

    def test_fails_closed_on_corrupt_state(self) -> None:
        """A corrupt state file with mounts present recovers as blocked."""
        state_path(demo=False).write_text("{bad", encoding="utf-8")
        with patch(f"{PKG}.mounted_targets", return_value={"/usr/bin/steam"}):
            out = _state_or_recover(_rules(budget=50.0), now=NOW)
        assert out.is_blocked() is True


class TestPlaytimeTick:
    """playtime_tick accrues, records, rolls over and cuts off."""

    @pytest.mark.usefixtures("quiet_tick")
    def test_accumulates_while_a_game_runs(self) -> None:
        """A tick with a game running adds the interval to the counter."""
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

    @pytest.mark.usefixtures("quiet_tick")
    def test_records_the_day_in_the_history(self) -> None:
        """Each tick records the day's total in the history."""
        save_state(
            PlaytimeState(day_key=TODAY, last_tick_at=NOW.timestamp() - 3.0),
            demo=False,
        )
        history = StubHistory()
        session = replace(fake_session(), history=history)
        with (
            patch(f"{PKG}.qualifying_pids", return_value={7: "app:440"}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=session)
        assert history.recorded == [(TODAY, 3.0)]

    @pytest.mark.usefixtures("quiet_tick")
    def test_records_the_day_even_under_a_total_block(self) -> None:
        """The counter still needs a history point while the block is up."""
        save_state(
            PlaytimeState(
                day_key=TODAY, seconds=5.0, last_tick_at=NOW.timestamp() - 3.0
            ),
            demo=False,
        )
        history = StubHistory()
        session = replace(fake_session(), history=history)
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.qualifying_pids", return_value={7: "app:440"}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=session)
        assert history.recorded == [(TODAY, 5.0)]

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
        """A new day clears yesterday's block and counter."""
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
        """Crossing the budget blocks and asks Steam to shut down."""
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

    @pytest.mark.usefixtures("quiet_tick")
    def test_demo_uses_a_separate_state_file(self) -> None:
        """A demo run must never consume the real day's budget."""
        with (
            patch(f"{PKG}.qualifying_pids", return_value={7: "app:440"}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=fake_session(), demo=True)
        assert load_state(demo=True) is not None
        assert load_state(demo=False) is None

    @pytest.mark.usefixtures("quiet_tick")
    def test_first_tick_writes_state(self) -> None:
        """The very first tick writes a state file for today."""
        with (
            patch(f"{PKG}.qualifying_pids", return_value={}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, session=fake_session())
        stored = load_state(demo=False)
        assert stored is not None
        assert stored.day_key == TODAY
