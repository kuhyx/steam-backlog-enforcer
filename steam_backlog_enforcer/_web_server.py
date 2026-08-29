"""Minimal read-only localhost HTTP server for the interactive web UI.

Serves the projected dataset at ``GET /api/dataset`` and the built React
bundle (``web/dist``) as static files.  Binds to localhost only and never
exposes secrets: the payload comes from :func:`build_web_dataset`, which reads
the data caches but never ``config.json``.

In development the Vite dev server proxies ``/api`` here; in production the
``serve`` command serves the built bundle and the API from one process.
"""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

from steam_backlog_enforcer._budget_view import build_budget_snapshot
from steam_backlog_enforcer._web_dataset import build_web_dataset, dataset_to_payload
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.game_install import _echo

logger = logging.getLogger(__name__)

# Built frontend lives at <repo>/web/dist (sibling of the package directory).
WEB_DIST = (Path(__file__).resolve().parent.parent / "web" / "dist").resolve()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
_API_DATASET = "/api/dataset"
_API_BUDGET = "/api/budget"

# Content types that are text but not under the ``text/`` prefix.
_EXTRA_TEXT_TYPES = frozenset(
    {"application/javascript", "application/json", "image/svg+xml"}
)
_NOT_BUILT_MSG = b"Frontend not built. Run: cd web && npm install && npm run build"


class _Handler(BaseHTTPRequestHandler):
    """Serve the dataset JSON and the static frontend bundle (read-only)."""

    def log_message(self, fmt: str, *args: object) -> None:
        """Route the default request log to ``logging`` at debug level."""
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        """Dispatch a GET to one of the APIs or to a static file."""
        split = urlsplit(self.path)
        if split.path == _API_DATASET:
            self._serve_dataset()
        elif split.path == _API_BUDGET:
            # ``?demo=1`` reads the demo run's state and log, which is how the
            # 60-second demo can be watched hitting its cutoff in the browser
            # without spending a real day's budget to see it.
            self._serve_budget(demo="demo=1" in split.query)
        else:
            self._serve_static(split.path)

    def _serve_budget(self, *, demo: bool) -> None:
        """Build and send the gaming-budget snapshot as JSON."""
        try:
            body = json.dumps(build_budget_snapshot(demo=demo)).encode("utf-8")
        except (OSError, ValueError, KeyError):
            logger.exception("Failed to build budget snapshot")
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, b"budget error", "text/plain")
            return
        self._send(HTTPStatus.OK, body, "application/json")

    def _serve_dataset(self) -> None:
        """Build and send the projected dataset as JSON."""
        try:
            payload = dataset_to_payload(build_web_dataset(State.load()))
            body = json.dumps(payload).encode("utf-8")
        except (OSError, ValueError, KeyError):
            logger.exception("Failed to build web dataset")
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, b"dataset error", "text/plain")
            return
        self._send(HTTPStatus.OK, body, "application/json")

    def _serve_static(self, path: str) -> None:
        """Serve a file from ``WEB_DIST`` with SPA fallback and traversal guard."""
        rel = path.lstrip("/") or "index.html"
        candidate = (WEB_DIST / rel).resolve()
        # Reject path traversal, then fall back to index.html for SPA routes.
        if not candidate.is_relative_to(WEB_DIST) or not candidate.is_file():
            candidate = WEB_DIST / "index.html"
        if not candidate.is_file():
            self._send(HTTPStatus.NOT_FOUND, _NOT_BUILT_MSG, "text/plain")
            return
        ctype, _ = mimetypes.guess_type(candidate.name)
        self._send(HTTPStatus.OK, candidate.read_bytes(), ctype or "text/plain")

    def _send(self, status: HTTPStatus, body: bytes, ctype: str) -> None:
        """Write a complete response with the given status, body, and type."""
        if ctype.startswith("text/") or ctype in _EXTRA_TEXT_TYPES:
            ctype = f"{ctype}; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(
    host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> ThreadingHTTPServer:
    """Create (but do not start) the threading HTTP server."""
    return ThreadingHTTPServer((host, port), _Handler)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the web server until interrupted with Ctrl-C."""
    server = create_server(host, port)
    _echo(f"Steam Backlog Enforcer web UI: http://{host}:{port}")
    _echo("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _echo("\nShutting down.")
    finally:
        server.server_close()
