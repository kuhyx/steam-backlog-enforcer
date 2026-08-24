"""Tests for protondb module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    _load_cache,
    _rating_from_cache,
    _rating_to_dict,
    _save_cache,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestProtonDBRating:
    """Tests for ProtonDBRating."""

    def test_playable_native(self) -> None:
        """Test playable native."""
        r = ProtonDBRating(app_id=1, tier="native")
        assert r.is_playable is True

    def test_playable_platinum(self) -> None:
        """Test playable platinum."""
        r = ProtonDBRating(app_id=1, tier="platinum")
        assert r.is_playable is True

    def test_playable_gold(self) -> None:
        """Test playable gold."""
        r = ProtonDBRating(app_id=1, tier="gold")
        assert r.is_playable is True

    def test_not_playable_silver(self) -> None:
        """Test not playable silver."""
        r = ProtonDBRating(app_id=1, tier="silver")
        assert r.is_playable is False

    def test_not_playable_bronze(self) -> None:
        """Test not playable bronze."""
        r = ProtonDBRating(app_id=1, tier="bronze")
        assert r.is_playable is False

    def test_not_playable_borked(self) -> None:
        """Test not playable borked."""
        r = ProtonDBRating(app_id=1, tier="borked")
        assert r.is_playable is False

    def test_playable_no_data(self) -> None:
        """Test playable no data."""
        r = ProtonDBRating(app_id=1, tier="")
        assert r.is_playable is True

    def test_playable_pending(self) -> None:
        """Test playable pending."""
        r = ProtonDBRating(app_id=1, tier="pending")
        assert r.is_playable is True

    def test_gold_trending_silver(self) -> None:
        """Test gold trending silver."""
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="silver")
        assert r.is_playable is True

    def test_gold_trending_gold(self) -> None:
        """Test gold trending gold."""
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="gold")
        assert r.is_playable is True

    def test_silver_trending_gold(self) -> None:
        """Test silver trending gold."""
        r = ProtonDBRating(app_id=1, tier="silver", trending_tier="gold")
        assert r.is_playable is True

    def test_gold_no_trending(self) -> None:
        """Test gold no trending."""
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="")
        assert r.is_playable is True

    def test_gold_trending_platinum(self) -> None:
        """Test gold trending platinum."""
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="platinum")
        assert r.is_playable is True

    def test_gold_trending_unknown(self) -> None:
        """Test gold trending unknown."""
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="unknown")
        assert r.is_playable is False

    def test_gold_trending_bronze(self) -> None:
        """Test gold trending bronze."""
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="bronze")
        assert r.is_playable is False

    def test_unknown_tier(self) -> None:
        """Test unknown tier."""
        r = ProtonDBRating(app_id=1, tier="unknown_tier")
        assert r.is_playable is False

    def test_unplayable_reason_no_trending_tier(self) -> None:
        """Test unplayable reason no trending tier."""
        r = ProtonDBRating(app_id=1, tier="borked")
        assert "tier<" in r.unplayable_reason

    def test_unplayable_reason_for_silver_silver(self) -> None:
        """Test unplayable reason for silver silver."""
        r = ProtonDBRating(app_id=1, tier="silver", trending_tier="silver")
        assert "no gold tier" in r.unplayable_reason

    def test_unplayable_reason_for_gold_bronze(self) -> None:
        """Test unplayable reason for gold bronze."""
        r = ProtonDBRating(app_id=1, tier="gold", trending_tier="bronze")
        assert "below silver" in r.unplayable_reason

    def test_unplayable_reason_empty_when_playable(self) -> None:
        """Test unplayable reason empty when playable."""
        r = ProtonDBRating(app_id=1, tier="gold")
        assert r.unplayable_reason == ""


class TestProtonDBCache:
    """Tests for cache I/O."""

    def test_load_cache_exists(self, tmp_path: Path) -> None:
        """Test load cache exists."""
        cache_file = tmp_path / "protondb_cache.json"
        cache_file.write_text(json.dumps({"440": {"tier": "gold"}}), encoding="utf-8")
        with patch(
            "steam_backlog_enforcer.protondb.PROTONDB_CACHE_FILE",
            cache_file,
        ):
            result = _load_cache()
            assert result == {"440": {"tier": "gold"}}

    def test_load_cache_missing(self, tmp_path: Path) -> None:
        """Test load cache missing."""
        cache_file = tmp_path / "nonexistent.json"
        with patch(
            "steam_backlog_enforcer.protondb.PROTONDB_CACHE_FILE",
            cache_file,
        ):
            assert _load_cache() == {}

    def test_save_cache(self, tmp_path: Path) -> None:
        """Test save cache."""
        cache_file = tmp_path / "protondb_cache.json"
        config_dir = tmp_path
        with (
            patch(
                "steam_backlog_enforcer.protondb.PROTONDB_CACHE_FILE",
                cache_file,
            ),
            patch("steam_backlog_enforcer.protondb.CONFIG_DIR", config_dir),
        ):
            _save_cache({"440": {"tier": "gold"}})
            assert cache_file.exists()


class TestRatingConversion:
    """Tests for rating serialization."""

    def test_to_dict(self) -> None:
        """Test to dict."""
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
        """Test from cache."""
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
        """Test from cache defaults."""
        r = _rating_from_cache(440, {})
        assert r.tier == ""
        assert r.total_reports == 0
