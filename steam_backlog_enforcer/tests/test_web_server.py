"""Tests for _web_server module — 100% branch coverage."""

from __future__ import annotations

from contextlib import contextmanager
from http.client import HTTPConnection
import json
import threading
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import main as main_mod
from steam_backlog_enforcer._web_server import create_server, serve
from steam_backlog_enforcer.config import Config, State

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._web_server"
_DATA_PKG = "steam_backlog_enforcer._web_dataset"


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


class TestDatasetEndpoint:
    """Tests for the /api/dataset route."""

    def test_dataset_ok(self) -> None:
        with (
            patch(f"{_DATA_PKG}.load_snapshot", return_value=None),
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
        with (
            patch(f"{_PKG}.build_web_dataset", side_effect=OSError("boom")),
            _running() as port,
        ):
            status, body, _ = _get(port, "/api/dataset")
        assert status == 500
        assert b"dataset error" in body


class TestStaticServing:
    """Tests for static-file serving + SPA fallback + traversal guard."""

    def test_serves_index(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path)
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, body, ctype = _get(port, "/")
        assert status == 200
        assert b"INDEX" in body
        assert "text/html" in ctype

    def test_serves_js_with_charset(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path, files={"app.js": b"console.log(1)"})
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, _, ctype = _get(port, "/app.js")
        assert status == 200
        assert "charset=utf-8" in ctype

    def test_serves_binary_without_charset(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path, files={"pic.png": b"\x89PNG\r\n"})
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, _, ctype = _get(port, "/pic.png")
        assert status == 200
        assert "image/png" in ctype
        assert "charset" not in ctype

    def test_spa_fallback_to_index(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path)
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, body, _ = _get(port, "/some/spa/route")
        assert status == 200
        assert b"INDEX" in body

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path)
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, body, _ = _get(port, "/../../../../../../etc/passwd")
        assert status == 200
        assert b"INDEX" in body  # fell back to index, did not serve the secret
        assert b"root:" not in body

    def test_not_built_returns_404(self, tmp_path: Path) -> None:
        dist = _make_dist(tmp_path, with_index=False)
        with patch(f"{_PKG}.WEB_DIST", dist), _running() as port:
            status, body, _ = _get(port, "/")
        assert status == 404
        assert b"not built" in body.lower()


class TestCreateServer:
    """Tests for create_server."""

    def test_binds_localhost(self) -> None:
        server = create_server("127.0.0.1", 0)
        try:
            assert server.server_address[0] == "127.0.0.1"
        finally:
            server.server_close()


class TestServe:
    """Tests for the blocking serve() entry point."""

    def test_keyboard_interrupt_shuts_down(self) -> None:
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
        fake = MagicMock()
        with (
            patch(f"{_PKG}.create_server", return_value=fake),
            patch(f"{_PKG}._echo"),
        ):
            serve()
        fake.server_close.assert_called_once()


class TestCmdServe:
    """Tests for the main.cmd_serve wiring."""

    def test_invokes_serve(self) -> None:
        with patch.object(main_mod, "serve") as mock_serve:
            main_mod.cmd_serve(Config(), State())
        mock_serve.assert_called_once()
