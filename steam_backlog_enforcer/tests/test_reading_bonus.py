"""Tests for _reading_bonus: which book-guard ledger rows buy today's hour.

Mirrors ``test_leetcode_ledger.py``: signed rows built with the shared
``sign`` helper, a throwaway key patched into *this* module's binding (it
imports ``HMAC_KEY_FILE`` by name, so the LeetCode ``key_file`` fixture does
not reach it), and every failure mode pinned to ``None`` -- never "did not
read".
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._reading_bonus import (
    read_ledger_read_today,
    read_today,
    reset_cache,
)
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._ledger_fixtures import KEY, sign, write_ledger

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._reading_bonus"


@pytest.fixture(autouse=True)
def reading_key(tmp_path: Path) -> Iterator[Path]:
    """Point the module at a throwaway signing key and an empty memo.

    Args:
        tmp_path: pytest's temporary directory.

    Yields:
        The key path, with the module patched to use it.
    """
    path = tmp_path / "reading-hmac.key"
    path.write_bytes(KEY)
    reset_cache()
    with patch(f"{_PKG}.HMAC_KEY_FILE", path):
        yield path
    reset_cache()


def reading(
    *,
    when: datetime,
    bonus: str = "1",
    kind: str = "credit",
    detail: object = None,
) -> dict[str, Any]:
    """Build a signed book-guard row for a session that ended at *when*.

    Args:
        when: When the reading session ended.
        bonus: The ``detail["bonus"]`` flag; ``"1"`` earns the hour.
        kind: The row kind.
        detail: A replacement ``detail`` value, overriding the two above.

    Returns:
        A signed ledger row.
    """
    body = {"bonus": bonus, "ended_at": str(int(when.timestamp()))}
    return sign(
        {
            "entry_id": f"read:{when.isoformat()}:{bonus}",
            "kind": kind,
            "day": when.date().isoformat(),
            "created_at": when.isoformat(),
            "amount": 1,
            "device": "pc",
            "detail": body if detail is None else detail,
        }
    )


def _now() -> datetime:
    return datetime.now().astimezone()


class TestWhichRowsCount:
    """Only a signed, bonus-eligible credit that ended today counts."""

    def test_a_bonus_credit_today_counts(self, tmp_path: Path) -> None:
        ledger = write_ledger(tmp_path, [reading(when=_now())])
        assert read_ledger_read_today(ledger) is True

    def test_yesterdays_reading_does_not(self, tmp_path: Path) -> None:
        yesterday = _now() - timedelta(days=1)
        assert (
            read_ledger_read_today(write_ledger(tmp_path, [reading(when=yesterday)]))
            is False
        )

    @pytest.mark.parametrize(
        "row",
        [
            pytest.param({"kind": "credit"}, id="unsigned"),
            pytest.param("not-a-row", id="not-a-dict"),
        ],
    )
    def test_malformed_rows_are_skipped(self, tmp_path: Path, row: object) -> None:
        """Rows that are not signed dicts contribute nothing and do not crash.

        Args:
            tmp_path: pytest's temporary directory.
            row: The malformed row.
        """
        ledger = tmp_path / "ledger.json"
        ledger.write_text(json.dumps({"entries": [row]}), encoding="utf-8")
        assert read_ledger_read_today(ledger) is False

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"kind": "charge"}, id="charge"),
            pytest.param({"bonus": "0"}, id="no-bonus"),
            pytest.param({"detail": "flat"}, id="detail-not-dict"),
            pytest.param({"detail": {"bonus": "1"}}, id="no-ended-at"),
            pytest.param({"detail": {"bonus": "1", "ended_at": "soon"}}, id="bad-ts"),
        ],
    )
    def test_ineligible_rows_do_not_count(
        self, tmp_path: Path, overrides: dict[str, Any]
    ) -> None:
        """Signed but not a bonus-earning session today.

        Args:
            tmp_path: pytest's temporary directory.
            overrides: Keyword overrides for :func:`reading`.
        """
        ledger = write_ledger(tmp_path, [reading(when=_now(), **overrides)])
        assert read_ledger_read_today(ledger) is False

    def test_a_tampered_row_does_not_count(self, tmp_path: Path) -> None:
        row = reading(when=_now(), bonus="0")
        row["detail"]["bonus"] = "1"
        assert read_ledger_read_today(write_ledger(tmp_path, [row])) is False


class TestFailingClosed:
    """Anything unreadable is ``None``; only an absent ledger is a plain no."""

    def test_no_ledger_yet_is_an_honest_no(self, tmp_path: Path) -> None:
        assert read_ledger_read_today(tmp_path / "absent.json") is False

    def test_an_unreadable_ledger_is_none(self, tmp_path: Path) -> None:
        assert read_ledger_read_today(tmp_path) is None

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("{bad", id="bad-json"),
            pytest.param("[]", id="top-level-list"),
            pytest.param(json.dumps({"version": 1}), id="no-entries"),
            pytest.param(json.dumps({"entries": {}}), id="entries-not-list"),
        ],
    )
    def test_a_malformed_ledger_is_none(self, tmp_path: Path, text: str) -> None:
        """Bad JSON or a missing entries array is "could not check".

        Args:
            tmp_path: pytest's temporary directory.
            text: The ledger's content.
        """
        ledger = tmp_path / "ledger.json"
        ledger.write_text(text, encoding="utf-8")
        assert read_ledger_read_today(ledger) is None

    def test_a_missing_key_is_none(self, tmp_path: Path) -> None:
        ledger = write_ledger(tmp_path, [reading(when=_now())])
        with patch(f"{_PKG}.HMAC_KEY_FILE", tmp_path / "absent.key"):
            assert read_ledger_read_today(ledger) is None

    def test_an_empty_key_is_none(self, tmp_path: Path, reading_key: Path) -> None:
        reading_key.write_bytes(b"  \n")
        ledger = write_ledger(tmp_path, [reading(when=_now())])
        assert read_ledger_read_today(ledger) is None


class TestTheMemo:
    """Answers are cached like the other earners; failures are not."""

    def test_reads_the_configured_ledger(self, tmp_path: Path) -> None:
        ledger = write_ledger(tmp_path, [reading(when=_now())])
        assert read_today(Config(book_ledger_path=str(ledger))) is True

    def test_a_cached_answer_is_served_without_a_reread(self) -> None:
        with patch(f"{_PKG}.read_ledger_read_today", return_value=False) as read:
            assert read_today(Config()) is False
            assert read_today(Config()) is False
        assert read.call_count == 1

    def test_a_failure_is_not_cached(self) -> None:
        with patch(f"{_PKG}.read_ledger_read_today", return_value=None) as read:
            assert read_today(Config()) is None
            assert read_today(Config()) is None
        assert read.call_count == 2

    def test_reset_cache_forces_a_reread(self) -> None:
        with patch(f"{_PKG}.read_ledger_read_today", return_value=True) as read:
            read_today(Config())
            reset_cache()
            read_today(Config())
        assert read.call_count == 2

    def test_the_default_path_is_book_guards(self) -> None:
        assert Config().book_ledger_path.endswith("book_guard/ledger.json")
