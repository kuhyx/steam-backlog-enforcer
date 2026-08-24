"""Tests for HLTB poll-count tracking, schema migration, and confidence display."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._hltb_types import (
    HLTBResult,
    _HLTBExtras,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_game_id_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from pathlib import Path

_TYPES = "steam_backlog_enforcer._hltb_types"
_CMD = "steam_backlog_enforcer._cmd_done"
_SCAN = "steam_backlog_enforcer.scanning"


def _state(finished: list[int], current: int | None = None) -> State:
    s = State()
    s.finished_app_ids = list(finished)
    s.current_app_id = current
    s.current_game_name = ""
    return s


class TestCacheSchema:
    """Tests for the new cache schema and back-compat migration."""

    def test_legacy_float_migrates(self, tmp_path: Path) -> None:
        """Test legacy float migrates."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(json.dumps({"440": 10.5}), encoding="utf-8")
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {440: 10.5}
            assert load_hltb_polls_cache() == {440: 0}
            assert load_hltb_count_comp_cache() == {440: 0}

    def test_new_dict_schema(self, tmp_path: Path) -> None:
        """Test new dict schema."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"440": {"hours": 10.5, "polls": 7, "count_comp": 20}}),
            encoding="utf-8",
        )
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {440: 10.5}
            assert load_hltb_polls_cache() == {440: 7}
            assert load_hltb_count_comp_cache() == {440: 20}

    def test_invalid_app_id_skipped(self, tmp_path: Path) -> None:
        """Test invalid app id skipped."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"notanint": 1.0, "440": 5.0}), encoding="utf-8"
        )
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {440: 5.0}

    def test_unparsable_value_skipped(self, tmp_path: Path) -> None:
        """Test unparsable value skipped."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(json.dumps({"440": "notafloat"}), encoding="utf-8")
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {}

    def test_save_with_polls_roundtrip(self, tmp_path: Path) -> None:
        """Test save with polls roundtrip."""
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5}, {440: 7}, _HLTBExtras(count_comp={440: 20}))
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            assert data == {
                "440": {
                    "hours": 10.5,
                    "polls": 7,
                    "count_comp": 20,
                    "rush_hours": -1,
                    "leisure_100h": -1,
                    "hltb_game_id": 0,
                }
            }

    def test_save_without_polls_defaults_zero(self, tmp_path: Path) -> None:
        """Test save without polls defaults zero."""
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5})
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            assert data == {
                "440": {
                    "hours": 10.5,
                    "polls": 0,
                    "count_comp": 0,
                    "rush_hours": -1,
                    "leisure_100h": -1,
                    "hltb_game_id": 0,
                }
            }

    def test_load_game_id_cache(self, tmp_path: Path) -> None:
        """load_hltb_game_id_cache returns the hltb_game_id portion of the cache."""
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5}, extras=_HLTBExtras(hltb_game_id={440: 99}))
            assert load_hltb_game_id_cache() == {440: 99}


class TestHltbResultPolls:
    """Tests for Hltb Result Polls."""

    def test_default_zero(self) -> None:
        """Test default zero."""
        r = HLTBResult(app_id=1, game_name="x", completionist_hours=1.0, similarity=1)
        assert r.comp_100_count == 0
        assert r.count_comp == 0

    def test_explicit(self) -> None:
        """Test explicit."""
        r = HLTBResult(
            app_id=1,
            game_name="x",
            completionist_hours=1.0,
            similarity=1,
            comp_100_count=42,
            count_comp=100,
        )
        assert r.comp_100_count == 42
        assert r.count_comp == 100


class TestGameInfoPolls:
    """Tests for Game Info Polls."""

    def test_snapshot_roundtrip(self) -> None:
        """Test snapshot roundtrip."""
        g = GameInfo(
            app_id=1,
            name="X",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=30,
            comp_100_count=8,
            count_comp=20,
        )
        snap = g.to_snapshot()
        assert snap["comp_100_count"] == 8
        assert snap["count_comp"] == 20
        restored = GameInfo.from_snapshot(snap)
        assert restored.comp_100_count == 8
        assert restored.count_comp == 20

    def test_snapshot_missing_field_defaults(self) -> None:
        """Test snapshot missing field defaults."""
        snap = {
            "app_id": 1,
            "name": "X",
            "total_achievements": 0,
            "unlocked_achievements": 0,
        }
        restored = GameInfo.from_snapshot(snap)
        assert restored.comp_100_count == 0
        assert restored.count_comp == 0
