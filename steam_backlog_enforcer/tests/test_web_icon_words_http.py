"""The icon-word endpoints over real HTTP: auth rules and the served page."""

from __future__ import annotations

from http.client import HTTPConnection
import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _icon_ledger, _web_icon_words, _web_server
from steam_backlog_enforcer.tests._icon_registry import REGISTRY
from steam_backlog_enforcer.tests._web_process_state import (
    clean_process_state,
    running_server,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clean_process_state() -> Iterator[None]:
    """Never "stale": other edits to the tree must not leak in."""
    yield from clean_process_state()


@pytest.fixture(name="server")
def fixture_server(tmp_path: Path) -> Iterator[_web_server.WebServer]:
    """A live server on an ephemeral port with a one-page bundle."""
    dist = (tmp_path / "dist").resolve()
    dist.mkdir()
    (dist / "index.html").write_text("<html><head></head>X</html>", "utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(REGISTRY), "utf-8")
    with (
        patch.object(_web_server, "WEB_DIST", dist),
        patch.object(_web_icon_words, "REGISTRY_FILE", registry),
        running_server() as server,
    ):
        yield server


def _call(
    server: _web_server.WebServer,
    method: str,
    path: str,
    body: object = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object] | str]:
    host = f"127.0.0.1:{server.port}"
    sent = {"Host": host, **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        sent["Content-Type"] = "application/json"
    conn = HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.request(method, path, body=data, headers=sent)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        ctype = resp.headers.get("Content-Type", "")
        return resp.status, json.loads(raw) if "json" in ctype else raw
    finally:
        conn.close()


def _authed(server: _web_server.WebServer) -> dict[str, str]:
    return {"Origin": f"http://127.0.0.1:{server.port}", "X-SBE-Token": server.token}


class TestAuth:
    """Writes follow the server's Host, Origin and token rules."""

    @pytest.mark.parametrize(
        ("headers", "code"),
        [
            ({}, "bad_origin"),
            ({"Origin": "http://evil.example"}, "bad_origin"),
            ({"Origin": "ORIGIN"}, "bad_token"),
        ],
    )
    def test_post_without_origin_or_token_is_refused(
        self, server: _web_server.WebServer, headers: dict[str, str], code: str
    ) -> None:
        """No Origin, a foreign one, or no token: 403 and nothing written."""
        sent = {
            k: v.replace("ORIGIN", f"http://127.0.0.1:{server.port}")
            for k, v in headers.items()
        }
        status, body = _call(
            server, "POST", "/api/icon-words/cmd.done", {"word": "x"}, sent
        )
        assert status == 403
        assert isinstance(body, dict)
        assert body["error"] == code
        assert not _icon_ledger.ledger_path().exists()

    def test_foreign_host_is_refused_even_for_get(
        self, server: _web_server.WebServer
    ) -> None:
        """The DNS-rebinding guard covers the ledger too."""
        status, _ = _call(
            server, "GET", "/api/icon-words", headers={"Host": "evil.example"}
        )
        assert status == 403

    @pytest.mark.parametrize("method", ["POST", "PUT"])
    def test_authed_write_saves_and_get_reads_it(
        self, server: _web_server.WebServer, method: str
    ) -> None:
        """With Origin and token a write lands; a token-less GET reads it."""
        status, body = _call(
            server,
            method,
            "/api/icon-words/cmd.done",
            {"word": "My win"},
            _authed(server),
        )
        assert status == 200
        assert isinstance(body, dict)
        assert body["icons"] == {"cmd.done": {"word": "My win", "glyph": None}}
        status, body = _call(server, "GET", "/api/icon-words")
        assert (status, body) == (
            200,
            {"version": 1, "icons": {"cmd.done": {"word": "My win", "glyph": None}}},
        )

    def test_bad_word_is_a_400(self, server: _web_server.WebServer) -> None:
        """Validation errors are invalid_params over HTTP too."""
        status, body = _call(
            server,
            "POST",
            "/api/icon-words/cmd.done",
            {"word": "x" * 41},
            _authed(server),
        )
        assert status == 400
        assert isinstance(body, dict)
        assert body["error"] == "invalid_params"


class TestServedPage:
    """Every served page carries the current ledger: no rebuild needed."""

    def test_a_pick_shows_on_the_next_page_load(
        self, server: _web_server.WebServer
    ) -> None:
        """Save a word, reload the page: the injected ledger has it."""
        _call(
            server, "POST", "/api/icon-words/cmd.done", {"word": "Yay"}, _authed(server)
        )
        status, html = _call(server, "GET", "/")
        assert status == 200
        assert isinstance(html, str)
        marker = f'<script type="application/json" id="{_web_icon_words.SCRIPT_ID}">'
        payload = html.split(marker, 1)[1].split("</script>", 1)[0]
        assert json.loads(payload)["icons"]["cmd.done"]["word"] == "Yay"
        assert f'content="{server.token}"' in html
