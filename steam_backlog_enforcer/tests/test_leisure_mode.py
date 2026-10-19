"""Phase 2 gate and billing: ``leisure_on`` and ``leisure_billed``."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import importlib
from pathlib import Path
from unittest.mock import patch

import earned_time
import pytest

from steam_backlog_enforcer import _leisure_mode
from steam_backlog_enforcer._budget_resolve import resolve_budget
from steam_backlog_enforcer._leisure_mode import (
    Tick,
    bill_tick,
    leisure_billed,
    leisure_on,
)
from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState
from steam_backlog_enforcer._shadow import ShadowVerdict, shadow_accumulate
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._budget_dates import AFTER_CUT, pin_today
from steam_backlog_enforcer.tests._isolate_leisure import switch_file

_LOCAL = timezone(timedelta(hours=2))
_NOW = datetime(2026, 11, 2, 20, 0, tzinfo=_LOCAL)
_DAY = "2026-11-02"
_REAL_SWITCH = Path("/etc/leisure-watch/leisure_from")
_RULES = PlaytimeRules(
    budget_seconds=100.0,
    warn_at=(),
    sigkill_after=30.0,
    count_launchers=False,
    enforcement=True,
    demo=False,
)


def _switch_on(tmp_path: Path, day: str) -> None:
    switch_file(tmp_path).write_text(day + "\n", encoding="ascii")


class TestHygiene:
    def test_no_test_reads_the_real_switch_file(self) -> None:
        assert _leisure_mode.LEISURE_FROM_PATH != _REAL_SWITCH
        reader = importlib.import_module("earned_time._leisure")
        assert reader.LEISURE_FROM_PATH != _REAL_SWITCH

    def test_the_redirect_reaches_both_readers(self, tmp_path: Path) -> None:
        with pin_today(AFTER_CUT):
            dormant = resolve_budget(Config()).base_seconds
            _switch_on(tmp_path, AFTER_CUT.isoformat())
            live = resolve_budget(Config()).base_seconds
        assert leisure_on(AFTER_CUT.isoformat())
        assert live - dormant == 2 * 3600.0


class TestLeisureOn:
    def test_absent_switch_is_dormant(self) -> None:
        assert not leisure_on(_DAY)

    def test_the_switch_day_and_later_are_on(self, tmp_path: Path) -> None:
        _switch_on(tmp_path, _DAY)
        assert leisure_on(_DAY)
        assert leisure_on("2026-11-03")

    def test_the_day_before_is_off(self, tmp_path: Path) -> None:
        _switch_on(tmp_path, _DAY)
        assert not leisure_on("2026-11-01")

    def test_a_garbage_day_key_is_dormant(self, tmp_path: Path) -> None:
        _switch_on(tmp_path, _DAY)
        assert not leisure_on("not-a-day")

    def test_the_gate_asks_earned_time(self) -> None:
        with patch.object(earned_time, "leisure_active", return_value=True) as ask:
            assert leisure_on(_DAY)
        ask.assert_called_once_with(date(2026, 11, 2), _leisure_mode.LEISURE_FROM_PATH)


def _start() -> PlaytimeState:
    return PlaytimeState(day_key=_DAY, last_tick_at=_NOW.timestamp() - 3.0)


def _tick(verdict: ShadowVerdict, owners: dict[int, str] | None = None) -> Tick:
    return Tick(now=_NOW, interval=3.0, owners=owners or {}, verdict=verdict)


def _bill(
    verdict: ShadowVerdict, owners: dict[int, str] | None = None
) -> tuple[PlaytimeState, bool]:
    state, rules = bill_tick(_start(), _RULES, _tick(verdict, owners))
    return state, rules.leisure


@pytest.fixture
def live(tmp_path: Path) -> None:
    _switch_on(tmp_path, _DAY)


@pytest.mark.usefixtures("live")
class TestLeisureBilled:
    def test_leisure_bills_enforced_seconds_unattributed(self) -> None:
        state, leisure = _bill(ShadowVerdict(paused_by=None, keys=("app:mpv",)))
        assert (state.seconds, state.per_game, leisure) == (3.0, {}, True)
        assert state.last_tick_at == _NOW.timestamp()

    def test_a_game_tick_credits_the_game(self) -> None:
        verdict = ShadowVerdict(paused_by=None, keys=("app:440",))
        state, _ = _bill(verdict, {7: "app:440"})
        assert state.per_game == {"app:440": 3.0}

    def test_paused_bills_nothing_even_with_a_game(self) -> None:
        verdict = ShadowVerdict(paused_by="i3lock", keys=())
        state, leisure = _bill(verdict, {7: "app:440"})
        assert (state.seconds, state.per_game, leisure) == (0.0, {}, True)
        assert state.last_tick_at == _NOW.timestamp()

    def test_free_bills_nothing(self) -> None:
        state, _ = _bill(ShadowVerdict(paused_by=None, keys=()))
        assert state.seconds == 0.0

    def test_enforced_and_shadow_move_together(self) -> None:
        verdicts = (
            ShadowVerdict(paused_by=None, keys=("domain:youtube.com",)),
            ShadowVerdict(paused_by="i3lock", keys=()),
            ShadowVerdict(paused_by=None, keys=()),
            ShadowVerdict(paused_by=None, keys=("app:440", "app:mpv")),
        )
        state = _start()
        for i, verdict in enumerate(verdicts):
            now = _NOW + timedelta(seconds=3 * i)
            before = state
            state = shadow_accumulate(
                state, stamp=now.timestamp(), interval=3.0, verdict=verdict
            )
            tick = Tick(now=now, interval=3.0, owners={}, verdict=verdict)
            state = leisure_billed(state, tick)
            moved = state.seconds - before.seconds
            assert moved == state.shadow_seconds - before.shadow_seconds


class TestDormantBilling:
    def test_games_only_and_rules_untouched(self) -> None:
        verdict = ShadowVerdict(paused_by=None, keys=("app:mpv",))
        state, leisure = _bill(verdict)
        assert (state.seconds, leisure) == (0.0, False)
        state, _ = _bill(ShadowVerdict(paused_by="i3lock", keys=()), {7: "app:440"})
        assert state.per_game == {"app:440": 3.0}

    def test_a_demo_is_never_live(self, live: None) -> None:
        del live
        demo = PlaytimeRules(
            1.0, (), 1.0, count_launchers=False, enforcement=True, demo=True
        )
        verdict = ShadowVerdict(paused_by=None, keys=("app:mpv",))
        state, rules = bill_tick(_start(), demo, _tick(verdict))
        assert (state.seconds, rules) == (0.0, demo)
