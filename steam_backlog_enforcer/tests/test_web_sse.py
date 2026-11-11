"""Tests for _web_sse — the job event stream."""

from __future__ import annotations

from http import HTTPStatus
import io
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _web_process, _web_sse
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer._web_sse import _frame, _is_terminal_state, _pump
from steam_backlog_enforcer.jobs._daemon_jobs import DaemonOutcome, record_daemon_job
from steam_backlog_enforcer.jobs._events import now_iso
from steam_backlog_enforcer.tests._web_request import make_request

if TYPE_CHECKING:
    from collections.abc import Buffer, Iterator
    from http.server import BaseHTTPRequestHandler

_PKG = "steam_backlog_enforcer._web_sse"
_RESULT = {"seq": 1, "type": "result"}
_DONE = {"seq": 2, "type": "state", "state": "succeeded"}


class _Handler:
    def __init__(self, wfile: io.BytesIO | None = None) -> None:
        self.wfile = wfile or io.BytesIO()
        self.headers_sent: list[tuple[str, str]] = []
        self.status: int | None = None
        self.close_connection = False

    def send_response(self, status: int) -> None:
        """Record the status line the stream sends."""
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        """Record a header the stream sends."""
        self.headers_sent.append((name, value))

    def end_headers(self) -> None:
        """Accept the end of headers; nothing is buffered."""
        return

    def as_handler(self) -> BaseHTTPRequestHandler:
        """Expose the fake under the handler type the code expects."""
        return cast("BaseHTTPRequestHandler", self)

    def written(self) -> str:
        """Return everything the stream wrote, decoded."""
        return self.wfile.getvalue().decode()


class _Clock:
    """A fake monotonic clock that ``sleep`` advances, then retires the server."""

    def __init__(self, step: float, sleeps_before_retire: int) -> None:
        self.now = 0.0
        self.step = step
        self.left = sleeps_before_retire

    def monotonic(self) -> float:
        """Return the fake current time."""
        return self.now

    def sleep(self, _seconds: float) -> None:
        """Advance the clock one step and retire the server once out of sleeps."""
        self.now += self.step
        self.left -= 1
        if self.left <= 0:
            _web_process.RETIRING.set()


@pytest.fixture(autouse=True)
def _not_retiring() -> Iterator[None]:
    _web_process.RETIRING.clear()
    yield
    _web_process.RETIRING.clear()


def _run_pump(clock: _Clock, events: list[list[dict[str, Any]]], state: str) -> str:
    """Run ``_pump`` over scripted event batches (then empty ones)."""
    handler = _Handler()
    batches = iter(events)
    with (
        patch(f"{_PKG}.time.monotonic", clock.monotonic),
        patch(f"{_PKG}.time.sleep", clock.sleep),
        patch(f"{_PKG}.read_job_events", side_effect=lambda *_: next(batches, [])),
        patch(f"{_PKG}.read_job", return_value={"state": state}),
    ):
        _pump(handler.as_handler(), "j", 0)
    return handler.written()


class TestResumeAfter:
    """The resume point comes from Last-Event-ID, then ?after, never negative."""

    @pytest.mark.parametrize(
        ("headers", "query", "expected"),
        [
            ({}, {}, 0),
            ({}, {"after": "7"}, 7),
            ({"Last-Event-ID": "9"}, {"after": "7"}, 9),
            ({}, {"after": "-3"}, 0),
        ],
    )
    def test_header_wins_over_query(
        self, headers: dict[str, str], query: dict[str, str], expected: int
    ) -> None:
        """A Last-Event-ID header beats ?after, and negatives clamp to zero."""
        request = make_request(headers=headers, query=query)
        assert _web_sse.resume_after(request) == expected

    def test_non_numeric(self) -> None:
        """A non-numeric ?after is refused as invalid_params."""
        with pytest.raises(ApiError) as err:
            _web_sse.resume_after(make_request(query={"after": "x"}))
        assert err.value.code == "invalid_params"


class TestFrames:
    """Each event becomes one SSE frame; only state events can end a stream."""

    def test_frame_layout(self) -> None:
        """A frame carries the seq as its id and the event as JSON data."""
        assert _frame({"seq": 4, "a": 1}) == (b'id: 4\ndata: {"seq": 4, "a": 1}\n\n')

    @pytest.mark.parametrize(
        ("event", "terminal"),
        [
            ({"type": "state", "state": "failed"}, True),
            ({"type": "state", "state": "running"}, False),
            ({"type": "result", "state": "failed"}, False),
        ],
    )
    def test_terminal_state(self, event: dict[str, str], *, terminal: bool) -> None:
        """Only a state event in a final state counts as terminal."""
        assert _is_terminal_state(event) is terminal


class TestPump:
    """The pump streams until the job ends, a grace lapses or the server retires."""

    def test_stops_at_once_when_retiring(self) -> None:
        """A retiring server writes nothing at all."""
        _web_process.RETIRING.set()
        assert _run_pump(_Clock(1, 99), [[_RESULT]], "running") == ""

    def test_ends_after_the_final_state(self) -> None:
        """Every event up to the final state is sent, then the pump ends."""
        out = _run_pump(
            _Clock(1, 99), [[{"seq": 0, "type": "log"}, _RESULT, _DONE]], "x"
        )
        assert out.count("data:") == 3
        assert out.endswith("\n\n")

    def test_ends_a_grace_after_a_result_without_a_state(self) -> None:
        """A result with no state event ends the stream once the grace period lapses."""
        clock = _Clock(3, 99)
        out = _run_pump(clock, [[_RESULT]], "running")
        assert out.count("data:") == 1
        assert clock.left == 98  # one sleep, then the grace lapsed

    def test_ends_for_a_finished_job_with_nothing_new(self) -> None:
        """A job already finished with no new events ends at once with no output."""
        assert _run_pump(_Clock(1, 99), [], "failed") == ""

    def test_keeps_alive_while_waiting(self) -> None:
        """Idle waiting writes a keep-alive comment so the browser keeps the stream."""
        out = _run_pump(_Clock(10, 3), [], "running")
        assert out == ": keep-alive\n\n"

    def test_keeps_waiting_inside_the_grace_period(self) -> None:
        """Inside the grace period after a result the pump keeps waiting."""
        clock = _Clock(1, 3)
        out = _run_pump(clock, [[_RESULT]], "running")
        assert out.count("data:") == 1
        assert _web_process.RETIRING.is_set()


class TestStream:
    """stream_job_events sends headers, replays the job log and closes."""

    def _job(self) -> str:
        done = DaemonOutcome(ok=True, summary="done", exit_code=0)
        return record_daemon_job("unblock", {}, created_at=now_iso(), outcome=done)

    def test_streams_a_finished_job_and_closes(self) -> None:
        """A finished job streams its result and final state, then closes."""
        job_id = self._job()
        handler = _Handler()
        _web_sse.stream_job_events(handler.as_handler(), make_request(job_id))
        assert handler.status == HTTPStatus.OK
        assert handler.close_connection is True
        assert ("Content-Type", "text/event-stream; charset=utf-8") in (
            handler.headers_sent
        )
        out = handler.written()
        assert out.startswith("retry: 2000\n\n")
        assert '"type": "result"' in out
        assert '"state": "succeeded"' in out

    def test_resumes_past_the_end(self) -> None:
        """Resuming past the last event sends only the retry hint."""
        job_id = self._job()
        handler = _Handler()
        request = make_request(job_id, query={"after": "999"})
        _web_sse.stream_job_events(handler.as_handler(), request)
        assert handler.written() == "retry: 2000\n\n"

    def test_unknown_job_sends_nothing(self) -> None:
        """An unknown job raises not_found before any response is started."""
        handler = _Handler()
        with pytest.raises(ApiError) as err:
            _web_sse.stream_job_events(handler.as_handler(), make_request("nope"))
        assert err.value.code == "not_found"
        assert handler.status is None

    def test_bad_after_is_refused_before_any_byte(self) -> None:
        """A bad ?after is refused before the response status is sent."""
        handler = _Handler()
        with pytest.raises(ApiError):
            _web_sse.stream_job_events(
                handler.as_handler(), make_request("j", query={"after": "x"})
            )
        assert handler.status is None

    @pytest.mark.parametrize("gone", [BrokenPipeError, ConnectionResetError])
    def test_a_vanished_browser_is_not_an_error(self, gone: type[OSError]) -> None:
        """A browser that disconnects mid-stream ends the stream without an error."""

        class _Dead(io.BytesIO):
            def write(self, _data: Buffer) -> int:
                raise gone

        handler = _Handler(_Dead())
        with patch(f"{_PKG}.read_job", return_value={"id": "j"}):
            _web_sse.stream_job_events(handler.as_handler(), make_request("j"))
        assert handler.status == HTTPStatus.OK
