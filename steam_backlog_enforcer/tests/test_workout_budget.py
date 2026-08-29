"""Tests for _workout_budget: the workout-to-gaming-budget coupling.

The property that matters most here is that every way of *not* getting an
answer yields the unearned floor. If any of them fell through to the earned
budget, the whole coupling could be defeated by stopping one user service, and
a silent 8h would be indistinguishable from an earned one.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _workout_budget
from steam_backlog_enforcer._workout_budget import (
    reset_cache,
    resolve_budget_seconds,
    workout_logged_today,
)
from steam_backlog_enforcer.config import Config

if TYPE_CHECKING:
    from collections.abc import Iterator

_PKG = "steam_backlog_enforcer._workout_budget"

_EARNED = 8 * 3600
_UNEARNED = 6 * 3600


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Keep the module memo from leaking answers between tests.

    Yields:
        None, with the cache empty before and after.
    """
    reset_cache()
    yield
    reset_cache()


def _config(**over: object) -> Config:
    """Build a config with the budget fields under test.

    Args:
        over: Field overrides.

    Returns:
        A Config instance; never loaded from or saved to disk.
    """
    config = Config()
    config.daily_gaming_seconds = _EARNED
    config.unearned_gaming_seconds = _UNEARNED
    config.workout_status_url = "http://127.0.0.1:8770/api/status"
    for key, value in over.items():
        setattr(config, key, value)
    return config


class TestWorkoutLoggedToday:
    """The locker's answer, or None when there was not one."""

    def test_true_when_a_workout_is_logged(self) -> None:
        """A truthy workout_today comes back as True."""
        with patch(f"{_PKG}._fetch_workout_today", return_value=True):
            assert workout_logged_today(_config()) is True

    def test_false_when_none_is_logged(self) -> None:
        """A falsy workout_today comes back as False, not None."""
        with patch(f"{_PKG}._fetch_workout_today", return_value=False):
            assert workout_logged_today(_config()) is False

    def test_unreachable_server_is_none_not_false(self) -> None:
        """ "Could not ask" must stay distinguishable from "asked, no"."""
        with patch(f"{_PKG}._fetch_workout_today", side_effect=OSError("refused")):
            assert workout_logged_today(_config()) is None

    def test_unreachable_server_says_why(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The warning names the URL and how to check the unit."""
        with (
            caplog.at_level(logging.WARNING),
            patch(f"{_PKG}._fetch_workout_today", side_effect=OSError("refused")),
        ):
            workout_logged_today(_config())
        assert "127.0.0.1:8770" in caplog.text
        assert "screen-locker-web" in caplog.text

    @pytest.mark.parametrize(
        "error",
        [ValueError("not json"), KeyError("gaming"), TypeError("bad shape")],
    )
    def test_an_unusable_answer_is_none(self, error: Exception) -> None:
        """Malformed JSON, a missing key or a wrong shape all fail closed."""
        with patch(f"{_PKG}._fetch_workout_today", side_effect=error):
            assert workout_logged_today(_config()) is None

    def test_a_successful_answer_is_cached(self) -> None:
        """The daemon ticks often; one HTTP call per tick would be silly."""
        with patch(f"{_PKG}._fetch_workout_today", return_value=True) as fetch:
            workout_logged_today(_config())
            workout_logged_today(_config())
        assert fetch.call_count == 1

    def test_a_failure_is_not_cached(self) -> None:
        """A restarted status server must take effect on the next tick."""
        with patch(f"{_PKG}._fetch_workout_today", side_effect=OSError("x")) as fetch:
            workout_logged_today(_config())
            workout_logged_today(_config())
        assert fetch.call_count == 2

    def test_the_cache_expires(self) -> None:
        """A workout logged later in the day still raises the budget."""
        with (
            patch(f"{_PKG}._fetch_workout_today", return_value=False) as fetch,
            patch(f"{_PKG}.time.monotonic", side_effect=[0.0, 999.0]),
        ):
            workout_logged_today(_config())
            workout_logged_today(_config())
        assert fetch.call_count == 2

    def test_different_urls_do_not_share_a_cache_entry(self) -> None:
        """Keyed by URL, so a test or a retarget cannot read a stale answer."""
        with patch(f"{_PKG}._fetch_workout_today", return_value=True) as fetch:
            workout_logged_today(_config())
            workout_logged_today(
                _config(workout_status_url="http://127.0.0.1:9999/api/status"),
            )
        assert fetch.call_count == 2


class TestResolveBudgetSeconds:
    """The number the enforcer actually bills against."""

    def test_a_workout_earns_the_full_budget(self) -> None:
        """8h once a counted workout is logged today."""
        with patch(f"{_PKG}._fetch_workout_today", return_value=True):
            assert resolve_budget_seconds(_config()) == float(_EARNED)

    def test_no_workout_gets_the_floor(self) -> None:
        """6h on a day with nothing logged."""
        with patch(f"{_PKG}._fetch_workout_today", return_value=False):
            assert resolve_budget_seconds(_config()) == float(_UNEARNED)

    def test_an_unreachable_locker_gets_the_floor(self) -> None:
        """Fail closed: a dead locker costs gaming time, never grants it."""
        with patch(f"{_PKG}._fetch_workout_today", side_effect=OSError("refused")):
            assert resolve_budget_seconds(_config()) == float(_UNEARNED)

    def test_the_cut_is_explained(self, caplog: pytest.LogCaptureFixture) -> None:
        """A 2h swing should never be silent."""
        with (
            caplog.at_level(logging.INFO),
            patch(f"{_PKG}._fetch_workout_today", return_value=False),
        ):
            resolve_budget_seconds(_config())
        assert "6.0h" in caplog.text
        assert "8.0h" in caplog.text

    def test_a_floor_above_the_ceiling_is_refused(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Misconfigured, skipping would otherwise buy MORE time than working out."""
        config = _config(unearned_gaming_seconds=10 * 3600)
        with (
            caplog.at_level(logging.ERROR),
            patch(f"{_PKG}._fetch_workout_today", return_value=False),
        ):
            assert resolve_budget_seconds(config) == float(_EARNED)
        assert "exceeds daily_gaming_seconds" in caplog.text


class TestFetchWorkoutToday:
    """The HTTP read itself, over a real loopback server."""

    def test_reads_the_flag(self, http_stub: str) -> None:
        """A well-formed payload yields the boolean."""
        assert _workout_budget._fetch_workout_today(http_stub) is True

    def test_a_non_200_is_an_error(self, http_stub_500: str) -> None:
        """An error status must not be parsed as "no workout"."""
        with pytest.raises(ValueError, match="status 500"):
            _workout_budget._fetch_workout_today(http_stub_500)


@pytest.fixture
def http_stub() -> Iterator[str]:
    """Serve a status payload saying a workout was logged today.

    Yields:
        The URL of the stub endpoint.
    """
    yield from _serve(200, json.dumps({"gaming": {"workout_today": True}}).encode())


@pytest.fixture
def http_stub_500() -> Iterator[str]:
    """Serve a 500, as a broken payload builder would.

    Yields:
        The URL of the stub endpoint.
    """
    yield from _serve(500, b"status error")


def _serve(status: int, body: bytes) -> Iterator[str]:
    """Run a one-route HTTP server on an ephemeral loopback port.

    Args:
        status: Status code to return.
        body: Body to return.

    Yields:
        The URL of the endpoint.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            """Stay quiet in test output."""

        def do_GET(self) -> None:
            """Serve the canned response."""
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/api/status"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
