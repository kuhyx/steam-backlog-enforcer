"""The enforced budget is priced by the 06:00 gaming day, like billing.

earned_time 0.16.0: ``resolve(leisure=False)`` forces pre-leisure pricing, so
the enforcer asks ``leisure_active`` for the gaming day itself; 00:00-05:59 on
the go-live date still belongs to the day before.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import earned_time
import pytest

from steam_backlog_enforcer._budget_resolve import resolve_budget
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._budget_dates import AFTER_CUT
from steam_backlog_enforcer.tests._isolate_leisure import switch_file

if TYPE_CHECKING:
    from pathlib import Path

_HOUR = 3600.0


def _at(hour: int) -> MagicMock:
    """A ``datetime`` stand-in whose ``now().astimezone()`` is AFTER_CUT at *hour*."""
    clock = MagicMock()
    clock.now.return_value.astimezone.return_value = datetime.combine(
        AFTER_CUT, time(hour)
    ).astimezone()
    return clock


def _resolve(hour: int) -> tuple[float, list[object]]:
    """Enforced base seconds at *hour*, and every ``leisure=`` resolve was given."""
    with (
        patch("steam_backlog_enforcer._budget_resolve.datetime", _at(hour)),
        patch.object(earned_time, "resolve", wraps=earned_time.resolve) as spy,
    ):
        base = resolve_budget(Config()).base_seconds
    return base, [c.kwargs["leisure"] for c in spy.call_args_list]


@pytest.fixture
def dormant(tmp_path: Path) -> float:
    """The dormant base at noon, then the switch dated the go-live day."""
    base = _resolve(12)[0]
    switch_file(tmp_path).write_text(AFTER_CUT.isoformat() + "\n", encoding="ascii")
    return base


def test_dormant_prices_pre_leisure_with_a_leisure_shadow() -> None:
    assert _resolve(12)[1] == [False, True]


@pytest.mark.parametrize("hour", [6, 12, 23])
def test_the_go_live_gaming_day_is_priced_as_leisure(dormant: float, hour: int) -> None:
    base, leisure = _resolve(hour)
    assert leisure == [True, True]
    assert base - dormant == 2 * _HOUR


@pytest.mark.parametrize("hour", [0, 3, 5])
def test_before_06_on_the_go_live_date_stays_pre_leisure(
    dormant: float, hour: int
) -> None:
    base, leisure = _resolve(hour)
    assert leisure == [False, True]
    assert base == dormant


def test_a_switch_dated_tomorrow_is_dormant_today(tmp_path: Path) -> None:
    tomorrow = (AFTER_CUT + timedelta(days=1)).isoformat()
    switch_file(tmp_path).write_text(tomorrow + "\n", encoding="ascii")
    assert _resolve(12)[1] == [False, True]
