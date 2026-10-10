"""Tests for _web_server's static bundle, token injection and ``serve``."""

from __future__ import annotations

from http.client import HTTPConnection
import threading
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _web_auth, _web_process, _web_server

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_STUB = "tok"
_PKG = "steam_backlog_enforcer._web_server"


@pytest.fixture(autouse=True)
def _clean_process_state() -> Iterator[None]:
    """No retiring flag, and never "stale": other edits to the tree must not leak in."""
    _web_process.RETIRING.clear()
    with patch(f"{_PKG}.outdated_source", return_value=None):
        yield
    _web_process.RETIRING.clear()
    _web_process._server.clear()


@pytest.fixture
def dist(tmp_path: Path) -> Iterator[Path]:
    """A fake built bundle, served instead of ``web/dist``."""
    root = (tmp_path / "dist").resolve()
    root.mkdir()
    (root / "index.html").write_text("<html><head></head>INDEX</html>", "utf-8")
    (root / "app.js").write_text("console.log(1)", "utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG")
    (root / "noext").write_text("plain", "utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "index.html").write_text("<html>SUB</html>", "utf-8")
    (tmp_path / "secret.txt").write_text("top secret", "utf-8")
    with patch(f"{_PKG}.WEB_DIST", root):
        yield root


def _get(path: str) -> tuple[int, bytes, str, str, str]:
    """GET *path* from a throw-away server; the token is the last element."""
    server = _web_server.create_server("127.0.0.1", 0)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    conn = HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return (
            resp.status,
            resp.read(),
            resp.headers.get("Content-Type", ""),
            resp.headers.get("Cache-Control", ""),
            server.token,
        )
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.usefixtures("dist")
class TestStatic:
    def test_index_carries_this_launchs_token_and_is_not_cached(self) -> None:
        status, body, ctype, cache, token = _get("/")
        assert status == 200
        assert f'content="{token}"'.encode() in body
        assert ctype == "text/html; charset=utf-8"
        assert cache == "no-store"

    def test_javascript_declares_its_charset(self) -> None:
        _, body, ctype, cache, _ = _get("/app.js")
        assert body == b"console.log(1)"
        assert ctype.endswith("; charset=utf-8")
        assert cache == ""

    def test_binary_has_no_charset(self) -> None:
        _, body, ctype, _, _ = _get("/logo.png")
        assert (body, ctype) == (b"\x89PNG", "image/png")

    def test_unknown_extension_is_plain_text(self) -> None:
        assert _get("/noext")[2] == "text/plain; charset=utf-8"

    def test_a_nested_index_is_served_without_a_token(self) -> None:
        _, body, _, cache, _ = _get("/sub/index.html")
        assert (body, cache) == (b"<html>SUB</html>", "")

    def test_spa_route_falls_back_to_index(self) -> None:
        status, body, _, _, _ = _get("/library/42")
        assert (status, b"INDEX" in body) == (200, True)

    def test_path_traversal_gets_the_index_not_the_file(self) -> None:
        status, body, _, _, _ = _get("/..%2Fsecret.txt")
        assert status == 200
        assert b"top secret" not in body

    def test_unbuilt_frontend_is_a_404(self, tmp_path: Path) -> None:
        with patch(f"{_PKG}.WEB_DIST", (tmp_path / "missing").resolve()):
            status, body, _, _, _ = _get("/")
        assert (status, body) == (404, _web_server._NOT_BUILT_MSG)


class TestServer:
    def test_port_is_the_bound_one(self) -> None:
        server = _web_server.create_server("127.0.0.1", 0)
        try:
            assert server.port > 0
            assert len(server.token) == 64
            assert _web_process._server == [server]
        finally:
            server.server_close()

    def test_query_keeps_the_first_value(self) -> None:
        assert _web_server._query("a=1&a=2&b=3") == {"a": "1", "b": "3"}


class TestServe:
    def _serve(self, serve_forever: object) -> MagicMock:
        server = MagicMock()
        server.token = _STUB
        server.port = 4321
        server.serve_forever = serve_forever
        with (
            patch(f"{_PKG}.create_server", return_value=server),
            patch(f"{_PKG}._echo") as echo,
        ):
            _web_server.serve("127.0.0.1", 4321)
        server.server_close.assert_called_once_with()
        return echo

    def test_writes_the_token_file_and_runs_until_it_returns(self) -> None:
        echo = self._serve(MagicMock())
        assert _web_auth.token_path(4321).read_text("ascii") == "tok\n"
        assert "Press Ctrl-C" in echo.call_args_list[2].args[0]

    def test_ctrl_c_shuts_down_cleanly(self) -> None:
        echo = self._serve(MagicMock(side_effect=KeyboardInterrupt))
        assert "Shutting down" in echo.call_args.args[0]
