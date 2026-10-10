"""Localhost HTTP server for the web UI: the control API and the React bundle.

A thin router. Per request it, in order: checks ``Host`` (every route — the
DNS-rebinding guard, :mod:`._web_auth`), fails closed on stale code
(:mod:`._serve_stale`), checks ``Origin`` and the per-launch token on
anything that is not a GET (and on the SSE stream), then hands off to a
route from :mod:`._web_routes`, the SSE streamer (:mod:`._web_sse`) or the
static bundle (``web/dist``, with the token injected into ``index.html``).

Binds to loopback only; never serves secrets and never sends CORS headers.
In development the Vite dev server proxies ``/api`` here; in production the
``serve`` command serves the built bundle and the API from one process.
"""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from steam_backlog_enforcer import _web_auth, _web_process
from steam_backlog_enforcer._serve_stale import outdated_source
from steam_backlog_enforcer._web_errors import ApiError, not_found
from steam_backlog_enforcer._web_io import (
    Request,
    read_json_body,
    send_bytes,
    send_error,
    send_reply,
)
from steam_backlog_enforcer._web_routes import EVENTS_PATH, resolve
from steam_backlog_enforcer._web_sse import stream_job_events
from steam_backlog_enforcer.game_install import _echo

logger = logging.getLogger(__name__)

# Built frontend lives at <repo>/web/dist (sibling of the package directory).
WEB_DIST = (Path(__file__).resolve().parent.parent / "web" / "dist").resolve()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
_INDEX = "index.html"
_NOT_BUILT_MSG = b"Frontend not built. Run: cd web && npm install && npm run build"
_STALE_MSG = (
    "This server is running outdated code and has stopped answering rather "
    "than report numbers the enforcer is not applying. It restarts on "
    "current code by itself under systemd; otherwise run ./run.sh serve"
)


class WebServer(ThreadingHTTPServer):
    """The HTTP server plus its per-launch token."""

    def __init__(self, address: tuple[str, int]) -> None:
        """Bind to *address* and mint this launch's token."""
        super().__init__(address, _Handler)
        self.token = _web_auth.new_token()

    @property
    def port(self) -> int:
        """The bound port (the real one, also when bound to port 0)."""
        return int(self.server_address[1])


class _Handler(BaseHTTPRequestHandler):
    """Route one request: auth, stale check, then API, SSE or static."""

    server: WebServer

    def log_message(self, fmt: str, /, *args: object) -> None:
        """Route the default request log to ``logging`` at debug level."""
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        """Handle a GET."""
        self._handle("GET")

    def do_POST(self) -> None:
        """Handle a POST."""
        self._handle("POST")

    def do_DELETE(self) -> None:
        """Handle a DELETE."""
        self._handle("DELETE")

    def _handle(self, method: str) -> None:
        """Run the checks, then dispatch; every refusal is a JSON error."""
        split = urlsplit(self.path)
        try:
            host = _web_auth.check_host(self.headers, self.server.port)
            if self._refused_as_stale(split.path):
                return
            if method != "GET":
                _web_auth.check_origin(self.headers, host)
                token = self.headers.get(_web_auth.AUTH_HEADER)
                _web_auth.check_token(token, self.server.token)
            self._dispatch(method, split.path, _query(split.query))
        except ApiError as exc:
            send_error(self, exc)
        except Exception:
            logger.exception("%s %s failed", method, split.path)
            msg = "The server failed to answer this request; see its log."
            send_error(
                self,
                ApiError(
                    msg, code="op_failed", status=HTTPStatus.INTERNAL_SERVER_ERROR
                ),
            )

    def _dispatch(self, method: str, path: str, query: dict[str, str]) -> None:
        """Send the request to the SSE stream, an API route or the bundle."""
        events = EVENTS_PATH.fullmatch(path) if method == "GET" else None
        if events is not None:
            # EventSource cannot send headers: the token rides in the query.
            _web_auth.check_token(query.get(_web_auth.AUTH_QUERY), self.server.token)
            request = Request(method, path, query, events.groups(), self.headers)
            stream_job_events(self, request)
            return
        if not path.startswith("/api/"):
            if method != "GET":
                raise _method_not_allowed()
            self._serve_static(path)
            return
        found = resolve(method, path)
        if found is None:
            msg = f"No such endpoint: {path}"
            raise not_found(msg)
        if isinstance(found, str):
            raise _method_not_allowed()
        route, args = found
        body = read_json_body(self) if method != "GET" else {}
        send_reply(self, route(Request(method, path, query, args, self.headers, body)))

    def _refused_as_stale(self, path: str) -> bool:
        """Fail closed when our own source changed since this process started.

        Every route refuses, static included: a page served from a fresh
        bundle that then fetches numbers from stale code is the same lie
        with extra steps. ``/api/server`` is the exception, because saying
        "I am stale" is the one answer that is still true. Either way the
        server then stands down so the supervisor restarts it on current
        code (``Restart=always``).
        """
        if outdated_source(_web_process.STARTED_AT) is None:
            return False
        if path == "/api/server":
            send_reply(self, _web_process.health_view(_no_request(path, self)))
        elif path.startswith("/api/"):
            send_error(self, ApiError(_STALE_MSG, code="server_stale"))
        else:
            body = _STALE_MSG.encode()
            send_bytes(
                self, HTTPStatus.SERVICE_UNAVAILABLE, body, "text/plain; charset=utf-8"
            )
        _web_process.retire()
        return True

    def _serve_static(self, path: str) -> None:
        """Serve a file from ``WEB_DIST`` with SPA fallback and traversal guard."""
        rel = path.lstrip("/") or _INDEX
        candidate = (WEB_DIST / rel).resolve()
        # Reject path traversal, then fall back to index.html for SPA routes.
        if not candidate.is_relative_to(WEB_DIST) or not candidate.is_file():
            candidate = WEB_DIST / _INDEX
        if not candidate.is_file():
            send_bytes(self, HTTPStatus.NOT_FOUND, _NOT_BUILT_MSG, "text/plain")
            return
        ctype, _ = mimetypes.guess_type(candidate.name)
        ctype = ctype or "text/plain"
        if ctype.startswith("text/") or ctype in _TEXT_TYPES:
            ctype = f"{ctype}; charset=utf-8"
        body = candidate.read_bytes()
        headers: dict[str, str] = {}
        if candidate.name == _INDEX and candidate.parent == WEB_DIST:
            # Carries this launch's token: never cache it.
            body = _web_auth.inject_token(body, self.server.token)
            headers["Cache-Control"] = "no-store"
        send_bytes(self, HTTPStatus.OK, body, ctype, headers)


# Content types that are text but not under the ``text/`` prefix.
_TEXT_TYPES = frozenset({"application/javascript", "application/json", "image/svg+xml"})


def _query(raw: str) -> dict[str, str]:
    """The query string, first value per key."""
    return {key: values[0] for key, values in parse_qs(raw).items()}


def _no_request(path: str, handler: _Handler) -> Request:
    """A bodiless GET request for *path* (for routes that ignore it)."""
    return Request("GET", path, {}, (), handler.headers)


def _method_not_allowed() -> ApiError:
    """The 405 for a known path under the wrong method."""
    msg = "Method not allowed here."
    return ApiError(msg, code="invalid_params", status=HTTPStatus.METHOD_NOT_ALLOWED)


def create_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> WebServer:
    """Create (but do not start) the threading HTTP server."""
    server = WebServer((host, port))
    _web_process.register(server)
    return server


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the web server until interrupted (or until it stands down)."""
    server = create_server(host, port)
    token_file = _web_auth.write_token_file(server.token, server.port)
    _echo(f"Steam Backlog Enforcer web UI: http://{host}:{port}")
    _echo(f"Session token written to {token_file}.")
    _echo("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _echo("\nShutting down.")
    finally:
        server.server_close()
