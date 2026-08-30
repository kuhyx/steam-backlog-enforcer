"""Tests for _workout_budget: reading the "did I work out today" fact.

The property that matters most here is that every way of *not* getting an
answer yields ``None``, never ``False``-that-looks-like-an-answer. The budget
arithmetic that consumes it lives in test_budget_resolve.py.
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
    workout_logged_today,
)
from steam_backlog_enforcer.config import Config

if TYPE_CHECKING:
    from collections.abc import Iterator

_PKG = "steam_backlog_enforcer._workout_budget"


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
