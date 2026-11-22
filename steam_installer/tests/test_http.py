"""The one https-only way the package opens a URL."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import pytest

from steam_installer import _http

if TYPE_CHECKING:
    import urllib.request


class _Response:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_a_non_https_url_is_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not even file:// or plain http gets as far as urlopen."""
    monkeypatch.setattr(
        _http.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("no request")
    )
    for url in ("http://example.invalid/x", "file:///etc/passwd", "ftp://x/y"):
        with (
            pytest.raises(ValueError, match="non-https"),
            _http.open_https(url, timeout=1, user_agent="ua"),
        ):
            pass


def test_an_https_url_is_opened_with_the_agent_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The request carries the caller's User-Agent, and the timeout is passed on."""
    seen: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _Response:
        seen["url"] = request.full_url
        seen["agent"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(_http.urllib.request, "urlopen", fake_urlopen)
    with _http.open_https("https://example.invalid/x", timeout=7, user_agent="ua"):
        pass
    assert seen == {"url": "https://example.invalid/x", "agent": "ua", "timeout": 7}
