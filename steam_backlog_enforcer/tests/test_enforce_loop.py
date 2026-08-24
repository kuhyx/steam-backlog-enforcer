"""Tests for _enforce_loop module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._owned_apps_cache import (
    _load_owned_app_ids_cache,
    _save_owned_app_ids_cache,
    get_all_owned_app_ids,
)
from steam_backlog_enforcer.config import Config

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer._enforce_loop"
ENFORCE_STEPS_PKG = "steam_backlog_enforcer._enforce_steps"
OWNED_APPS_CACHE_PKG = "steam_backlog_enforcer._owned_apps_cache"


class TestGetAllOwnedAppIds:
    """Tests for get_all_owned_app_ids."""

    def test_snapshot_used_when_api_fails(self) -> None:
        snap = [{"app_id": 1}, {"app_id": 2}]
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}.load_snapshot", return_value=snap),
            patch(
                f"{OWNED_APPS_CACHE_PKG}._load_owned_app_ids_cache", return_value=None
            ),
            patch(
                f"{OWNED_APPS_CACHE_PKG}.SteamAPIClient", side_effect=OSError("boom")
            ),
        ):
            assert get_all_owned_app_ids(Config()) == [1, 2]

    def test_no_snapshot_falls_back_to_api(self) -> None:
        mock_client = MagicMock()
        mock_client.get_owned_games.return_value = [
            {"appid": 10},
            {"appid": 20},
        ]
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}.load_snapshot", return_value=None),
            patch(
                f"{OWNED_APPS_CACHE_PKG}._load_owned_app_ids_cache", return_value=None
            ),
            patch(f"{OWNED_APPS_CACHE_PKG}.SteamAPIClient", return_value=mock_client),
        ):
            result = get_all_owned_app_ids(
                Config(steam_api_key="k", steam_id="i"),
            )
            assert result == [10, 20]

    def test_api_fails(self) -> None:
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}.load_snapshot", return_value=None),
            patch(
                f"{OWNED_APPS_CACHE_PKG}._load_owned_app_ids_cache", return_value=None
            ),
            patch(
                f"{OWNED_APPS_CACHE_PKG}.SteamAPIClient",
                side_effect=OSError("fail"),
            ),
        ):
            assert get_all_owned_app_ids(Config()) == []

    def test_empty_snapshot_falls_through_to_api(self) -> None:
        mock_client = MagicMock()
        mock_client.get_owned_games.return_value = [{"appid": 5}]
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}.load_snapshot", return_value=[]),
            patch(
                f"{OWNED_APPS_CACHE_PKG}._load_owned_app_ids_cache", return_value=None
            ),
            patch(f"{OWNED_APPS_CACHE_PKG}.SteamAPIClient", return_value=mock_client),
        ):
            assert get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i")) == [5]

    def test_merges_snapshot_with_api_results(self) -> None:
        mock_client = MagicMock()
        mock_client.get_owned_games.return_value = [{"appid": 10}, {"appid": 20}]
        with (
            patch(
                f"{OWNED_APPS_CACHE_PKG}.load_snapshot",
                return_value=[{"app_id": 20}, {"app_id": 30}],
            ),
            patch(
                f"{OWNED_APPS_CACHE_PKG}._load_owned_app_ids_cache", return_value=None
            ),
            patch(f"{OWNED_APPS_CACHE_PKG}.SteamAPIClient", return_value=mock_client),
        ):
            assert get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i")) == [
                10,
                20,
                30,
            ]

    def test_uses_owned_ids_cache_without_api_call(self) -> None:
        with (
            patch(
                f"{OWNED_APPS_CACHE_PKG}.load_snapshot", return_value=[{"app_id": 30}]
            ),
            patch(
                f"{OWNED_APPS_CACHE_PKG}._load_owned_app_ids_cache",
                return_value=[10, 20],
            ),
            patch(f"{OWNED_APPS_CACHE_PKG}.SteamAPIClient") as mock_client,
        ):
            result = get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i"))

        assert result == [10, 20, 30]
        mock_client.assert_not_called()

    def test_cached_ids_merge_deduplicates_entries(self) -> None:
        with (
            patch(
                f"{OWNED_APPS_CACHE_PKG}.load_snapshot",
                return_value=[{"app_id": 20}, {"app_id": 30}],
            ),
            patch(
                f"{OWNED_APPS_CACHE_PKG}._load_owned_app_ids_cache",
                return_value=[10, 20, 20],
            ),
            patch(f"{OWNED_APPS_CACHE_PKG}.SteamAPIClient") as mock_client,
        ):
            result = get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i"))

        assert result == [10, 20, 30]
        mock_client.assert_not_called()

    def test_api_success_saves_owned_ids_cache(self) -> None:
        mock_client = MagicMock()
        mock_client.get_owned_games.return_value = [{"appid": 10}, {"appid": 20}]
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}.load_snapshot", return_value=[]),
            patch(
                f"{OWNED_APPS_CACHE_PKG}._load_owned_app_ids_cache", return_value=None
            ),
            patch(f"{OWNED_APPS_CACHE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{OWNED_APPS_CACHE_PKG}._save_owned_app_ids_cache") as mock_save,
        ):
            result = get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i"))

        assert result == [10, 20]
        mock_save.assert_called_once_with("i", [10, 20])


class TestOwnedIdsCacheHelpers:
    """Tests for owned app IDs cache helper functions."""

    def test_load_cache_no_steam_id(self, tmp_path: Path) -> None:
        with patch(
            f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", tmp_path / "owned.json"
        ):
            assert _load_owned_app_ids_cache("") is None

    def test_load_cache_missing_file(self, tmp_path: Path) -> None:
        with patch(
            f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", tmp_path / "owned.json"
        ):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_invalid_json(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        cache_file.write_text("{invalid", encoding="utf-8")
        with patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_wrong_steam_id(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps({"steam_id": "other", "fetched_at": 1e12, "app_ids": [1]}),
            encoding="utf-8",
        )
        with patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_stale(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps({"steam_id": "sid", "fetched_at": 0, "app_ids": [1]}),
            encoding="utf-8",
        )
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(f"{PKG}.time.time", return_value=10_000.0),
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_TTL_SECONDS", 60),
        ):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_non_list_ids(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps({"steam_id": "sid", "fetched_at": 10_000.0, "app_ids": 1}),
            encoding="utf-8",
        )
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(f"{PKG}.time.time", return_value=10_010.0),
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_TTL_SECONDS", 60),
        ):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_valid(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps(
                {"steam_id": "sid", "fetched_at": 10_000.0, "app_ids": ["1", 2]}
            ),
            encoding="utf-8",
        )
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(f"{PKG}.time.time", return_value=10_010.0),
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_TTL_SECONDS", 60),
        ):
            assert _load_owned_app_ids_cache("sid") == [1, 2]

    def test_save_cache_writes_atomic_payload(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        with (
            patch(f"{OWNED_APPS_CACHE_PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(f"{PKG}.time.time", return_value=123.0),
            patch(f"{OWNED_APPS_CACHE_PKG}._atomic_write") as mock_atomic,
        ):
            _save_owned_app_ids_cache("sid", [10, 20])

        mock_atomic.assert_called_once()
        path_arg = mock_atomic.call_args.args[0]
        payload_arg = mock_atomic.call_args.args[1]
        assert path_arg == cache_file
        assert '"steam_id": "sid"' in payload_arg
        assert '"app_ids": [\n    10,\n    20\n  ]' in payload_arg
