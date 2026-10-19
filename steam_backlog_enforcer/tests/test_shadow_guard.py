"""The shadow path can never raise into the enforce loop (no per-tick guard).

Any exception from ``leisure_watch`` (a ``RecursionError`` was observed, not
just ``OSError``/``ValueError``) must fail the shadow closed, log at most once
per distinct error per window, and leave the enforced count untouched.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _shadow
from steam_backlog_enforcer._playtime import playtime_tick
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    load_state,
    save_state,
)
from steam_backlog_enforcer._shadow import FAILCLOSED_KEY, ShadowVerdict, observe_shadow
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._fake_session import fake_session

if TYPE_CHECKING:
    from collections.abc import Iterator

PKG = "steam_backlog_enforcer._playtime"
NOW = datetime(2026, 7, 27, 20, 0, tzinfo=timezone(timedelta(hours=2)))
T0 = NOW.timestamp()


@pytest.fixture(autouse=True)
def _fresh_warnings() -> Iterator[None]:
    """Each test starts with no error already logged."""
    _shadow.reset_warnings()
    yield
    _shadow.reset_warnings()


@pytest.fixture
def quiet_tick() -> Iterator[None]:
    """Neutralise the tick's side effects (cutoff, mounts, total block)."""
    cutoff = "steam_backlog_enforcer._playtime_cutoff"
    with ExitStack() as stack:
        for name in ("reconcile", "request_steam_shutdown", "kill_gaming_processes"):
            stack.enter_context(patch(f"{cutoff}.{name}"))
        stack.enter_context(patch(f"{cutoff}.notify_desktop_user"))
        stack.enter_context(patch(f"{PKG}.mounted_targets", return_value=set()))
        stack.enter_context(patch(f"{PKG}.is_total_block_active", return_value=False))
        yield


@pytest.mark.parametrize("where", ["paused_by", "read_now"])
@pytest.mark.parametrize("exc", [RecursionError("deep"), RuntimeError("boom")])
def test_any_exception_fails_closed(where: str, exc: Exception) -> None:
    with patch.object(_shadow, where, side_effect=exc):
        game = observe_shadow({1: "app:440"}, stamp=T0)
        idle = observe_shadow({}, stamp=T0)
    assert game == ShadowVerdict(paused_by=None, keys=("app:440",))
    assert idle == ShadowVerdict(paused_by=None, keys=(FAILCLOSED_KEY,))


def test_a_successful_pause_check_still_pauses() -> None:
    """Only the fact read failed: the lock answer stands, nothing bills."""
    with (
        patch.object(_shadow, "paused_by", return_value="i3lock"),
        patch.object(_shadow, "read_now", side_effect=RecursionError("deep")),
    ):
        assert observe_shadow({}, stamp=T0) == ShadowVerdict("i3lock", ())


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_logs_once_per_distinct_error_per_window(
    caplog: pytest.LogCaptureFixture,
) -> None:
    errors = [RecursionError("deep")] * 3 + [RuntimeError("other")]
    with (
        caplog.at_level(logging.WARNING, logger=_shadow.__name__),
        patch.object(_shadow, "read_now", side_effect=errors),
        patch.object(_shadow.time, "monotonic", return_value=100.0),
    ):
        for _ in errors:
            observe_shadow({}, stamp=T0)
    logged = _warnings(caplog)
    assert len(logged) == 2
    assert "deep" in logged[0]
    assert "other" in logged[1]


def test_logs_again_after_the_window(caplog: pytest.LogCaptureFixture) -> None:
    window = _shadow.WARN_EVERY_SECONDS
    clock = [100.0, 100.0 + window - 1, 100.0 + window + 1]
    with (
        caplog.at_level(logging.WARNING, logger=_shadow.__name__),
        patch.object(_shadow, "read_now", side_effect=RecursionError("deep")),
        patch.object(_shadow.time, "monotonic", side_effect=clock),
    ):
        for _ in clock:
            observe_shadow({}, stamp=T0)
    assert len(_warnings(caplog)) == 2


@pytest.mark.usefixtures("quiet_tick")
@pytest.mark.parametrize("where", ["paused_by", "read_now"])
@pytest.mark.parametrize(
    ("owners", "seconds", "shadow"),
    [({7: "app:440"}, 3.0, "app:440"), ({}, 0.0, FAILCLOSED_KEY)],
)
def test_tick_completes_and_enforced_count_is_untouched(
    where: str, owners: dict[int, str], seconds: float, shadow: str
) -> None:
    save_state(PlaytimeState(day_key="2026-07-27", last_tick_at=T0 - 3.0), demo=False)
    with (
        patch.object(_shadow, where, side_effect=RecursionError("deep")),
        patch(f"{PKG}.qualifying_pids", return_value=owners),
        patch(f"{PKG}.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = NOW
        playtime_tick(Config(), interval=3.0, session=fake_session())
    state = load_state(demo=False)
    assert state.seconds == seconds
    assert state.last_tick_at == T0
    assert state.shadow_per_source == {shadow: 3.0}
