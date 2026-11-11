"""Tests for _web_server module — 100% branch coverage."""

from __future__ import annotations

from contextlib import contextmanager
from http.client import HTTPConnection
import json
import threading
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._web_server import create_server, serve

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._web_server"
_VIEWS_PKG = "steam_backlog_enforcer._web_views"
_DATA_PKG = "steam_backlog_enforcer._web_games"
# build_web_dataset itself did not move.
_DATASET_PKG = "steam_backlog_enforcer._web_dataset"


@contextmanager
def _running() -> Iterator[int]:
    """Start the server on an ephemeral port in a thread; yield the port."""
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get(port: int, path: str) -> tuple[int, bytes, str]:
    """Make a GET request, returning (status, body, content-type)."""
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    finally:
        conn.close()


def _make_dist(
    tmp_path: Path,
    *,
    with_index: bool = True,
    files: dict[str, bytes] | None = None,
) -> Path:
    """Create a fake built-frontend directory."""
    dist = (tmp_path / "dist").resolve()
    dist.mkdir()
    if with_index:
        (dist / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    for name, content in (files or {}).items():
        (dist / name).write_bytes(content)
    return dist


class TestBudgetEndpoint:
    """Tests for the /api/budget route."""

    def test_budget_ok(self) -> None:
        """/api/budget returns the production snapshot as JSON."""
        with (
            patch(
                f"{_VIEWS_PKG}.build_budget_snapshot", return_value={"ok": True}
            ) as build,
            _running() as port,
        ):
            status, body, ctype = _get(port, "/api/budget")
        assert status == 200
        assert "application/json" in ctype
        assert json.loads(body) == {"ok": True}
        # Production by default, and nothing to do with the dataset projection.
        assert build.call_args.kwargs == {"demo": False}

    def test_demo_query_reads_the_demo_run(self) -> None:
        """?demo=1 builds the budget snapshot from the demo run."""
        with (
            patch(
                f"{_VIEWS_PKG}.build_budget_snapshot", return_value={"ok": True}
            ) as build,
            _running() as port,
        ):
            _get(port, "/api/budget?demo=1")
        assert build.call_args.kwargs == {"demo": True}

    def test_budget_error(self) -> None:
        """A failure building the snapshot returns 500 op_failed."""
        with (
            patch(f"{_VIEWS_PKG}.build_budget_snapshot", side_effect=OSError("boom")),
            _running() as port,
        ):
            status, body, _ = _get(port, "/api/budget")
        assert status == 500
        assert json.loads(body)["error"] == "op_failed"


class TestDatasetEndpoint:
    """Tests for the /api/dataset route."""

    def test_dataset_ok(self) -> None:
        """/api/dataset returns the games dataset as UTF-8 JSON."""
        with (
            patch(f"{_DATASET_PKG}.load_snapshot", return_value=None),
            patch(f"{_DATA_PKG}._read_raw_cache", return_value={}),
            patch(f"{_DATA_PKG}._load_cache", return_value={}),
            _running() as port,
        ):
            status, body, ctype = _get(port, "/api/dataset")
        assert status == 200
        assert "application/json" in ctype
        assert "charset=utf-8" in ctype
        assert "games" in json.loads(body)

    def test_dataset_error_returns_500(self) -> None:
        """A failure building the dataset returns 500 op_failed."""
        with (
            patch(f"{_VIEWS_PKG}.build_web_dataset", side_effect=OSError("boom")),
            _running() as port,
        ):
            status, body, _ = _get(port, "/api/dataset")
        assert status == 500
        assert json.loads(body)["error"] == "op_failed"


class TestStaticServing:
    """Tests for static-file serving, the 404 page and the traversal guard."""

    def test_serves_index(self, tmp_path: Path) -> None:
        """/ serves index.html as HTML."""
        dist = _make_dist(tmp_path)
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, body, ctype = _get(port, "/")
        assert status == 200
        assert b"INDEX" in body
        assert "text/html" in ctype

    def test_serves_js_with_charset(self, tmp_path: Path) -> None:
        """JavaScript is served with a UTF-8 charset."""
        dist = _make_dist(tmp_path, files={"app.js": b"console.log(1)"})
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, _, ctype = _get(port, "/app.js")
        assert status == 200
        assert "charset=utf-8" in ctype

    def test_serves_binary_without_charset(self, tmp_path: Path) -> None:
        """Binary files are served without a charset."""
        dist = _make_dist(tmp_path, files={"pic.png": b"\x89PNG\r\n"})
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, _, ctype = _get(port, "/pic.png")
        assert status == 200
        assert "image/png" in ctype
        assert "charset" not in ctype

    def test_unknown_route_gets_the_404_page(self, tmp_path: Path) -> None:
        """An unknown route gets the built 404 page."""
        dist = _make_dist(tmp_path, files={"404.html": b"<html>MISSING</html>"})
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, body, _ = _get(port, "/some/unknown/route")
        assert status == 404
        assert b"MISSING" in body

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """A traversal path gets the 404 page, never a file outside dist."""
        dist = _make_dist(tmp_path, files={"404.html": b"<html>MISSING</html>"})
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, body, _ = _get(port, "/../../../../../../etc/passwd")
        assert status == 404
        assert b"MISSING" in body  # got the 404 page, not the secret
        assert b"root:" not in body

    def test_not_built_returns_404(self, tmp_path: Path) -> None:
        """Without a built index the server answers 404 saying it is not built."""
        dist = _make_dist(tmp_path, with_index=False)
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, body, _ = _get(port, "/")
        assert status == 404
        assert b"not built" in body.lower()


class TestCreateServer:
    """Tests for create_server."""

    def test_binds_localhost(self) -> None:
        """create_server binds the requested localhost address."""
        server = create_server("127.0.0.1", 0)
        try:
            assert server.server_address[0] == "127.0.0.1"
        finally:
            server.server_close()


class TestServe:
    """Tests for the blocking serve() entry point."""

    def test_keyboard_interrupt_shuts_down(self) -> None:
        """Ctrl-C stops serve() and the server is still closed."""
        fake = MagicMock()
        fake.serve_forever.side_effect = KeyboardInterrupt
        with (
            patch(f"{_PKG}.create_server", return_value=fake),
            patch(f"{_PKG}._echo"),
        ):
            serve()
        fake.serve_forever.assert_called_once()
        fake.server_close.assert_called_once()

    def test_normal_return_closes_server(self) -> None:
        """A normal return from serve_forever closes the server."""
        fake = MagicMock()
        with (
            patch(f"{_PKG}.create_server", return_value=fake),
            patch(f"{_PKG}._echo"),
        ):
            serve()
        fake.server_close.assert_called_once()
