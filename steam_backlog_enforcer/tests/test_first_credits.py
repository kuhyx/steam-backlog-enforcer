"""Tests for _ledger_earners.first_credits: maturity only delays a penalty.

A stand-in earner (``piano``) is registered with a penalty. Its signed ledger
lives under the suite's redirected ``LEDGER_HOME``; whether it has ever paid
out decides the first day its cut applies (earned_time 0.6.0), and on an
earned_time without ``maturity`` the budget resolves exactly as 0.5.0 did.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import earned_time
import pytest

from steam_backlog_enforcer import _ledger_earners, _leetcode_bonus, _workout_budget
from steam_backlog_enforcer._budget_resolve import resolve_budget
from steam_backlog_enforcer._ledger_earners import first_credits
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._budget_dates import AFTER_CUT, pin_today
from steam_backlog_enforcer.tests._ledger_fixtures import KEY, credit, write_ledger

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import date
    from pathlib import Path

_WORKOUT = "steam_backlog_enforcer._workout_budget._fetch_workout_today"
_LEETCODE = "steam_backlog_enforcer._leetcode_bonus.read_ledger_solved_today"
_ANSWER = "steam_backlog_enforcer._budget_resolve.ledger_answer"
_HOUR = 3600.0
_DAY = timedelta(days=1)


def _any_credit(_row: dict[str, object], _window: tuple[float, float]) -> bool:
    """Count every verified credit: the reader's own dating is earned_time's."""
    return True


# Penalised since well before the suite's pinned day, never confirmed by kuhy:
# without a real credit it is a new gate and costs nothing.
PIANO = earned_time.Earner(
    name="piano",
    label="Piano",
    gaming_minutes=30,
    shutdown_minutes=30,
    ledger=".local/share/piano_guard/ledger.json",
    match=_any_credit,
    penalty_from=AFTER_CUT - 5 * _DAY,
)


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    """Keep every earner memo from leaking answers between tests.

    Yields:
        None, with the caches empty before and after.
    """
    for module in (_ledger_earners, _workout_budget, _leetcode_bonus):
        module.reset_cache()
    yield
    for module in (_ledger_earners, _workout_budget, _leetcode_bonus):
        module.reset_cache()


@pytest.fixture
def key(tmp_path: Path) -> Iterator[Path]:
    """Sign and verify the stand-in's ledger with a throwaway key.

    Args:
        tmp_path: pytest's temporary directory (also ``LEDGER_HOME``).

    Yields:
        The key path, patched into ``_ledger_earners``.
    """
    path = tmp_path / "hmac.key"
    path.write_bytes(KEY)
    with patch.object(_ledger_earners, "HMAC_KEY_FILE", path):
        yield path


def _credit_on(home: Path, day: date) -> None:
    """Write the stand-in's ledger with one signed credit at noon on ``day``."""
    ledger = home / str(PIANO.ledger)
    ledger.parent.mkdir(parents=True)
    when = datetime.combine(day, time(12)).astimezone()
    write_ledger(ledger.parent, [credit(when=when, entry_id="piano:1")])


def _base(day: date) -> float:
    """``resolve_budget``'s floor on ``day`` with ``piano`` registered, all "no"."""
    with (
        pin_today(day),
        patch("earned_time.EARNERS", (*earned_time.EARNERS, PIANO)),
        patch(_WORKOUT, return_value=False),
        patch(_LEETCODE, return_value=False),
        patch(_ANSWER, return_value=False),
    ):
        return resolve_budget(Config()).base_seconds


class TestTheMap:
    """Only penalised, ledger-backed earners, keyed by name."""

    def test_maps_each_penalised_reader_to_its_first_credit(
        self, tmp_path: Path, key: Path
    ) -> None:
        """A bonus, a ledger-less earner and a matcher-less one are left out.

        Args:
            tmp_path: The suite's ``LEDGER_HOME``.
            key: The patched signing key.
        """
        assert key.exists()
        _credit_on(tmp_path, AFTER_CUT - _DAY)
        registry = (
            PIANO,
            replace(PIANO, name="bonus", penalty_from=None),
            replace(PIANO, name="no-ledger", ledger=None),
            replace(PIANO, name="no-match", match=None),
        )
        assert first_credits(registry, AFTER_CUT) == {"piano": AFTER_CUT - _DAY}

    def test_an_unreadable_ledger_is_no_first_credit(self) -> None:
        """No ledger and no key on record: ``None``, which resolve treats closed."""
        assert first_credits((PIANO,), AFTER_CUT) == {"piano": None}

    def test_an_old_earned_time_gets_no_map(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without ``maturity`` (< 0.6) there is nothing to pass on.

        Args:
            monkeypatch: pytest's attribute patcher.
        """
        monkeypatch.delattr(earned_time, "maturity")
        assert first_credits((PIANO,), AFTER_CUT) is None


class TestTheBudget:
    """The cut waits for the day after the first real credit."""

    def test_a_gate_that_never_paid_out_costs_nothing(self) -> None:
        assert _base(AFTER_CUT) == 4 * _HOUR

    def test_the_cut_starts_the_day_after_the_first_credit(
        self, tmp_path: Path, key: Path
    ) -> None:
        """Credited on the pinned day: free that day, penalised the next.

        Args:
            tmp_path: The suite's ``LEDGER_HOME``.
            key: The patched signing key.
        """
        assert key.exists()
        _credit_on(tmp_path, AFTER_CUT)
        assert _base(AFTER_CUT) == 4 * _HOUR
        assert _base(AFTER_CUT + _DAY) == 3.5 * _HOUR

    def test_an_old_earned_time_resolves_as_before(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No ``maturity``, no ``first_credits``: ``penalty_from`` alone cuts.

        Args:
            monkeypatch: pytest's attribute patcher.
        """
        monkeypatch.delattr(earned_time, "maturity")
        assert _base(AFTER_CUT) == 3.5 * _HOUR
