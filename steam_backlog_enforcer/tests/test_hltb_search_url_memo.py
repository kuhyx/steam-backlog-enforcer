"""Tests for the HLTB search-endpoint memo (discovery costs ~0.8 s)."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._hltb_search_api import (
    _DEFAULT_SEARCH_URL,
    _SEARCH_URL_TTL_SECONDS,
    _get_hltb_search_url,
    forget_hltb_search_url,
)

_PKG = "steam_backlog_enforcer._hltb_search_api"
_FOUND = "https://howlongtobeat.com/api/search/abc"


class TestSearchUrlMemo:
    """The discovered search URL is memoised with a TTL, never the fallback."""

    def test_a_discovered_url_is_reused_until_it_goes_stale(self) -> None:
        """A fresh memo skips a second discovery."""
        with (
            patch(f"{_PKG}._discover_hltb_search_url", return_value=_FOUND) as find,
            patch(f"{_PKG}.time.monotonic", side_effect=[0.0, 10.0]),
        ):
            assert _get_hltb_search_url() == _FOUND
            assert _get_hltb_search_url() == _FOUND
        find.assert_called_once()

    def test_a_stale_memo_is_rediscovered(self) -> None:
        """A memo older than the TTL triggers a new discovery."""
        later = _SEARCH_URL_TTL_SECONDS + 1
        with (
            patch(f"{_PKG}._discover_hltb_search_url", return_value=_FOUND) as find,
            patch(f"{_PKG}.time.monotonic", side_effect=[0.0, later]),
        ):
            _get_hltb_search_url()
            _get_hltb_search_url()
        assert find.call_count == 2

    def test_the_fallback_is_never_remembered(self) -> None:
        """The default URL is not memoised, so discovery runs again."""
        with patch(
            f"{_PKG}._discover_hltb_search_url", return_value=_DEFAULT_SEARCH_URL
        ) as find:
            _get_hltb_search_url()
            _get_hltb_search_url()
        assert find.call_count == 2

    def test_forgetting_forces_a_new_discovery(self) -> None:
        """forget_hltb_search_url drops the memo."""
        with patch(f"{_PKG}._discover_hltb_search_url", return_value=_FOUND) as find:
            _get_hltb_search_url()
            forget_hltb_search_url()
            _get_hltb_search_url()
        assert find.call_count == 2
