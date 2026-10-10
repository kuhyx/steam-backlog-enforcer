"""Tests for _web_server's router: auth order, stale refusal, dispatch, errors."""

from __future__ import annotations

from contextlib import contextmanager
from http.client import HTTPConnection
import json
import threading
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _web_process, _web_server
from steam_backlog_enforcer._web_io import Reply, Request, ok
from steam_backlog_enforcer.jobs._daemon_jobs import DaemonOutcome, record_daemon_job
from steam_backlog_enforcer.jobs._events import now_iso

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

_PKG = "steam_backlog_enforcer._web_server"


@pytest.fixture(autouse=True)
def _clean_process_state() -> Iterator[None]:
    """No retiring flag, and never "stale": other edits to the tree must not leak in."""
    _web_process.RETIRING.clear()
    with patch(f"{_PKG}.outdated_source", return_value=None):
        yield
    _web_process.RETIRING.clear()
    _web_process._server.clear()


@contextmanager
def _running() -> Iterator[_web_server.WebServer]:
    """Serve on an ephemeral loopback port in a thread."""
    server = _web_server.create_server("127.0.0.1", 0)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _auth(server: _web_server.WebServer) -> dict[str, str]:
    """The same-origin Origin header and the launch token."""
    return {
        "Origin": f"http://127.0.0.1:{server.port}",
        "X-SBE-Token": server.token,
    }


def _call(
    server: _web_server.WebServer,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: object = None,
) -> tuple[int, bytes, dict[str, str]]:
    """One request with *headers* (see :func:`_auth`) and a JSON *body*."""
    sent = dict(headers or {})
    payload = None
    if body is not None:
        payload = json.dumps(body)
        sent["Content-Type"] = "application/json"
    conn = HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.request(method, path, body=payload, headers=sent)
        resp = conn.getresponse()
        return resp.status, resp.read(), dict(resp.getheaders())
    finally:
        conn.close()


def _error_of(raw: bytes) -> str:
    return str(json.loads(raw)["error"])


class TestAuthOrder:
    def test_foreign_host_is_refused_even_for_static(self) -> None:
        with _running() as server:
            status, raw, _ = _call(server, "GET", "/", headers={"Host": "evil:1"})
        assert (status, _error_of(raw)) == (403, "bad_host")

    def test_a_post_needs_the_origin(self) -> None:
        with _running() as server:
            status, raw, _ = _call(server, "POST", "/api/jobs", body={})
        assert (status, _error_of(raw)) == (403, "bad_origin")

    def test_a_post_needs_the_token(self) -> None:
        with _running() as server:
            origin = {"Origin": f"http://127.0.0.1:{server.port}"}
            status, raw, _ = _call(server, "POST", "/api/jobs", headers=origin)
        assert (status, _error_of(raw)) == (403, "bad_token")

    def test_events_need_the_token_in_the_query(self) -> None:
        with _running() as server:
            status, raw, _ = _call(server, "GET", "/api/jobs/abc/events")
        assert (status, _error_of(raw)) == (403, "bad_token")


class TestStale:
    def _stale(self) -> AbstractContextManager[MagicMock]:
        return patch(f"{_PKG}.outdated_source", return_value="x.py")

    def test_api_routes_refuse_and_stand_down(self) -> None:
        with self._stale(), patch(f"{_PKG}._web_process.retire") as retire:
            with _running() as server:
                status, raw, _ = _call(server, "GET", "/api/budget")
            assert (status, _error_of(raw)) == (503, "server_stale")
        retire.assert_called_once_with()

    def test_static_routes_refuse_in_plain_text(self) -> None:
        with (
            self._stale(),
            patch(f"{_PKG}._web_process.retire"),
            _running() as server,
        ):
            status, raw, headers = _call(server, "GET", "/")
        assert status == 503
        assert raw.decode() == _web_server._STALE_MSG
        assert headers["Content-Type"].startswith("text/plain")

    def test_server_health_still_answers(self) -> None:
        with (
            self._stale(),
            patch(f"{_PKG}._web_process.retire") as retire,
            patch("steam_backlog_enforcer._web_process.version", return_value="v1"),
            _running() as server,
        ):
            status, raw, _ = _call(server, "GET", "/api/server")
        assert (status, json.loads(raw)["version"]) == (200, "v1")
        retire.assert_called_once_with()


class TestDispatch:
    def test_unknown_endpoint(self) -> None:
        with _running() as server:
            status, raw, _ = _call(server, "GET", "/api/nope")
        assert (status, _error_of(raw)) == (404, "not_found")

    def test_known_path_under_the_wrong_method(self) -> None:
        with _running() as server:
            status, _, _ = _call(server, "POST", "/api/budget", headers=_auth(server))
        assert status == 405

    def test_non_get_on_a_static_path(self) -> None:
        with _running() as server:
            status, _, _ = _call(server, "POST", "/index.html", headers=_auth(server))
        assert status == 405

    def test_post_body_reaches_the_route(self) -> None:
        seen: list[Request] = []

        def route(request: Request) -> Reply:
            seen.append(request)
            return ok({"got": request.body})

        with (
            patch(f"{_PKG}.resolve", return_value=(route, ("a",))),
            _running() as server,
        ):
            status, raw, _ = _call(
                server,
                "POST",
                "/api/jobs/a/x?q=1&q=2",
                body={"k": 1},
                headers=_auth(server),
            )
        assert (status, json.loads(raw)) == (200, {"got": {"k": 1}})
        assert (seen[0].args, seen[0].query, seen[0].method) == (
            ("a",),
            {"q": "1"},
            "POST",
        )

    def test_delete_is_routed(self) -> None:
        with (
            patch(f"{_PKG}.resolve", return_value=(lambda _r: ok(1), ())),
            _running() as server,
        ):
            status, _, _ = _call(
                server, "DELETE", "/api/pending/a", headers=_auth(server)
            )
        assert status == 200

    def test_a_crashing_route_is_a_500_without_details(self) -> None:
        def route(_request: Request) -> Reply:
            msg = "secret detail"
            raise RuntimeError(msg)

        with (
            patch(f"{_PKG}.resolve", return_value=(route, ())),
            _running() as server,
        ):
            status, raw, _ = _call(server, "GET", "/api/budget")
        assert (status, _error_of(raw)) == (500, "op_failed")
        assert b"secret" not in raw

    def test_real_route_through_the_table(self) -> None:
        with patch(f"{_PKG}.resolve", wraps=_web_server.resolve), _running() as server:
            status, raw, _ = _call(server, "GET", "/api/jobs")
        assert (status, json.loads(raw)) == (200, [])


class TestEvents:
    def test_streams_a_finished_job(self) -> None:
        done = DaemonOutcome(ok=True, summary="s", exit_code=0)
        job_id = record_daemon_job("unblock", {}, created_at=now_iso(), outcome=done)
        with _running() as server:
            path = f"/api/jobs/{job_id}/events?token={server.token}"
            status, raw, headers = _call(server, "GET", path)
        assert status == 200
        assert headers["Content-Type"].startswith("text/event-stream")
        assert b'"type": "result"' in raw
