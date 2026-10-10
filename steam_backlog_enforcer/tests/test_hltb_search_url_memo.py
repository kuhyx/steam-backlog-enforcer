"""Tests for the HLTB search-endpoint memo (discovery costs ~0.8 s)."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer import _hltb_search_api as api

_PKG = "steam_backlog_enforcer._hltb_search_api"
_FOUND = "https://howlongtobeat.com/api/search/abc"


class TestSearchUrlMemo:
    def test_a_discovered_url_is_reused_until_it_goes_stale(self) -> None:
        with (
            patch(f"{_PKG}._discover_hltb_search_url", return_value=_FOUND) as find,
            patch(f"{_PKG}.time.monotonic", side_effect=[0.0, 10.0]),
        ):
            assert api._get_hltb_search_url() == _FOUND
            assert api._get_hltb_search_url() == _FOUND
        find.assert_called_once()

    def test_a_stale_memo_is_rediscovered(self) -> None:
        later = api._SEARCH_URL_TTL_SECONDS + 1
        with (
            patch(f"{_PKG}._discover_hltb_search_url", return_value=_FOUND) as find,
            patch(f"{_PKG}.time.monotonic", side_effect=[0.0, later]),
        ):
            api._get_hltb_search_url()
            api._get_hltb_search_url()
        assert find.call_count == 2

    def test_the_fallback_is_never_remembered(self) -> None:
        with patch(
            f"{_PKG}._discover_hltb_search_url", return_value=api._DEFAULT_SEARCH_URL
        ) as find:
            api._get_hltb_search_url()
            api._get_hltb_search_url()
        assert find.call_count == 2

    def test_forgetting_forces_a_new_discovery(self) -> None:
        with patch(f"{_PKG}._discover_hltb_search_url", return_value=_FOUND) as find:
            api._get_hltb_search_url()
            api.forget_hltb_search_url()
            api._get_hltb_search_url()
        assert find.call_count == 2
