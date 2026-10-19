"""Tests for shadow leisure billing (contract C4): verdict and accumulation."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from leisure_watch.facts import Focus, Now, Reason
import pytest

from steam_backlog_enforcer import _shadow
from steam_backlog_enforcer._playtime_state import PlaytimeState
from steam_backlog_enforcer._shadow import (
    FAILCLOSED_KEY,
    ShadowVerdict,
    observe_shadow,
    shadow_accumulate,
    shadow_keys,
)

T0 = 1_760_000_000.0
_FOCUS = Focus(app="Helium", title="t", domain="youtube.com", idle=False)


def _now(state: str, *keys: str) -> Now:
    reasons = tuple(Reason("focus", key, None, key) for key in keys)
    return Now(ts=T0, seq=1, state=state, paused_by=None, reasons=reasons, focus=_FOCUS)


def _state(**over: object) -> PlaytimeState:
    base = PlaytimeState(day_key="2026-10-19", last_tick_at=T0, seconds=50.0)
    return replace(base, **over)


class TestShadowKeys:
    def test_games_win_over_the_watcher(self) -> None:
        owners = {2: "app:9", 1: "app:440", 3: "app:9"}
        keys = shadow_keys(owners, _now("leisure", "domain:youtube.com"))
        assert keys == ("app:440", "app:9")

    def test_a_missing_fact_fails_closed(self) -> None:
        assert shadow_keys({}, None) == (FAILCLOSED_KEY,)

    def test_leisure_uses_the_reason_keys_deduplicated(self) -> None:
        fact = _now("leisure", "domain:youtube.com", "app:mpv", "app:mpv")
        assert shadow_keys({}, fact) == ("domain:youtube.com", "app:mpv")

    def test_leisure_without_reasons_fails_closed(self) -> None:
        assert shadow_keys({}, _now("leisure")) == (FAILCLOSED_KEY,)

    @pytest.mark.parametrize("state", ["free", "paused"])
    def test_free_or_watcher_paused_bills_nothing(self, state: str) -> None:
        assert shadow_keys({}, _now(state, "x")) == ()


class TestVerdictState:
    def test_paused(self) -> None:
        assert ShadowVerdict(paused_by="i3lock", keys=()).state == "paused"

    def test_leisure(self) -> None:
        assert ShadowVerdict(paused_by=None, keys=("a",)).state == "leisure"

    def test_free(self) -> None:
        assert ShadowVerdict(paused_by=None, keys=()).state == "free"


class TestObserveShadow:
    def test_paused_skips_the_fact_file(self) -> None:
        with (
            patch.object(_shadow, "paused_by", return_value="gatelock:x") as lock,
            patch.object(_shadow, "read_now") as read,
        ):
            verdict = observe_shadow({1: "app:440"}, stamp=T0)
        assert verdict == ShadowVerdict(paused_by="gatelock:x", keys=())
        lock.assert_called_once_with(_shadow.CLAIMS_DIR)
        read.assert_not_called()

    def test_reads_the_fact_once_with_the_contract_age(self) -> None:
        fact = _now("leisure", "domain:youtube.com")
        with (
            patch.object(_shadow, "paused_by", return_value=None),
            patch.object(_shadow, "read_now", return_value=fact) as read,
        ):
            verdict = observe_shadow({}, stamp=T0)
        assert verdict.keys == ("domain:youtube.com",)
        read.assert_called_once_with(_shadow.NOW_PATH, T0, max_age=15)

    @pytest.mark.parametrize("where", ["paused_by", "read_now"])
    def test_a_failing_input_fails_closed_instead_of_raising(self, where: str) -> None:
        """The enforce loop has no per-tick guard: a raise would crash-loop it."""
        with (
            patch.object(_shadow, "paused_by", return_value=None),
            patch.object(_shadow, "read_now", return_value=None),
            patch.object(_shadow, where, side_effect=PermissionError("denied")),
        ):
            assert observe_shadow({1: "app:440"}, stamp=T0) == ShadowVerdict(
                paused_by=None, keys=("app:440",)
            )
            assert observe_shadow({}, stamp=T0).keys == (FAILCLOSED_KEY,)

    def test_root_paths_are_the_desktop_users(self) -> None:
        assert str(_shadow.NOW_PATH) == "/run/user/1000/leisure-watch/now.json"
        assert str(_shadow.CLAIMS_DIR) == "/run/user/1000/gatelock/claims"


class TestShadowAccumulate:
    def _bill(self, state: PlaytimeState, verdict: ShadowVerdict) -> PlaytimeState:
        return shadow_accumulate(state, stamp=T0 + 3.0, interval=3.0, verdict=verdict)

    def test_first_tick_credits_nothing(self) -> None:
        state = _state(last_tick_at=0.0)
        assert self._bill(state, ShadowVerdict(None, ("a",))) == state

    def test_a_backward_clock_credits_nothing(self) -> None:
        state = _state(last_tick_at=T0 + 10.0)
        assert self._bill(state, ShadowVerdict(None, ("a",))) == state

    def test_paused_goes_to_paused_seconds_only(self) -> None:
        out = self._bill(_state(), ShadowVerdict("i3lock", ()))
        assert out.shadow_paused_seconds == 3.0
        assert out.shadow_seconds == 0.0
        assert out.shadow_per_source == {}

    def test_free_bills_nothing(self) -> None:
        state = _state()
        assert self._bill(state, ShadowVerdict(None, ())) == state

    def test_one_source_takes_the_whole_tick(self) -> None:
        out = self._bill(_state(), ShadowVerdict(None, ("app:440",)))
        assert out.shadow_seconds == 3.0
        assert out.shadow_per_source == {"app:440": 3.0}

    def test_overlapping_sources_bill_once_and_split(self) -> None:
        state = _state(shadow_per_source={"a": 1.0}, shadow_seconds=1.0)
        out = self._bill(state, ShadowVerdict(None, ("a", "b")))
        assert out.shadow_seconds == 4.0
        assert out.shadow_per_source == {"a": 2.5, "b": 1.5}
        assert sum(out.shadow_per_source.values()) <= out.shadow_seconds + 1e-9

    def test_the_delta_is_clamped_like_the_enforced_one(self) -> None:
        out = shadow_accumulate(
            _state(),
            stamp=T0 + 3600.0,
            interval=3.0,
            verdict=ShadowVerdict(None, (FAILCLOSED_KEY,)),
        )
        assert out.shadow_seconds == 6.0

    def test_never_touches_enforced_fields(self) -> None:
        state = _state(per_game={"app:1": 5.0}, last_credited_key="app:1")
        out = self._bill(state, ShadowVerdict(None, ("app:440",)))
        assert (out.seconds, out.last_tick_at, out.per_game) == (
            state.seconds,
            state.last_tick_at,
            state.per_game,
        )
        assert out.last_credited_key == "app:1"
