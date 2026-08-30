"""Tests for _leetcode_bonus: the two transports and the memo.

The chain is the point: the ledger answers first because it works when
leetcode-guard is not running, the endpoint covers an unreadable ledger, and
only the failure of *both* is ``None`` -- which the caller must turn into an
incident rather than a silent lost hour.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _leetcode_bonus
from steam_backlog_enforcer._leetcode_bonus import leetcode_solved_today, reset_cache
from steam_backlog_enforcer.config import Config

if TYPE_CHECKING:
    from collections.abc import Iterator

_PKG = "steam_backlog_enforcer._leetcode_bonus"


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Keep the module memo from leaking answers between tests.

    Yields:
        None, with the cache empty before and after.
    """
    reset_cache()
    yield
    reset_cache()


class TestTheFallbackChain:
    """Ledger first, endpoint second, None only when neither answers."""

    def test_the_ledger_wins_when_it_answers(self) -> None:
        """The endpoint must not be consulted when the file was readable."""
        with (
            patch(f"{_PKG}.read_ledger_solved_today", return_value=True),
            patch(f"{_PKG}._fetch_leetcode_today") as fetch,
        ):
            assert leetcode_solved_today(Config()) is True
        assert fetch.call_count == 0

    def test_the_endpoint_covers_an_unreadable_ledger(self) -> None:
        """This is the whole reason the second transport exists."""
        with (
            patch(f"{_PKG}.read_ledger_solved_today", return_value=None),
            patch(f"{_PKG}._fetch_leetcode_today", return_value=True),
        ):
            assert leetcode_solved_today(Config()) is True

    def test_both_failing_is_none(self) -> None:
        """Never False: the caller must be able to raise an incident."""
        with (
            patch(f"{_PKG}.read_ledger_solved_today", return_value=None),
            patch(f"{_PKG}._fetch_leetcode_today", side_effect=OSError("refused")),
            patch(f"{_PKG}.report_leetcode_incident") as incident,
        ):
            assert leetcode_solved_today(Config()) is None
        assert incident.call_count == 1

    def test_an_unusable_endpoint_answer_is_none(self) -> None:
        """A malformed payload is not a "no"."""
        with (
            patch(f"{_PKG}.read_ledger_solved_today", return_value=None),
            patch(f"{_PKG}._fetch_leetcode_today", side_effect=KeyError("leetcode")),
            patch(f"{_PKG}.report_leetcode_incident") as incident,
        ):
            assert leetcode_solved_today(Config()) is None
        assert incident.call_count == 1

    def test_a_successful_answer_is_cached(self) -> None:
        """The daemon ticks often; the ledger must not be re-read each time."""
        with patch(f"{_PKG}.read_ledger_solved_today", return_value=True) as read:
            leetcode_solved_today(Config())
            leetcode_solved_today(Config())
        assert read.call_count == 1

    def test_a_failure_is_not_cached(self) -> None:
        """A restarted service must take effect on the very next tick."""
        with (
            patch(f"{_PKG}.read_ledger_solved_today", return_value=None) as read,
            patch(f"{_PKG}._fetch_leetcode_today", side_effect=OSError("refused")),
            patch(f"{_PKG}.report_leetcode_incident"),
        ):
            leetcode_solved_today(Config())
            leetcode_solved_today(Config())
        assert read.call_count == 2


class TestFetchLeetcodeToday:
    """The HTTP read itself."""

    def test_an_unchecked_answer_is_an_error(self) -> None:
        """The server saying "I could not look" must not read as "no"."""
        payload = json.dumps(
            {"leetcode": {"checked": False, "solved_today": False, "reason": "dead"}}
        ).encode()
        with (
            patch(f"{_PKG}.http.client.HTTPConnection") as conn,
            pytest.raises(ValueError, match="could not check"),
        ):
            resp = conn.return_value.getresponse.return_value
            resp.status = 200
            resp.read.return_value = payload
            _leetcode_bonus._fetch_leetcode_today("http://127.0.0.1:8771/api/status")

    def test_a_non_200_is_an_error(self) -> None:
        """An error page is not a payload."""
        with (
            patch(f"{_PKG}.http.client.HTTPConnection") as conn,
            pytest.raises(ValueError, match="status 500"),
        ):
            resp = conn.return_value.getresponse.return_value
            resp.status = 500
            resp.reason = "Internal Server Error"
            resp.read.return_value = b""
            _leetcode_bonus._fetch_leetcode_today("http://127.0.0.1:8771/api/status")

    def test_a_good_answer_is_read(self) -> None:
        """The happy path returns the flag."""
        payload = json.dumps(
            {"leetcode": {"checked": True, "solved_today": True, "reason": "1"}}
        ).encode()
        with patch(f"{_PKG}.http.client.HTTPConnection") as conn:
            resp = conn.return_value.getresponse.return_value
            resp.status = 200
            resp.read.return_value = payload
            assert (
                _leetcode_bonus._fetch_leetcode_today(
                    "http://127.0.0.1:8771/api/status"
                )
                is True
            )
