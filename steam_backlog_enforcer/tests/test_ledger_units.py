"""Tests for counted gate earners (the Automation tutor) in the gaming budget.

A counted gate pays per unit -- one verified 15-minute tutor block each --
so :func:`ledger_units` reads its unit count for the day and
``resolve_budget`` turns it into gaming time through the registry. A stand-in
counted earner is registered by patching ``earned_time.EARNERS``, which both
the installed earned_time and the cutover one (``earners_for``) read.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import earned_time
import pytest

from steam_backlog_enforcer import _ledger_earners
from steam_backlog_enforcer._budget_resolve import BudgetResolution, resolve_budget
from steam_backlog_enforcer._budget_view import _most
from steam_backlog_enforcer._ledger_earners import ledger_units, reset_cache
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._budget_dates import AFTER_CUT, pin_today
from steam_backlog_enforcer.tests._ledger_fixtures import KEY, credit, write_ledger

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._ledger_earners"
_WORKOUT = "steam_backlog_enforcer._workout_budget._fetch_workout_today"
_LEETCODE = "steam_backlog_enforcer._leetcode_bonus.read_ledger_solved_today"
_UNITS = "steam_backlog_enforcer._budget_resolve.ledger_units"
_ANSWER = "steam_backlog_enforcer._budget_resolve.ledger_answer"


def _any_credit(_row: dict[str, object], _window: tuple[float, float]) -> bool:
    return True


BLOCKS = earned_time.Earner(
    name="blocks",
    label="Blocks",
    gaming_minutes=15,
    shutdown_minutes=13,
    kind="counted",
    ledger=".local/share/blocks_guard/ledger.json",
    match=_any_credit,
)


@pytest.fixture(autouse=True)
def _clear() -> Iterator[None]:
    """Start and end every test with empty memos.

    Yields:
        None.
    """
    reset_cache()
    yield
    reset_cache()


class TestLedgerUnits:
    def test_no_ledger_is_none_and_says_so(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert ledger_units(replace(BLOCKS, ledger=None)) is None
        assert "Earner Blocks has no ledger" in caplog.text

    def test_counts_the_signed_rows_under_home(self, tmp_path: Path) -> None:
        assert BLOCKS.ledger is not None
        ledger_dir = (tmp_path / BLOCKS.ledger).parent
        ledger_dir.mkdir(parents=True)
        now = datetime.now().astimezone()
        write_ledger(ledger_dir, [credit(when=now, entry_id=f"s-b{n}") for n in (1, 2)])
        key = tmp_path / "hmac.key"
        key.write_bytes(KEY)
        with patch(f"{_PKG}.HMAC_KEY_FILE", key):
            assert ledger_units(BLOCKS) == 2

    def test_a_count_is_cached_until_its_ttl(self) -> None:
        with (
            patch("earned_time.credit_units", return_value=3) as read,
            patch(f"{_PKG}.time.monotonic", side_effect=[0.0, 30.0, 61.0]),
        ):
            assert [ledger_units(BLOCKS) for _ in range(3)] == [3, 3, 3]
        assert read.call_count == 2

    def test_a_failure_is_not_cached(self) -> None:
        with patch("earned_time.credit_units", return_value=None) as read:
            assert ledger_units(BLOCKS) is None
            assert ledger_units(BLOCKS) is None
        assert read.call_count == 2

    def test_reset_cache_drops_counts(self) -> None:
        with patch("earned_time.credit_units", return_value=1) as read:
            ledger_units(BLOCKS)
            _ledger_earners.reset_cache()
            ledger_units(BLOCKS)
        assert read.call_count == 2


def _resolve(units: int | None) -> BudgetResolution:
    with (
        pin_today(AFTER_CUT),
        patch("earned_time.EARNERS", (*earned_time.EARNERS, BLOCKS)),
        patch(_WORKOUT, return_value=False),
        patch(_LEETCODE, return_value=False),
        patch(_ANSWER, return_value=False),
        patch(_UNITS, return_value=units) as asked,
    ):
        resolved = resolve_budget(Config())
    asked.assert_called_once_with(BLOCKS)
    return resolved


class TestACountedGateInTheBudget:
    def test_units_earn_through_the_registry(self) -> None:
        resolved = _resolve(2)
        assert resolved.earned_seconds["blocks"] == BLOCKS.gaming_for(2) * 60.0
        assert resolved.reason.endswith(", Blocks credited x2")

    def test_one_unit_reads_like_a_flat_credit(self) -> None:
        assert _resolve(1).reason.endswith(", Blocks credited")

    def test_none_and_unknown(self) -> None:
        assert "no Blocks credited" in _resolve(0).reason
        assert "Blocks unknown" in _resolve(None).reason


def test_view_lists_what_a_full_day_pays() -> None:
    # Duck-typed stand-ins: ``plain`` is a pre-0.5 earner without units.
    capped = SimpleNamespace(gaming_minutes=15, max_gaming_minutes=60)
    plain = SimpleNamespace(gaming_minutes=30)
    assert _most(cast("earned_time.Earner", capped)) == 60
    assert _most(cast("earned_time.Earner", plain)) == 30
