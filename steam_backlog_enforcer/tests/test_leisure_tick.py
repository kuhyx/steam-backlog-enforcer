"""The tick with Phase 2 dormant (no new path runs) and live (leisure billing)."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _leisure_mode, _shadow
from steam_backlog_enforcer._leisure_kill import LeisureKiller
from steam_backlog_enforcer._playtime import playtime_tick
from steam_backlog_enforcer._playtime_cutoff import _begin_cutoff, _warn
from steam_backlog_enforcer._playtime_session import new_session
from steam_backlog_enforcer._playtime_state import (
    PlaytimeRules,
    PlaytimeState,
    load_state,
    save_state,
)
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._fake_session import fake_session
from steam_backlog_enforcer.tests._isolate_leisure import switch_file
from steam_backlog_enforcer.tests._no_workout_http import fixed_budget

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from steam_backlog_enforcer._shadow import ShadowVerdict

_LOCAL = timezone(timedelta(hours=2))
_NOW = datetime(2026, 7, 27, 20, 0, tzinfo=_LOCAL)
_TODAY = "2026-07-27"
_PKG = "steam_backlog_enforcer._playtime"
_CUTOFF = "steam_backlog_enforcer._playtime_cutoff"


class SpyLeisure:
    def __init__(self) -> None:
        self.calls: list[tuple[PlaytimeState, PlaytimeRules]] = []

    def enforce(
        self,
        state: PlaytimeState,
        rules: PlaytimeRules,
        *,
        verdict: ShadowVerdict,
        stamp: float,
    ) -> None:
        del verdict, stamp
        self.calls.append((state, rules))


@pytest.fixture
def notify() -> Iterator[MagicMock]:
    with ExitStack() as stack:
        stack.enter_context(patch(f"{_CUTOFF}.reconcile"))
        stack.enter_context(patch(f"{_CUTOFF}.request_steam_shutdown"))
        stack.enter_context(patch(f"{_CUTOFF}.kill_gaming_processes"))
        stack.enter_context(patch(f"{_PKG}.mounted_targets", return_value=set()))
        stack.enter_context(patch(f"{_PKG}.is_total_block_active", return_value=False))
        yield stack.enter_context(patch(f"{_CUTOFF}.notify_desktop_user"))


def _tick(
    owners: dict[int, str], *, budget: float = 3600.0, demo: bool = False
) -> tuple[PlaytimeState, SpyLeisure]:
    save_state(
        PlaytimeState(day_key=_TODAY, last_tick_at=_NOW.timestamp() - 3.0),
        demo=demo,
    )
    spy = SpyLeisure()
    session = replace(fake_session(), leisure=spy)
    with (
        fixed_budget(budget),
        patch(f"{_PKG}.qualifying_pids", return_value=owners),
        patch(f"{_PKG}.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = _NOW
        playtime_tick(Config(), interval=3.0, session=session, demo=demo)
    state = load_state(demo=demo)
    assert state is not None
    return state, spy


def _go_live(tmp_path: Path) -> None:
    switch_file(tmp_path).write_text(_TODAY + "\n", encoding="ascii")


@pytest.mark.usefixtures("notify")
class TestDormant:
    def test_no_new_code_path_runs_without_the_switch(self) -> None:
        with patch.object(
            _leisure_mode, "leisure_billed", side_effect=AssertionError("ran")
        ):
            state, spy = _tick({})
        assert spy.calls == []
        # Games-only, exactly as before: the fail-closed shadow does not bill.
        assert (state.seconds, state.shadow_seconds) == (0.0, 3.0)

    def test_games_still_bill_games_only(self) -> None:
        state, spy = _tick({7: "app:440"})
        assert (state.seconds, state.per_game, spy.calls) == (3.0, {"app:440": 3.0}, [])

    def test_a_demo_ignores_the_switch(self, tmp_path: Path) -> None:
        _go_live(tmp_path)
        state, spy = _tick({}, demo=True)
        assert (state.seconds, spy.calls) == (0.0, [])


@pytest.mark.usefixtures("notify")
class TestLive:
    def test_leisure_bills_the_enforced_count(self, tmp_path: Path) -> None:
        _go_live(tmp_path)
        state, spy = _tick({})
        assert state.seconds == state.shadow_seconds == 3.0
        assert state.shadow_per_source == {_shadow.FAILCLOSED_KEY: 3.0}
        [(_seen, rules)] = spy.calls
        assert rules.leisure

    def test_a_lock_pauses_the_enforced_count_too(self, tmp_path: Path) -> None:
        _go_live(tmp_path)
        with patch.object(_shadow, "paused_by", return_value="i3lock"):
            state, _ = _tick({7: "app:440"})
        assert (state.seconds, state.shadow_paused_seconds) == (0.0, 3.0)

    def test_at_zero_the_cutoff_says_leisure_and_kills_run(
        self, tmp_path: Path, notify: MagicMock
    ) -> None:
        _go_live(tmp_path)
        state, spy = _tick({}, budget=3.0)
        assert state.is_blocked()
        assert notify.call_args.args[0] == "Leisure time is up"
        assert "leisure" in notify.call_args.args[1]
        assert spy.calls[0][0].seconds >= spy.calls[0][1].budget_seconds


_RULES = PlaytimeRules(
    budget_seconds=3600.0,
    warn_at=(3600, 1800),
    sigkill_after=30.0,
    count_launchers=False,
    enforcement=True,
    demo=False,
)


class TestWording:
    def test_warnings_say_gaming_while_dormant(self) -> None:
        with patch(f"{_CUTOFF}.notify_desktop_user") as notify:
            _warn(PlaytimeState(day_key=_TODAY, seconds=10.0), _RULES)
        notify.assert_called_once_with(
            "Gaming time running out", "1 hour of today's gaming budget left."
        )

    def test_warnings_say_leisure_when_live(self) -> None:
        with patch(f"{_CUTOFF}.notify_desktop_user") as notify:
            _warn(
                PlaytimeState(day_key=_TODAY, seconds=10.0),
                replace(_RULES, leisure=True),
            )
        notify.assert_called_once_with(
            "Leisure time running out", "1 hour of today's leisure budget left."
        )

    @pytest.mark.usefixtures("notify")
    def test_the_dormant_cutoff_text_is_unchanged(self, notify: MagicMock) -> None:
        _begin_cutoff(PlaytimeState(day_key=_TODAY), _RULES, now=_NOW)
        notify.assert_called_once_with(
            "Gaming time is up",
            "Daily budget used up. Steam and games are shutting down. "
            "Unblocks at 06:00.",
        )


def test_new_session_kills_through_the_budget_log() -> None:
    session = new_session()
    assert isinstance(session.leisure, LeisureKiller)
    assert session.leisure.log is not None
