"""Tests for _ledger_earners and the generic earner path in resolve_budget.

An earner registered in ``earned_time`` after workout, LeetCode and reading has
no module of its own here: :func:`ledger_answer` reads its signed ledger, and
``resolve_budget`` adds its term. These tests register a stand-in earner by
patching ``earned_time.EARNERS`` -- the registry ``resolve_budget`` reads, and
passes on to ``earned_time.resolve``, at call time.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import earned_time
import pytest

from steam_backlog_enforcer import _ledger_earners, _leetcode_bonus, _workout_budget
from steam_backlog_enforcer._budget_resolve import BudgetResolution, resolve_budget
from steam_backlog_enforcer._ledger_earners import ledger_answer, reset_cache
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._budget_dates import AFTER_CUT, pin_today
from steam_backlog_enforcer.tests._ledger_fixtures import KEY, credit, write_ledger

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._ledger_earners"
_WORKOUT = "steam_backlog_enforcer._workout_budget._fetch_workout_today"
_LEETCODE = "steam_backlog_enforcer._leetcode_bonus.read_ledger_solved_today"
_ANSWER = "steam_backlog_enforcer._budget_resolve.ledger_answer"
_HOUR = 3600.0


def _any_credit(_row: dict[str, object], _window: tuple[float, float]) -> bool:
    """Count every verified credit: the reader's own dating is earned_time's."""
    return True


ANKI = earned_time.Earner(
    name="anki",
    label="Anki",
    gaming_minutes=30,
    shutdown_minutes=30,
    ledger=".local/share/anki_guard/ledger.json",
    match=_any_credit,
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


class TestLedgerAnswer:
    """One earner's answer from its ledger, memoised like the others."""

    def test_an_earner_without_a_ledger_earns_nothing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No ledger and no reader here is "cannot check", and says so.

        Args:
            caplog: pytest's log capture.
        """
        with caplog.at_level(logging.WARNING):
            assert ledger_answer(replace(ANKI, ledger=None)) is None
        assert "Earner Anki has no ledger" in caplog.text

    def test_reads_the_ledger_under_the_home_directory(self, tmp_path: Path) -> None:
        """A signed credit in ``LEDGER_HOME / earner.ledger`` counts.

        Args:
            tmp_path: pytest's temporary directory (conftest's LEDGER_HOME).
        """
        assert ANKI.ledger is not None
        ledger_dir = (tmp_path / ANKI.ledger).parent
        ledger_dir.mkdir(parents=True)
        write_ledger(ledger_dir, [credit(when=datetime.now().astimezone())])
        key = tmp_path / "hmac.key"
        key.write_bytes(KEY)
        with patch(f"{_PKG}.HMAC_KEY_FILE", key):
            assert ledger_answer(ANKI) is True

    @pytest.mark.parametrize("answer", [True, False])
    def test_an_answer_is_cached(self, *, answer: bool) -> None:
        """A yes and a no are both served from the memo on the next tick.

        Args:
            answer: The answer the ledger gives.
        """
        with patch("earned_time.done_today", return_value=answer) as read:
            assert ledger_answer(ANKI) is answer
            assert ledger_answer(ANKI) is answer
        assert read.call_count == 1

    def test_a_failure_is_not_cached(self) -> None:
        with patch("earned_time.done_today", return_value=None) as read:
            assert ledger_answer(ANKI) is None
            assert ledger_answer(ANKI) is None
        assert read.call_count == 2

    def test_reset_cache_forces_a_reread(self) -> None:
        with patch("earned_time.done_today", return_value=True) as read:
            ledger_answer(ANKI)
            reset_cache()
            ledger_answer(ANKI)
        assert read.call_count == 2


def _resolve(
    *, answer: bool | None, earner: earned_time.Earner = ANKI
) -> BudgetResolution:
    """Resolve with ``earner`` registered, the three built-ins all "no".

    Args:
        answer: What the extra earner's ledger says.
        earner: The extra earner to register.

    Returns:
        The resolved budget.
    """
    with (
        pin_today(AFTER_CUT),
        patch("earned_time.EARNERS", (*earned_time.EARNERS, earner)),
        patch(_WORKOUT, return_value=False),
        patch(_LEETCODE, return_value=False),
        patch(_ANSWER, return_value=answer) as asked,
    ):
        resolved = resolve_budget(Config())
    asked.assert_called_once_with(earner)
    return resolved


class TestAGenericEarnerInTheBudget:
    """A registered earner joins the sum with no code of its own here."""

    def test_its_credit_adds_its_term(self) -> None:
        resolved = _resolve(answer=True)
        assert resolved.seconds == 4.5 * _HOUR
        assert resolved.earned_seconds["anki"] == 0.5 * _HOUR
        assert resolved.reason.endswith(", Anki credited")

    def test_no_credit_adds_nothing(self) -> None:
        resolved = _resolve(answer=False)
        assert resolved.seconds == 4 * _HOUR
        assert resolved.earned_seconds["anki"] == 0.0
        assert "no Anki credited" in resolved.reason

    def test_unknown_adds_nothing_and_reads_differently(self) -> None:
        resolved = _resolve(answer=None)
        assert resolved.seconds == 4 * _HOUR
        assert "Anki unknown" in resolved.reason

    def test_its_penalty_lowers_the_base_by_what_it_pays_back(self) -> None:
        """Penalty, then reward: skipping it costs exactly its term."""
        penalised = replace(ANKI, penalty_from=AFTER_CUT)
        missed = _resolve(answer=False, earner=penalised)
        earned = _resolve(answer=True, earner=penalised)
        assert missed.base_seconds == 3.5 * _HOUR
        assert missed.seconds == 3.5 * _HOUR
        assert earned.seconds == 4 * _HOUR

    def test_the_built_in_earners_are_not_read_twice(self) -> None:
        """Only an earner with no dedicated reader goes through the ledger path."""
        with (
            pin_today(AFTER_CUT),
            patch(_WORKOUT, return_value=False),
            patch(_LEETCODE, return_value=False),
            patch(_ANSWER) as asked,
        ):
            resolved = resolve_budget(Config())
        asked.assert_not_called()
        assert set(resolved.earned_seconds) == {"workout", "leetcode", "reading"}
