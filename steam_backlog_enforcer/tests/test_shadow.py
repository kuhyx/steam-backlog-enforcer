"""Tests for shadow leisure billing (contract C4): verdict and accumulation."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from leisure_watch.facts import Focus, Now, Reason
import pytest

from steam_backlog_enforcer import _shadow
from steam_backlog_enforcer._playtime_record import ShadowLedger
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
    """Build a now.json fact in the given state with one reason per key."""
    reasons = tuple(Reason("focus", key, None, key) for key in keys)
    return Now(ts=T0, seq=1, state=state, paused_by=None, reasons=reasons, focus=_FOCUS)


def _state(**over: object) -> PlaytimeState:
    """Return a mid-day playtime state with the given fields overridden."""
    base = PlaytimeState(day_key="2026-10-19", last_tick_at=T0, seconds=50.0)
    return replace(base, **over)


class TestShadowKeys:
    """The shadow bills running games first, then the watcher's reasons."""

    def test_games_win_over_the_watcher(self) -> None:
        """Running games are billed, sorted and deduplicated, ahead of the watcher."""
        owners = {2: "app:9", 1: "app:440", 3: "app:9"}
        keys = shadow_keys(owners, _now("leisure", "domain:youtube.com"))
        assert keys == ("app:440", "app:9")

    def test_a_missing_fact_fails_closed(self) -> None:
        """No watcher fact bills the fail-closed key."""
        assert shadow_keys({}, None) == (FAILCLOSED_KEY,)

    def test_leisure_uses_the_reason_keys_deduplicated(self) -> None:
        """A leisure fact bills each reason key once, in order."""
        fact = _now("leisure", "domain:youtube.com", "app:mpv", "app:mpv")
        assert shadow_keys({}, fact) == ("domain:youtube.com", "app:mpv")

    def test_leisure_without_reasons_fails_closed(self) -> None:
        """A leisure fact with no reasons bills the fail-closed key."""
        assert shadow_keys({}, _now("leisure")) == (FAILCLOSED_KEY,)

    @pytest.mark.parametrize("state", ["free", "paused"])
    def test_free_or_watcher_paused_bills_nothing(self, state: str) -> None:
        """A free or paused watcher bills nothing."""
        assert shadow_keys({}, _now(state, "x")) == ()


class TestVerdictState:
    """A verdict's state follows from its pause and keys."""

    def test_paused(self) -> None:
        """A verdict with a pauser is paused."""
        assert ShadowVerdict(paused_by="i3lock", keys=()).state == "paused"

    def test_leisure(self) -> None:
        """A verdict with keys and no pauser is leisure."""
        assert ShadowVerdict(paused_by=None, keys=("a",)).state == "leisure"

    def test_free(self) -> None:
        """A verdict with neither is free."""
        assert ShadowVerdict(paused_by=None, keys=()).state == "free"


class TestObserveShadow:
    """observe_shadow reads the lock claims and the watcher fact."""

    def test_paused_skips_the_fact_file(self) -> None:
        """A held lock short-circuits before the fact file is read."""
        with (
            patch.object(_shadow, "paused_by", return_value="gatelock:x") as lock,
            patch.object(_shadow, "read_now") as read,
        ):
            verdict = observe_shadow({1: "app:440"}, stamp=T0)
        assert verdict == ShadowVerdict(paused_by="gatelock:x", keys=())
        lock.assert_called_once_with(_shadow.CLAIMS_DIR)
        read.assert_not_called()

    def test_reads_the_fact_once_with_the_contract_age(self) -> None:
        """The fact is read once with the contract's 15 s max age."""
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
        """The fact and claims paths live in uid 1000's runtime dir."""
        assert str(_shadow.NOW_PATH) == "/run/user/1000/leisure-watch/now.json"
        assert str(_shadow.CLAIMS_DIR) == "/run/user/1000/gatelock/claims"


class TestShadowAccumulate:
    """Shadow billing splits each tick across sources, leaving enforced fields."""

    def _bill(self, state: PlaytimeState, verdict: ShadowVerdict) -> PlaytimeState:
        """Bill one 3 s tick of state under verdict."""
        return shadow_accumulate(state, stamp=T0 + 3.0, interval=3.0, verdict=verdict)

    def test_first_tick_credits_nothing(self) -> None:
        """The first tick ever credits nothing."""
        state = _state(last_tick_at=0.0)
        assert self._bill(state, ShadowVerdict(None, ("a",))) == state

    def test_a_backward_clock_credits_nothing(self) -> None:
        """A clock step backwards credits nothing."""
        state = _state(last_tick_at=T0 + 10.0)
        assert self._bill(state, ShadowVerdict(None, ("a",))) == state

    def test_paused_goes_to_paused_seconds_only(self) -> None:
        """A paused tick only adds to paused seconds."""
        out = self._bill(_state(), ShadowVerdict("i3lock", ()))
        assert out.shadow.paused_seconds == 3.0
        assert out.shadow.seconds == 0.0
        assert out.shadow.per_source == {}

    def test_free_bills_nothing(self) -> None:
        """A free tick leaves the state unchanged."""
        state = _state()
        assert self._bill(state, ShadowVerdict(None, ())) == state

    def test_one_source_takes_the_whole_tick(self) -> None:
        """A single source is billed the whole tick."""
        out = self._bill(_state(), ShadowVerdict(None, ("app:440",)))
        assert out.shadow.seconds == 3.0
        assert out.shadow.per_source == {"app:440": 3.0}

    def test_overlapping_sources_bill_once_and_split(self) -> None:
        """Overlapping sources share one tick, never billing it twice."""
        state = _state(shadow=ShadowLedger(per_source={"a": 1.0}, seconds=1.0))
        out = self._bill(state, ShadowVerdict(None, ("a", "b")))
        assert out.shadow.seconds == 4.0
        assert out.shadow.per_source == {"a": 2.5, "b": 1.5}
        assert sum(out.shadow.per_source.values()) <= out.shadow.seconds + 1e-9

    def test_the_delta_is_clamped_like_the_enforced_one(self) -> None:
        """A long gap is clamped exactly like the enforced budget."""
        out = shadow_accumulate(
            _state(),
            stamp=T0 + 3600.0,
            interval=3.0,
            verdict=ShadowVerdict(None, (FAILCLOSED_KEY,)),
        )
        assert out.shadow.seconds == 6.0

    def test_never_touches_enforced_fields(self) -> None:
        """Shadow billing leaves every enforced field as it was."""
        state = _state(per_game={"app:1": 5.0}, last_credited_key="app:1")
        out = self._bill(state, ShadowVerdict(None, ("app:440",)))
        assert (out.seconds, out.last_tick_at, out.per_game) == (
            state.seconds,
            state.last_tick_at,
            state.per_game,
        )
        assert out.last_credited_key == "app:1"
