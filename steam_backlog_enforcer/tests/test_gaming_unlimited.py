"""From 2026-11-16 the gaming budget is gone: no kill, no block, no warning.

Each test pairs the new behaviour (a day on or after the switch) with the old
one (the day before it), so the gate is proven in both directions.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import logging
from typing import TYPE_CHECKING
from unittest.mock import DEFAULT, patch

from leisure_watch.facts import Reason
import pytest

from steam_backlog_enforcer import _gaming_gate
from steam_backlog_enforcer._budget_resolve import BudgetResolution, resolve_budget
from steam_backlog_enforcer._gaming_gate import gaming_enforced_on
from steam_backlog_enforcer._leisure_kill import LeisureKiller
from steam_backlog_enforcer._leisure_mode import leisure_on
from steam_backlog_enforcer._playtime import playtime_tick
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    load_state,
    rules_for,
    save_state,
)
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._budget_dates import pin_today
from steam_backlog_enforcer.tests._budget_earners import (
    LEETCODE,
    READING,
    WORKOUT,
)
from steam_backlog_enforcer.tests._fake_session import fake_session
from steam_backlog_enforcer.tests._leisure_kill_world import (
    RULES as LEISURE_RULES,
)
from steam_backlog_enforcer.tests._leisure_kill_world import (
    SPENT,
    StubLog,
    build_proc,
    now_with,
    verdict_of,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from unittest.mock import MagicMock

PKG = "steam_backlog_enforcer._playtime"
_RESOLVER = "steam_backlog_enforcer._playtime_state.resolve_budget"
LOCAL = timezone(timedelta(hours=2))
LAST_DAY = datetime(2026, 11, 15, 20, 0, tzinfo=LOCAL)
FIRST_DAY = datetime(2026, 11, 17, 20, 0, tzinfo=LOCAL)
_THREE_HOURS = 3 * 3600.0


@pytest.fixture(autouse=True)
def _fresh_gate() -> Iterator[None]:
    """Forget which failures were logged, so each test sees its own."""
    _gaming_gate.reset_logged()
    yield
    _gaming_gate.reset_logged()


@pytest.fixture(name="effects")
def fixture_effects() -> Iterator[dict[str, MagicMock]]:
    """Neutralise and expose every side effect a cutoff can have."""
    with ExitStack() as stack:
        mocks: dict[str, MagicMock] = stack.enter_context(
            patch.multiple(
                "steam_backlog_enforcer._playtime_cutoff",
                reconcile=DEFAULT,
                request_steam_shutdown=DEFAULT,
                kill_gaming_processes=DEFAULT,
                notify_desktop_user=DEFAULT,
            )
        )
        stack.enter_context(patch(f"{PKG}.mounted_targets", return_value=set()))
        stack.enter_context(patch(f"{PKG}.is_total_block_active", return_value=False))
        stack.enter_context(patch(f"{PKG}.qualifying_pids", return_value={7: "app:1"}))
        yield mocks


def _real_resolver(*, workout: bool = False) -> ExitStack:
    """Patch ``rules_for`` to use the real ``resolve_budget``, earners fixed."""
    stack = ExitStack()
    stack.enter_context(patch(_RESOLVER, side_effect=resolve_budget))
    stack.enter_context(patch(WORKOUT, return_value=workout))
    stack.enter_context(patch(LEETCODE, return_value=False))
    stack.enter_context(patch(READING, return_value=False))
    return stack


def _tick(now: datetime, key: str) -> PlaytimeState:
    """Run one real-resolver tick at *now* with a day already past any budget."""
    save_state(
        PlaytimeState(
            day_key=key,
            seconds=12 * 3600.0,
            blocked_at=now.timestamp() - 60,
            warned_seconds=[3600],
            last_tick_at=now.timestamp() - 3.0,
        ),
        demo=False,
    )
    with (
        _real_resolver(),
        pin_today(now.date()),
        patch(f"{PKG}.datetime") as clock,
        patch("steam_backlog_enforcer._playtime_state.datetime") as state_clock,
    ):
        clock.now.return_value = now
        state_clock.now.return_value.astimezone.return_value = now
        playtime_tick(Config(), interval=3.0, session=fake_session())
    stored = load_state(demo=False)
    assert stored is not None
    return stored


class TestGate:
    """``gaming_enforced_on``: the date switch, failing open and loud."""

    def test_enforced_the_day_before(self) -> None:
        """2026-11-15 still has its budget."""
        assert gaming_enforced_on("2026-11-15") is True

    @pytest.mark.parametrize("day", ["2026-11-16", "2026-11-17", "2027-03-01"])
    def test_unlimited_from_the_switch(self, day: str) -> None:
        """The switch day and every later one have no budget."""
        assert gaming_enforced_on(day) is False

    @pytest.mark.parametrize("failure", [AttributeError("old lib"), ValueError("x")])
    def test_failure_is_unlimited_and_logged_once(
        self, failure: Exception, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unreadable switch never re-imposes a budget; it logs, once."""
        with (
            patch("earned_time.gaming_enforced", side_effect=failure),
            caplog.at_level(logging.ERROR),
        ):
            assert gaming_enforced_on("2026-11-20") is False
            assert gaming_enforced_on("2026-11-20") is False
        assert [r.levelno for r in caplog.records] == [logging.ERROR]

    def test_a_key_that_is_no_date_is_unlimited_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A garbled day key cannot price a budget; it fails open, loudly."""
        with caplog.at_level(logging.ERROR):
            assert gaming_enforced_on("not-a-day") is False
        assert "not-a-day" in caplog.text


class TestResolve:
    """``resolve_budget`` marks the day unlimited from the switch."""

    def test_unlimited_day_has_no_budget_to_enforce(self) -> None:
        """On 2026-11-17 the resolution says unlimited, whatever the registry."""
        with _real_resolver(), pin_today(date(2026, 11, 17)):
            resolved = resolve_budget(Config())
        assert resolved.enforced is False
        assert "unlimited" in resolved.reason

    def test_the_day_before_is_unchanged(self) -> None:
        """On 2026-11-15 the budget is still a number to enforce."""
        with _real_resolver(), pin_today(date(2026, 11, 15)):
            resolved = resolve_budget(Config())
        assert resolved.enforced is True
        assert resolved.seconds > 0
        assert "unlimited" not in resolved.reason

    def test_rules_carry_the_flag(self) -> None:
        """``rules_for`` hands the gate to every consumer; a demo is always on."""
        off = BudgetResolution(0.0, 0.0, 0.0, 0.0, "unlimited", enforced=False)
        with patch(_RESOLVER, return_value=off):
            assert rules_for(Config(), demo=False).gaming_enforced is False
            assert rules_for(Config(), demo=True).gaming_enforced is True


class TestTick:
    """The enforce tick: zero credits, budget long spent."""

    def test_unlimited_day_never_kills_and_lifts_the_block(
        self, effects: dict[str, MagicMock]
    ) -> None:
        """2026-11-17, 12 h billed, nothing earned: no kill, mounts off."""
        stored = _tick(FIRST_DAY, "2026-11-17")
        effects["kill_gaming_processes"].assert_not_called()
        effects["request_steam_shutdown"].assert_not_called()
        effects["notify_desktop_user"].assert_not_called()
        assert not stored.is_blocked()
        assert stored.warned_seconds == []
        effects["reconcile"].assert_called_with(should_block=False)

    def test_the_day_before_still_cuts_off(self, effects: dict[str, MagicMock]) -> None:
        """2026-11-15, same state: the old cutoff holds."""
        stored = _tick(LAST_DAY, "2026-11-15")
        effects["kill_gaming_processes"].assert_called()
        effects["request_steam_shutdown"].assert_not_called()
        assert stored.is_blocked()

    def test_time_is_still_billed_for_history(
        self, effects: dict[str, MagicMock]
    ) -> None:
        """No budget does not stop the day's history from counting."""
        stored = _tick(FIRST_DAY, "2026-11-17")
        assert stored.seconds == pytest.approx(12 * 3600.0 + 3.0)
        del effects


class TestLeisure:
    """Leisure is a budget too: off from the switch."""

    def test_leisure_never_on_from_the_switch(self) -> None:
        """Even a live switch file cannot bill leisure on an unlimited day."""
        with patch("earned_time.leisure_active", return_value=True):
            assert leisure_on("2026-11-15") is True
            assert leisure_on("2026-11-16") is False

    @pytest.mark.parametrize(("enforced", "kills"), [(True, 1), (False, 0)])
    def test_leisure_kill_stands_down(
        self, tmp_path: Path, *, enforced: bool, kills: int
    ) -> None:
        """A spent leisure budget kills mpv only while gaming is enforced."""
        build_proc(tmp_path)
        killer = LeisureKiller(StubLog())
        verdict = verdict_of(now_with(Reason("media", "app:mpv", 10, "mpv")))
        rules = replace(LEISURE_RULES, gaming_enforced=enforced)
        with patch("os.kill") as kill:
            killer.enforce(SPENT, rules, verdict=verdict, stamp=1000.0)
        assert kill.call_count == kills
