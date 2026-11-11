"""Tests for _web_server's static bundle, token injection and ``serve``."""

from __future__ import annotations

from http.client import HTTPConnection
import threading
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _web_auth, _web_server
from steam_backlog_enforcer._web_process import _server
from steam_backlog_enforcer._web_server import _NOT_BUILT_MSG, _query
from steam_backlog_enforcer.tests._web_process_state import clean_process_state

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_STUB = "tok"
_PKG = "steam_backlog_enforcer._web_server"


@pytest.fixture(autouse=True)
def _clean_process_state() -> Iterator[None]:
    """No retiring flag, and never "stale": other edits to the tree must not leak in."""
    yield from clean_process_state()


@pytest.fixture(name="dist")
def fixture_dist(tmp_path: Path) -> Iterator[Path]:
    """A fake built bundle, served instead of ``web/dist``."""
    root = (tmp_path / "dist").resolve()
    root.mkdir()
    (root / "index.html").write_text("<html><head></head>INDEX</html>", "utf-8")
    (root / "app.js").write_text("console.log(1)", "utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG")
    (root / "noext").write_text("plain", "utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "index.html").write_text("<html><head></head>SUB</html>", "utf-8")
    (sub / "page.html").write_text("<html>PAGE</html>", "utf-8")
    (root / "404.html").write_text("<html><head></head>MISSING</html>", "utf-8")
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
    """Static files: content types, caching, token injection and 404s."""

    def test_index_carries_this_launchs_token_and_is_not_cached(self) -> None:
        """The index carries this launch's token and is never cached."""
        status, body, ctype, cache, token = _get("/")
        assert status == 200
        assert f'content="{token}"'.encode() in body
        assert ctype == "text/html; charset=utf-8"
        assert cache == "no-store"

    def test_javascript_declares_its_charset(self) -> None:
        """JavaScript is served with a utf-8 charset and may be cached."""
        _, body, ctype, cache, _ = _get("/app.js")
        assert body == b"console.log(1)"
        assert ctype.endswith("; charset=utf-8")
        assert cache == ""

    def test_binary_has_no_charset(self) -> None:
        """A PNG is served as image/png without a charset."""
        _, body, ctype, _, _ = _get("/logo.png")
        assert (body, ctype) == (b"\x89PNG", "image/png")

    def test_unknown_extension_is_plain_text(self) -> None:
        """A file without a known extension is plain text."""
        assert _get("/noext")[2] == "text/plain; charset=utf-8"

    @pytest.mark.parametrize("path", ["/sub", "/sub/", "/sub/index.html", "/sub/?id=7"])
    def test_a_directory_serves_its_own_index_with_a_token(self, path: str) -> None:
        """Every spelling of a directory serves its index with a token."""
        status, body, ctype, cache, token = _get(path)
        assert (status, b"SUB" in body) == (200, True)
        assert f'content="{token}"'.encode() in body
        assert (ctype, cache) == ("text/html; charset=utf-8", "no-store")

    def test_every_html_file_carries_the_token_and_is_not_cached(self) -> None:
        """Any HTML file gets the token and no-store."""
        status, body, _, cache, token = _get("/sub/page.html")
        assert (status, cache) == (200, "no-store")
        assert f'content="{token}"'.encode() in body

    def test_unknown_route_is_the_404_page_with_a_token(self) -> None:
        """An unknown route serves the 404 page with a token."""
        status, body, _, cache, token = _get("/library/42")
        assert (status, b"MISSING" in body, cache) == (404, True, "no-store")
        assert f'content="{token}"'.encode() in body

    def test_path_traversal_gets_the_404_page_not_the_file(self) -> None:
        """An encoded ../ never reaches a file outside the bundle."""
        status, body, _, _, _ = _get("/..%2Fsecret.txt")
        assert (status, b"MISSING" in body) == (404, True)
        assert b"top secret" not in body

    def test_unknown_route_without_a_404_page_is_not_built(self, dist: Path) -> None:
        """Without a 404 page an unknown route gets the not-built message."""
        (dist / "404.html").unlink()
        status, body, _, _, _ = _get("/nope")
        assert (status, body) == (404, _NOT_BUILT_MSG)

    def test_not_built_message_names_pnpm(self) -> None:
        """The not-built message tells how to build the frontend."""
        assert b"pnpm install && pnpm build" in _NOT_BUILT_MSG

    def test_unbuilt_frontend_is_a_404(self, tmp_path: Path) -> None:
        """A missing bundle answers 404 with the not-built message."""
        with patch(f"{_PKG}.WEB_DIST", (tmp_path / "missing").resolve()):
            status, body, _, _, _ = _get("/")
        assert (status, body) == (404, _NOT_BUILT_MSG)


class TestServer:
    """create_server binds, mints a token and registers itself."""

    def test_port_is_the_bound_one(self) -> None:
        """The server reports its bound port and a 64-char token, and is registered."""
        server = _web_server.create_server("127.0.0.1", 0)
        try:
            assert server.port > 0
            assert len(server.token) == 64
            assert _server == [server]
        finally:
            server.server_close()

    def test_query_keeps_the_first_value(self) -> None:
        """Repeated query keys keep their first value."""
        assert _query("a=1&a=2&b=3") == {"a": "1", "b": "3"}


class TestServe:
    """serve writes the token file and always closes the server."""

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
        """The token file is written and the user told how to stop."""
        echo = self._serve(MagicMock())
        assert _web_auth.token_path(4321).read_text("ascii") == "tok\n"
        assert "Press Ctrl-C" in echo.call_args_list[2].args[0]

    def test_ctrl_c_shuts_down_cleanly(self) -> None:
        """Ctrl-C ends serve with a shutdown message."""
        echo = self._serve(MagicMock(side_effect=KeyboardInterrupt))
        assert "Shutting down" in echo.call_args.args[0]
