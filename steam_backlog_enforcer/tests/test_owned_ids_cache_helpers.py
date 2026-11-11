"""Tests for the owned app IDs cache load/save helpers.

Split out of test_enforce_loop.py to keep both files under the 250-line cap.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._owned_apps_cache import (
    _load_owned_app_ids_cache,
    _save_owned_app_ids_cache,
)

if TYPE_CHECKING:
    from pathlib import Path

# The owned-ids cache reads its own clock.
_CLOCK = "steam_backlog_enforcer._owned_apps_cache.time.time"
OWNED_APPS_CACHE_PKG = "steam_backlog_enforcer._owned_apps_cache"


class TestOwnedIdsCacheHelpers:
    """Tests for owned app IDs cache helper functions."""

    def test_load_cache_no_steam_id(self, tmp_path: Path) -> None:
        """No Steam id means no cache hit."""
        with patch(
            f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", tmp_path / "owned.json"
        ):
            assert _load_owned_app_ids_cache("") is None

    def test_load_cache_missing_file(self, tmp_path: Path) -> None:
        """A missing cache file means no cache hit."""
        with patch(
            f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", tmp_path / "owned.json"
        ):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_invalid_json(self, tmp_path: Path) -> None:
        """A corrupt cache file means no cache hit."""
        cache_file = tmp_path / "owned.json"
        cache_file.write_text("{invalid", encoding="utf-8")
        with patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_wrong_steam_id(self, tmp_path: Path) -> None:
        """A cache for another account is ignored."""
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps({"steam_id": "other", "fetched_at": 1e12, "app_ids": [1]}),
            encoding="utf-8",
        )
        with patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_stale(self, tmp_path: Path) -> None:
        """A cache older than the TTL is ignored."""
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps({"steam_id": "sid", "fetched_at": 0, "app_ids": [1]}),
            encoding="utf-8",
        )
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(_CLOCK, return_value=10_000.0),
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_TTL_SECONDS", 60),
        ):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_non_list_ids(self, tmp_path: Path) -> None:
        """A cache whose app_ids is not a list is ignored."""
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps({"steam_id": "sid", "fetched_at": 10_000.0, "app_ids": 1}),
            encoding="utf-8",
        )
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(_CLOCK, return_value=10_010.0),
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_TTL_SECONDS", 60),
        ):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_valid(self, tmp_path: Path) -> None:
        """A fresh matching cache returns its ids as ints."""
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps(
                {"steam_id": "sid", "fetched_at": 10_000.0, "app_ids": ["1", 2]}
            ),
            encoding="utf-8",
        )
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(_CLOCK, return_value=10_010.0),
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_TTL_SECONDS", 60),
        ):
            assert _load_owned_app_ids_cache("sid") == [1, 2]

    def test_save_cache_writes_atomic_payload(self, tmp_path: Path) -> None:
        """Saving writes the steam id and ids atomically as indented JSON."""
        cache_file = tmp_path / "owned.json"
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(_CLOCK, return_value=123.0),
            patch(f"{OWNED_APPS_CACHE_PKG}._atomic_write") as mock_atomic,
        ):
            _save_owned_app_ids_cache("sid", [10, 20])

        mock_atomic.assert_called_once()
        path_arg = mock_atomic.call_args.args[0]
        payload_arg = mock_atomic.call_args.args[1]
        assert path_arg == cache_file
        assert '"steam_id": "sid"' in payload_arg
        assert '"app_ids": [\n    10,\n    20\n  ]' in payload_arg
