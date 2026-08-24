"""Tests for hltb module."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from steam_backlog_enforcer._hltb_search import (
    _AuthInfo,
    _get_hltb_search_url,
    _similarity,
)
from steam_backlog_enforcer.hltb import (
    _get_auth_info,
    load_hltb_cache,
    save_hltb_cache,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestHltbCache:
    """Tests for HLTB cache I/O."""

    def test_load_cache_exists(self, tmp_path: Path) -> None:
        """Test load cache exists."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(json.dumps({"440": 10.5}), encoding="utf-8")
        with patch("steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE", cache_file):
            result = load_hltb_cache()
            assert result == {440: 10.5}

    def test_load_cache_missing(self, tmp_path: Path) -> None:
        """Test load cache missing."""
        cache_file = tmp_path / "nonexistent.json"
        with patch("steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {}

    def test_load_cache_corrupt(self, tmp_path: Path) -> None:
        """Test load cache corrupt."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text("not json", encoding="utf-8")
        with patch("steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {}

    def test_save_cache(self, tmp_path: Path) -> None:
        """Test save cache."""
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch(
                "steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE",
                cache_file,
            ),
            patch("steam_backlog_enforcer._hltb_types.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5})
            assert cache_file.exists()

    def test_save_cache_os_error(self, tmp_path: Path) -> None:
        """Test save cache os error."""
        with patch(
            "steam_backlog_enforcer._hltb_types._atomic_write",
            side_effect=OSError("disk full"),
        ):
            save_hltb_cache({440: 10.5})  # Should not raise

    def test_save_cache_full_extras_skips_existing_read(self, tmp_path: Path) -> None:
        """Test save cache full extras skips existing read."""
        from steam_backlog_enforcer._hltb_types import _HLTBExtras

        cache_file = tmp_path / "hltb_cache.json"
        extras = _HLTBExtras(
            hltb_game_id={440: 1},
            rush={440: 5.0},
            leisure_100h={440: 20.0},
        )
        with (
            patch("steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE", cache_file),
            patch("steam_backlog_enforcer._hltb_types.CONFIG_DIR", tmp_path),
            patch("steam_backlog_enforcer._hltb_types._read_raw_cache") as mock_read,
        ):
            save_hltb_cache({440: 10.5}, extras=extras)
        mock_read.assert_not_called()
        assert cache_file.exists()


class TestGetHltbSearchUrl:
    """Tests for _get_hltb_search_url."""

    def test_discovers_url(self) -> None:
        """Test discovers url."""
        mock_info = MagicMock()
        mock_info.search_url = "/api/search/abc"
        with patch("steam_backlog_enforcer._hltb_search.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.return_value = mock_info
            mock_html.BASE_URL = "https://howlongtobeat.com"
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/search/abc"

    def test_fallback_url(self) -> None:
        """Test fallback url."""
        with patch("steam_backlog_enforcer._hltb_search.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.return_value = None
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/finder"

    def test_first_returns_none_second_returns_info(self) -> None:
        """Test first returns none second returns info."""
        mock_info = MagicMock()
        mock_info.search_url = "/api/search/xyz"
        with patch("steam_backlog_enforcer._hltb_search.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.side_effect = [None, mock_info]
            mock_html.BASE_URL = "https://howlongtobeat.com"
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/search/xyz"

    def test_exception_fallback(self) -> None:
        """Test exception fallback."""
        with patch("steam_backlog_enforcer._hltb_search.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.side_effect = RuntimeError
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/finder"


class TestGetAuthInfo:
    """Tests for _get_auth_info."""

    def test_success(self) -> None:
        """Test success."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"token": "abc123", "hpKey": "ign_x", "hpVal": "ff"}
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result == _AuthInfo("abc123", "ign_x", "ff")

    def test_success_no_hp(self) -> None:
        """Test success no hp."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"token": "abc123"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result == _AuthInfo("abc123")

    def test_no_token_key(self) -> None:
        """Test no token key."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"notoken": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None

    def test_non_200(self) -> None:
        """Test non 200."""
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None

    def test_client_error(self) -> None:
        """Test client error."""
        mock_session = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=ctx)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None


class TestSimilarity:
    """Tests for _similarity."""

    def test_identical(self) -> None:
        """Test identical."""
        assert _similarity("hello", "hello") == 1.0

    def test_different(self) -> None:
        """Test different."""
        assert _similarity("abc", "xyz") < 0.5

    def test_case_insensitive(self) -> None:
        """Test case insensitive."""
        assert _similarity("Hello", "hello") == 1.0
