"""Name -> AppID search, across both backends.

The community endpoint is primary because the storefront one TLS-rejects
scripted clients from this network; these tests pin the fallback order, the
retry, and the exact-title rule that stops "Portal" installing Portal 2.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Never
import urllib.error

import pytest

from steam_installer import _http, resolve

if TYPE_CHECKING:
    from collections.abc import Callable
    from urllib.request import Request

COMMUNITY_PAYLOAD = [{"appid": "1771300", "name": "Kingdom Come: Deliverance II"}]
STORE_PAYLOAD = {"items": [{"id": 1771300, "name": "Kingdom Come: Deliverance II"}]}


class _FakeResponse(io.BytesIO):
    """A urlopen response: BytesIO already works as a context manager."""


def _responder(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[str], io.BytesIO]
) -> list[str]:
    """Route a fake urlopen by URL so each backend can be driven separately."""
    seen = []

    def fake_urlopen(request: Request, **_kw: float) -> io.BytesIO:
        seen.append(request.full_url)
        return handler(request.full_url)

    monkeypatch.setattr(_http.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(resolve.time, "sleep", lambda _: None)
    return seen


def test_community_backend_is_tried_first_and_parses_string_appids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The community endpoint returns appid as a string, unlike the store one."""
    seen = _responder(
        monkeypatch, lambda url: _FakeResponse(json.dumps(COMMUNITY_PAYLOAD).encode())
    )

    results = resolve.search("kingdom come")

    assert results == [
        resolve.SearchResult(appid=1771300, name="Kingdom Come: Deliverance II")
    ]
    assert "steamcommunity.com" in seen[0]
    assert len(seen) == 1


def test_store_backend_is_used_when_the_community_one_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Store backend is used when the community one fails."""

    def handler(url: str) -> _FakeResponse:
        if "steamcommunity.com" in url:
            msg = "dns"
            raise urllib.error.URLError(msg)
        return _FakeResponse(json.dumps(STORE_PAYLOAD).encode())

    seen = _responder(monkeypatch, handler)

    assert resolve.search("kingdom come")[0].appid == 1771300
    assert "store.steampowered.com" in seen[-1]


def test_a_transient_failure_is_retried_rather_than_given_up_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS here fails intermittently; one blip must not send the user off to
    look up an AppID by hand."""
    attempts = []

    def handler(url: str) -> _FakeResponse:
        attempts.append(url)
        if len(attempts) == 1:
            msg = "temporary failure in name resolution"
            raise urllib.error.URLError(msg)
        return _FakeResponse(json.dumps(COMMUNITY_PAYLOAD).encode())

    _responder(monkeypatch, handler)

    assert resolve.search("kingdom come")[0].appid == 1771300
    assert len(attempts) == 2


def test_search_quotes_the_term(monkeypatch: pytest.MonkeyPatch) -> None:
    """Search quotes the term."""
    seen = _responder(monkeypatch, lambda url: _FakeResponse(b"[]"))

    resolve.search("kingdom come/2")

    assert "kingdom%20come/2" in seen[0] or "kingdom%20come%2F2" in seen[0]


def test_search_sends_an_explicit_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """urllib's default UA gets refused outright by Steam's edge."""
    captured = {}

    def fake_urlopen(request: Request, **_kw: float) -> io.BytesIO:
        captured["ua"] = request.get_header("User-agent")
        return _FakeResponse(b"[]")

    monkeypatch.setattr(_http.urllib.request, "urlopen", fake_urlopen)

    resolve.search("anything")

    assert captured["ua"] == resolve.USER_AGENT


def test_rows_with_a_non_numeric_appid_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows with a non numeric appid are skipped."""
    payload = [{"appid": "nope", "name": "Broken"}, *COMMUNITY_PAYLOAD]
    _responder(monkeypatch, lambda url: _FakeResponse(json.dumps(payload).encode()))

    assert [r.appid for r in resolve.search("x")] == [1771300]


def test_store_missing_items_key_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Store missing items key returns empty."""

    def handler(url: str) -> _FakeResponse:
        if "steamcommunity.com" in url:
            msg = "dns"
            raise urllib.error.URLError(msg)
        return _FakeResponse(b"{}")

    _responder(monkeypatch, handler)
    assert resolve.search("nothing") == []


def test_an_html_error_page_is_a_search_failure_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A captive portal or block page returns HTML with a 200; that must not
    surface as a JSONDecodeError traceback."""
    _responder(monkeypatch, lambda url: _FakeResponse(b"<html>nope</html>"))

    with pytest.raises(resolve.SearchUnavailableError):
        resolve.search("kingdom come")


def test_a_dict_payload_falls_through_to_the_store_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The community endpoint returns a list. A dict is the store's shape, so
    it is not a crash -- the store parser handles it and finds no items."""
    _responder(monkeypatch, lambda url: _FakeResponse(b'{"not": "a list"}'))

    assert resolve.search("kingdom come") == []


def test_a_payload_neither_backend_understands_is_a_search_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A payload neither backend understands is a search failure."""
    _responder(monkeypatch, lambda url: _FakeResponse(b'"just a string"'))

    with pytest.raises(resolve.SearchUnavailableError):
        resolve.search("kingdom come")


@pytest.mark.parametrize(
    "exc", [urllib.error.URLError("tls blocked"), TimeoutError("timed out")]
)
def test_search_network_failure_becomes_search_unavailable(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    """Neither endpoint reachable is not a code bug, so it gets its own type."""

    def boom(url: str) -> Never:
        raise exc

    _responder(monkeypatch, boom)

    with pytest.raises(resolve.SearchUnavailableError, match="steamcommunity"):
        resolve.search("kingdom come")


def test_exact_match_beats_steams_own_ranking() -> None:
    """Steam ranks Portal 2 above Portal; typing the full name must still win."""
    results = [
        resolve.SearchResult(620, "Portal 2"),
        resolve.SearchResult(400, "Portal"),
    ]
    assert resolve.exact_match(results, "portal").appid == 400
    assert resolve.exact_match(results, "  PORTAL  ").appid == 400


def test_exact_match_returns_none_without_one() -> None:
    """Exact match returns none without one."""
    results = [resolve.SearchResult(620, "Portal 2")]
    assert resolve.exact_match(results, "Portal") is None


def test_exact_match_refuses_to_pick_between_duplicate_titles() -> None:
    """Two apps with the same title is a genuine ambiguity, not a coin flip."""
    results = [resolve.SearchResult(1, "Same"), resolve.SearchResult(2, "Same")]
    assert resolve.exact_match(results, "Same") is None
