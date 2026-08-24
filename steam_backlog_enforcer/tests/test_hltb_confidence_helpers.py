"""Tests for hltb module — part 2 (missing coverage)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from typing_extensions import Self

from steam_backlog_enforcer._hltb_search import _AuthInfo
from steam_backlog_enforcer.hltb import (
    _fetch_batch_confidence_only,
    fetch_hltb_confidence,
    fetch_hltb_confidence_cached,
)

PKG = "steam_backlog_enforcer.hltb"
_CONF = "steam_backlog_enforcer._hltb_confidence"


class _DummySession:
    """Minimal async context manager used to mock aiohttp ClientSession."""

    async def __aenter__(self) -> Self:
        """Enter async context."""
        return self

    async def __aexit__(self, *_args: object) -> bool:
        """Exit async context."""
        return False


class TestConfidenceHelpers:
    """Coverage tests for confidence-fetch helpers."""

    def test_fetch_batch_confidence_only_returns_empty_without_auth(self) -> None:
        """Test fetch batch confidence only returns empty without auth."""
        with (
            patch(f"{PKG}.aiohttp.ClientSession", return_value=_DummySession()),
            patch(f"{PKG}.aiohttp.TCPConnector"),
            patch(f"{PKG}._get_hltb_search_url", return_value="https://example"),
            patch(f"{PKG}._get_auth_info", return_value=None),
        ):
            result = asyncio.run(
                _fetch_batch_confidence_only([(1, "Game")], {}, {}, None),
            )
        assert result == []

    def test_fetch_batch_confidence_only_handles_empty_hp_and_default_counts(
        self,
    ) -> None:
        """Test fetch batch confidence only handles empty hp and default counts."""
        auth_token = str(1)
        with (
            patch(f"{PKG}.aiohttp.ClientSession", return_value=_DummySession()),
            patch(f"{PKG}.aiohttp.TCPConnector"),
            patch(f"{PKG}._get_hltb_search_url", return_value="https://example"),
            patch(
                f"{PKG}._get_auth_info",
                return_value=_AuthInfo(token=auth_token, hp_key="", hp_val=""),
            ),
            patch(f"{PKG}._search_one", side_effect=[None]) as mock_search,
        ):
            result = asyncio.run(
                _fetch_batch_confidence_only(
                    games=[(1, "Game")],
                    cache={},
                    polls={},
                    progress_cb=None,
                    count_comp=None,
                ),
            )
        assert result == []
        mock_search.assert_called_once()

    def test_fetch_batch_confidence_only_with_hp_key_and_prepopulated_count_comp(
        self,
    ) -> None:
        """Test fetch batch confidence only with hp key and prepopulated count comp."""
        auth_token = str(1)
        with (
            patch(f"{PKG}.aiohttp.ClientSession", return_value=_DummySession()),
            patch(f"{PKG}.aiohttp.TCPConnector"),
            patch(f"{PKG}._get_hltb_search_url", return_value="https://example"),
            patch(
                f"{PKG}._get_auth_info",
                return_value=_AuthInfo(token=auth_token, hp_key="hpk", hp_val="hpv"),
            ),
            patch(f"{PKG}._search_one", side_effect=[None]) as mock_search,
        ):
            result = asyncio.run(
                _fetch_batch_confidence_only(
                    games=[(1, "Game")],
                    cache={},
                    polls={},
                    progress_cb=None,
                    count_comp={1: 42},
                ),
            )
        assert result == []
        mock_search.assert_called_once()

    def test_fetch_hltb_confidence_initializes_optional_dicts(self) -> None:
        """Test fetch hltb confidence initializes optional dicts."""
        with patch(f"{PKG}.asyncio.run", return_value=[]) as mock_run:
            result = fetch_hltb_confidence([(1, "Game")])
        assert result == []
        mock_run.assert_called_once()

    def test_fetch_hltb_confidence_empty_games_returns_empty(self) -> None:
        """Test fetch hltb confidence empty games returns empty."""
        with patch(f"{PKG}.asyncio.run") as mock_run:
            result = fetch_hltb_confidence([])
        assert result == []
        mock_run.assert_not_called()

    def test_fetch_hltb_confidence_cached_all_cached_skips_fetch(self) -> None:
        """Test fetch hltb confidence cached all cached skips fetch."""
        with (
            patch(f"{_CONF}.load_hltb_cache", return_value={1: 12.0}),
            patch(f"{_CONF}.load_hltb_polls_cache", return_value={1: 30}),
            patch(f"{_CONF}.load_hltb_count_comp_cache", return_value={1: 200}),
            patch(f"{_CONF}.fetch_hltb_confidence") as mock_fetch,
            patch(f"{_CONF}.save_hltb_cache") as mock_save,
        ):
            result = fetch_hltb_confidence_cached([(1, "Game")])
        assert result == {1: 12.0}
        mock_fetch.assert_not_called()
        mock_save.assert_not_called()
