"""Tests for protondb module."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    _fetch_batch,
    fetch_protondb_ratings,
)
from steam_backlog_enforcer.tests._protondb_cache import (
    cache_at,
    writable_cache_at,
    write_gold_cache,
)

if TYPE_CHECKING:
    from pathlib import Path

    import aiohttp


class TestFetchBatch:
    """Tests for _fetch_batch."""

    def test_returns_ratings(self) -> None:
        """Test returns ratings."""
        rating = ProtonDBRating(app_id=440, tier="gold")
        with patch(
            "steam_backlog_enforcer.protondb._fetch_one",
            new_callable=AsyncMock,
            return_value=rating,
        ):
            result = asyncio.run(_fetch_batch([440]))
            assert len(result) == 1
            assert result[0].tier == "gold"

    def test_filters_none_results(self) -> None:
        """Network failures (None) are filtered out of the batch result."""
        rating = ProtonDBRating(app_id=440, tier="gold")

        async def mock_fetch_one(
            _session: aiohttp.ClientSession,
            _sem: asyncio.Semaphore,
            app_id: int,
        ) -> ProtonDBRating | None:
            """Test mock fetch one."""
            return rating if app_id == 440 else None

        with patch(
            "steam_backlog_enforcer.protondb._fetch_one",
            side_effect=mock_fetch_one,
        ):
            result = asyncio.run(_fetch_batch([440, 999]))
            assert len(result) == 1
            assert result[0].app_id == 440


class TestFetchProtondbRatings:
    """Tests for fetch_protondb_ratings."""

    def test_all_cached(self, tmp_path: Path) -> None:
        """Test all cached."""
        with cache_at(write_gold_cache(tmp_path)):
            result = fetch_protondb_ratings([440])
            assert 440 in result
            assert result[440].tier == "gold"

    def test_fetch_uncached(self, tmp_path: Path) -> None:
        """Test fetch uncached."""
        with (
            writable_cache_at(tmp_path / "protondb_cache.json", tmp_path),
            patch(
                "steam_backlog_enforcer.protondb._fetch_batch",
                return_value=[ProtonDBRating(app_id=440, tier="platinum")],
            ),
        ):
            result = fetch_protondb_ratings([440])
            assert result[440].tier == "platinum"
