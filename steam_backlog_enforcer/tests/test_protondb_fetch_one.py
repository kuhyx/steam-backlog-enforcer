"""Tests for protondb module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from steam_backlog_enforcer.protondb import (
    HTTP_NOT_FOUND,
    _fetch_one,
)


class TestFetchOne:
    """Tests for _fetch_one."""

    def test_success(self) -> None:
        """Test success."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={"tier": "gold", "trendingTier": "platinum"}
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        sem = asyncio.Semaphore(1)
        result = asyncio.run(_fetch_one(mock_session, sem, 440))
        assert result.tier == "gold"

    def test_not_found(self) -> None:
        """Test not found."""
        mock_resp = AsyncMock()
        mock_resp.status = HTTP_NOT_FOUND
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        sem = asyncio.Semaphore(1)
        result = asyncio.run(_fetch_one(mock_session, sem, 440))
        assert result.tier == ""

    def test_client_error(self) -> None:
        """Test client error."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock(side_effect=aiohttp.ClientError)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        sem = asyncio.Semaphore(1)
        result = asyncio.run(_fetch_one(mock_session, sem, 440))
        assert result is None
