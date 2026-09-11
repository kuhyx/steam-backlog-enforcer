"""Name -> AppID search, across both backends.

The community endpoint is primary because the storefront one TLS-rejects
scripted clients from this network; these tests pin the fallback order, the
retry, and the exact-title rule that stops "Portal" installing Portal 2.
"""

import io
import json
import urllib.error

import pytest

from steam_installer import resolve

COMMUNITY_PAYLOAD = [{"appid": "1771300", "name": "Kingdom Come: Deliverance II"}]
STORE_PAYLOAD = {"items": [{"id": 1771300, "name": "Kingdom Come: Deliverance II"}]}


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _responder(monkeypatch, handler):
    """Route a fake urlopen by URL so each backend can be driven separately."""
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(request.full_url)
        return handler(request.full_url)

    monkeypatch.setattr(resolve.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(resolve.time, "sleep", lambda _: None)
    return seen


def test_community_backend_is_tried_first_and_parses_string_appids(monkeypatch):
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


def test_store_backend_is_used_when_the_community_one_fails(monkeypatch):
    def handler(url):
        if "steamcommunity.com" in url:
            raise urllib.error.URLError("dns")
        return _FakeResponse(json.dumps(STORE_PAYLOAD).encode())

    seen = _responder(monkeypatch, handler)

    assert resolve.search("kingdom come")[0].appid == 1771300
    assert "store.steampowered.com" in seen[-1]


def test_a_transient_failure_is_retried_rather_than_given_up_on(monkeypatch):
    """DNS here fails intermittently; one blip must not send the user off to
    look up an AppID by hand."""
    attempts = []

    def handler(url):
        attempts.append(url)
        if len(attempts) == 1:
            raise urllib.error.URLError("temporary failure in name resolution")
        return _FakeResponse(json.dumps(COMMUNITY_PAYLOAD).encode())

    _responder(monkeypatch, handler)

    assert resolve.search("kingdom come")[0].appid == 1771300
    assert len(attempts) == 2


def test_search_quotes_the_term(monkeypatch):
    seen = _responder(monkeypatch, lambda url: _FakeResponse(b"[]"))

    resolve.search("kingdom come/2")

    assert "kingdom%20come/2" in seen[0] or "kingdom%20come%2F2" in seen[0]


def test_search_sends_an_explicit_user_agent(monkeypatch):
    """urllib's default UA gets refused outright by Steam's edge."""
    captured = {}

    def fake_urlopen(request, timeout):
        captured["ua"] = request.get_header("User-agent")
        return _FakeResponse(b"[]")

    monkeypatch.setattr(resolve.urllib.request, "urlopen", fake_urlopen)

    resolve.search("anything")

    assert captured["ua"] == resolve.USER_AGENT


def test_rows_with_a_non_numeric_appid_are_skipped(monkeypatch):
    payload = [{"appid": "nope", "name": "Broken"}, *COMMUNITY_PAYLOAD]
    _responder(monkeypatch, lambda url: _FakeResponse(json.dumps(payload).encode()))

    assert [r.appid for r in resolve.search("x")] == [1771300]


def test_store_missing_items_key_returns_empty(monkeypatch):
    def handler(url):
        if "steamcommunity.com" in url:
            raise urllib.error.URLError("dns")
        return _FakeResponse(b"{}")

    _responder(monkeypatch, handler)
    assert resolve.search("nothing") == []


def test_an_html_error_page_is_a_search_failure_not_a_crash(monkeypatch):
    """A captive portal or block page returns HTML with a 200; that must not
    surface as a JSONDecodeError traceback."""
    _responder(monkeypatch, lambda url: _FakeResponse(b"<html>nope</html>"))

    with pytest.raises(resolve.SearchUnavailable):
        resolve.search("kingdom come")


def test_a_dict_payload_falls_through_to_the_store_parser(monkeypatch):
    """The community endpoint returns a list. A dict is the store's shape, so
    it is not a crash -- the store parser handles it and finds no items."""
    _responder(monkeypatch, lambda url: _FakeResponse(b'{"not": "a list"}'))

    assert resolve.search("kingdom come") == []


def test_a_payload_neither_backend_understands_is_a_search_failure(monkeypatch):
    _responder(monkeypatch, lambda url: _FakeResponse(b'"just a string"'))

    with pytest.raises(resolve.SearchUnavailable):
        resolve.search("kingdom come")


@pytest.mark.parametrize(
    "exc", [urllib.error.URLError("tls blocked"), TimeoutError("timed out")]
)
def test_search_network_failure_becomes_search_unavailable(monkeypatch, exc):
    """Neither endpoint reachable is not a code bug, so it gets its own type."""

    def boom(url):
        raise exc

    _responder(monkeypatch, boom)

    with pytest.raises(resolve.SearchUnavailable, match="steamcommunity"):
        resolve.search("kingdom come")


def test_exact_match_beats_steams_own_ranking():
    """Steam ranks Portal 2 above Portal; typing the full name must still win."""
    results = [
        resolve.SearchResult(620, "Portal 2"),
        resolve.SearchResult(400, "Portal"),
    ]
    assert resolve.exact_match(results, "portal").appid == 400
    assert resolve.exact_match(results, "  PORTAL  ").appid == 400


def test_exact_match_returns_none_without_one():
    results = [resolve.SearchResult(620, "Portal 2")]
    assert resolve.exact_match(results, "Portal") is None


def test_exact_match_refuses_to_pick_between_duplicate_titles():
    """Two apps with the same title is a genuine ambiguity, not a coin flip."""
    results = [resolve.SearchResult(1, "Same"), resolve.SearchResult(2, "Same")]
    assert resolve.exact_match(results, "Same") is None


def _results():
    return [
        resolve.SearchResult(appid=1, name="One"),
        resolve.SearchResult(appid=2, name="Two"),
    ]


def test_prompt_confirm_returns_the_chosen_result(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "2")
    assert resolve.prompt_confirm(_results()).appid == 2


def test_prompt_confirm_reprompts_until_valid(monkeypatch, capsys):
    answers = iter(["", "banana", "9", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    assert resolve.prompt_confirm(_results()).appid == 1
    assert capsys.readouterr().out.count("Invalid choice") == 3


def test_prompt_confirm_zero_cancels(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "0")
    with pytest.raises(resolve.ResolveError, match="Cancelled"):
        resolve.prompt_confirm(_results())


def test_prompt_confirm_rejects_empty_result_list():
    """Never guess an app: no matches must be an error, not a default pick."""
    with pytest.raises(resolve.ResolveError, match="No matches"):
        resolve.prompt_confirm([])
