"""Tests for protondb module."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from python_pkg.steam_backlog_enforcer.protondb import (
    HTTP_NOT_FOUND,
    ProtonDBRating,
    _fetch_batch,
    _fetch_one,
    _load_cache,
    _rating_from_cache,
    _rating_to_dict,
    _save_cache,
    fetch_protondb_ratings,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestProtonDBRating:
    """Tests for ProtonDBRating."""

    def test_playable_native(self) -> None:
        r = ProtonDBRating(app_id=1, tier="native")
        assert r.is_playable is True

    def test_playable_platinum(self) -> None:
        r = ProtonDBRating(app_id=1, tier="platinum")
        assert r.is_playable is True

    def test_playable_gold(self) -> None:
        r = ProtonDBRating(app_id=1, tier="gold")
        assert r.is_playable is True

    def test_not_playable_silver(self) -> None:
        r = ProtonDBRating(app_id=1, tier="silver")
        assert r.is_playable is False

    def test_not_playable_bronze(self) -> None:
        r = ProtonDBRating(app_id=1, tier="bronze")
        assert r.is_playable is False

    def test_not_playable_borked(self) -> None:
        r = ProtonDBRating(app_id=1, tier="borked")
        assert r.is_playable is False

    def test_playable_no_data(self) -> None:
        r = ProtonDBRating(app_id=1, tier="")
        assert r.is_playable is True

    def test_playable_pending(self) -> None:
        r = ProtonDBRating(app_id=1, tier="pending")
        assert r.is_playable is True

    def test_gold_trending_silver(self) -> None:
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="silver")
        assert r.is_playable is False

    def test_gold_trending_gold(self) -> None:
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="gold")
        assert r.is_playable is True

    def test_gold_no_trending(self) -> None:
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="")
        assert r.is_playable is True

    def test_gold_trending_platinum(self) -> None:
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="platinum")
        assert r.is_playable is True

    def test_gold_trending_unknown(self) -> None:
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="unknown")
        assert r.is_playable is False

    def test_unknown_tier(self) -> None:
        r = ProtonDBRating(app_id=1, tier="unknown_tier")
        assert r.is_playable is False


class TestProtonDBCache:
    """Tests for cache I/O."""

    def test_load_cache_exists(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "protondb_cache.json"
        cache_file.write_text(json.dumps({"440": {"tier": "gold"}}), encoding="utf-8")
        with patch(
            "python_pkg.steam_backlog_enforcer.protondb.PROTONDB_CACHE_FILE",
            cache_file,
        ):
            result = _load_cache()
            assert result == {"440": {"tier": "gold"}}

    def test_load_cache_missing(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "nonexistent.json"
        with patch(
            "python_pkg.steam_backlog_enforcer.protondb.PROTONDB_CACHE_FILE",
            cache_file,
        ):
            assert _load_cache() == {}

    def test_save_cache(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "protondb_cache.json"
        config_dir = tmp_path
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.protondb.PROTONDB_CACHE_FILE",
                cache_file,
            ),
            patch("python_pkg.steam_backlog_enforcer.protondb.CONFIG_DIR", config_dir),
        ):
            _save_cache({"440": {"tier": "gold"}})
            assert cache_file.exists()


class TestRatingConversion:
    """Tests for rating serialization."""

    def test_to_dict(self) -> None:
        r = ProtonDBRating(
            app_id=1,
            tier="gold",
            trending_tier="platinum",
            score=0.9,
            confidence="high",
            total_reports=100,
        )
        d = _rating_to_dict(r)
        assert d["tier"] == "gold"
        assert d["total_reports"] == 100

    def test_from_cache(self) -> None:
        data: dict[str, Any] = {
            "tier": "silver",
            "trending_tier": "bronze",
            "score": 0.5,
        }
        r = _rating_from_cache(440, data)
        assert r.app_id == 440
        assert r.tier == "silver"
        assert r.trending_tier == "bronze"

    def test_from_cache_defaults(self) -> None:
        r = _rating_from_cache(440, {})
        assert r.tier == ""
        assert r.total_reports == 0


class TestFetchOne:
    """Tests for _fetch_one."""

    def test_success(self) -> None:
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
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = MagicMock(side_effect=aiohttp.ClientError)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        sem = asyncio.Semaphore(1)
        result = asyncio.run(_fetch_one(mock_session, sem, 440))
        assert result.tier == ""


class TestFetchBatch:
    """Tests for _fetch_batch."""

    def test_returns_ratings(self) -> None:
        rating = ProtonDBRating(app_id=440, tier="gold")
        with patch(
            "python_pkg.steam_backlog_enforcer.protondb._fetch_one",
            new_callable=AsyncMock,
            return_value=rating,
        ):
            result = asyncio.run(_fetch_batch([440]))
            assert len(result) == 1
            assert result[0].tier == "gold"


class TestFetchProtondbRatings:
    """Tests for fetch_protondb_ratings."""

    def test_all_cached(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "protondb_cache.json"
        cache_file.write_text(json.dumps({"440": {"tier": "gold"}}), encoding="utf-8")
        with patch(
            "python_pkg.steam_backlog_enforcer.protondb.PROTONDB_CACHE_FILE",
            cache_file,
        ):
            result = fetch_protondb_ratings([440])
            assert 440 in result
            assert result[440].tier == "gold"

    def test_fetch_uncached(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "protondb_cache.json"
        config_dir = tmp_path
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.protondb.PROTONDB_CACHE_FILE",
                cache_file,
            ),
            patch("python_pkg.steam_backlog_enforcer.protondb.CONFIG_DIR", config_dir),
            patch(
                "python_pkg.steam_backlog_enforcer.protondb._fetch_batch",
                return_value=[ProtonDBRating(app_id=440, tier="platinum")],
            ),
        ):
            result = fetch_protondb_ratings([440])
            assert result[440].tier == "platinum"
