import io
import json
import urllib.error

import pytest

from steam_installer import resolve


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_search_parses_items(monkeypatch):
    payload = {"items": [{"id": 1771300, "name": "Kingdom Come: Deliverance II"}]}
    monkeypatch.setattr(
        resolve.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeResponse(json.dumps(payload).encode()),
    )

    results = resolve.search("kingdom come")

    assert results == [
        resolve.SearchResult(appid=1771300, name="Kingdom Come: Deliverance II")
    ]


def test_search_quotes_the_term(monkeypatch):
    seen = {}

    def fake_urlopen(url, timeout):
        seen["url"] = url
        return _FakeResponse(b'{"items": []}')

    monkeypatch.setattr(resolve.urllib.request, "urlopen", fake_urlopen)

    resolve.search("kingdom come/2")

    assert "kingdom%20come/2" in seen["url"] or "kingdom%20come%2F2" in seen["url"]


def test_search_missing_items_key_returns_empty(monkeypatch):
    monkeypatch.setattr(
        resolve.urllib.request, "urlopen", lambda url, timeout: _FakeResponse(b"{}")
    )
    assert resolve.search("nothing") == []


@pytest.mark.parametrize(
    "exc", [urllib.error.URLError("tls blocked"), TimeoutError("timed out")]
)
def test_search_network_failure_becomes_search_unavailable(monkeypatch, exc):
    """store.steampowered.com is known to reject scripted clients on some
    networks -- that is not a code bug, so it gets its own exception type."""

    def boom(url, timeout):
        raise exc

    monkeypatch.setattr(resolve.urllib.request, "urlopen", boom)

    with pytest.raises(resolve.SearchUnavailable):
        resolve.search("kingdom come")


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
