"""Tests for the per-game records kept in the owned-apps cache."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _owned_apps_cache as cache_mod
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.steam_api import SteamAPIError

_PKG = "steam_backlog_enforcer._owned_apps_cache"
_FULL = {
    "appid": 10,
    "name": "Half-Life",
    "playtime_forever": 120,
    "rtime_last_played": 1_700_000_000,
    "has_community_visible_stats": True,
}


def _write(payload: object) -> None:
    cache_mod._OWNED_IDS_CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")


def _configured() -> Config:
    return Config(steam_api_key="k", steam_id="sid")


class TestOwnedRecord:
    """The slice of a GetOwnedGames entry the library shows."""

    def test_maps_every_field(self) -> None:
        assert cache_mod._owned_record(_FULL) == {
            "app_id": 10,
            "name": "Half-Life",
            "playtime_minutes": 120,
            "last_played": 1_700_000_000,
            "has_stats": True,
        }

    def test_missing_fields_default_to_empty(self) -> None:
        assert cache_mod._owned_record({"appid": "7"}) == {
            "app_id": 7,
            "name": "",
            "playtime_minutes": 0,
            "last_played": 0,
            "has_stats": False,
        }


class TestSaveRecords:
    """_save_owned_app_ids_cache stores records only when given games."""

    def test_games_become_records(self) -> None:
        cache_mod._save_owned_app_ids_cache("sid", [10], [_FULL, {"name": "no id"}])
        data: dict[str, Any] = json.loads(
            cache_mod._OWNED_IDS_CACHE_FILE.read_text(encoding="utf-8")
        )
        assert data["app_ids"] == [10]
        assert [g["app_id"] for g in data["games"]] == [10]

    def test_without_games_there_are_no_records(self) -> None:
        cache_mod._save_owned_app_ids_cache("sid", [10])
        data = json.loads(cache_mod._OWNED_IDS_CACHE_FILE.read_text(encoding="utf-8"))
        assert "games" not in data


class TestOwnedCacheStamp:
    """The stamp changes whenever the file is rewritten."""

    def test_absent_file_is_zero(self) -> None:
        assert cache_mod.owned_cache_stamp() == (0, 0)

    def test_present_file_reports_mtime_and_size(self) -> None:
        _write({"steam_id": "sid"})
        mtime_ns, size = cache_mod.owned_cache_stamp()
        assert mtime_ns > 0
        assert size == len(json.dumps({"steam_id": "sid"}))


class TestLoadOwnedRecords:
    """load_owned_records ignores the TTL but not the account."""

    def test_returns_stored_records(self) -> None:
        records = [{"app_id": 10}]
        _write({"steam_id": "sid", "fetched_at": 0, "games": records})
        assert cache_mod.load_owned_records("sid") == records

    @pytest.mark.parametrize(
        "payload",
        [
            {"steam_id": "other", "games": []},
            {"steam_id": "sid"},
            {"steam_id": "sid", "games": "nope"},
            ["not", "a", "dict"],
        ],
    )
    def test_unusable_cache_is_none(self, payload: object) -> None:
        _write(payload)
        assert cache_mod.load_owned_records("sid") is None

    def test_missing_file_is_none(self) -> None:
        assert cache_mod.load_owned_records("sid") is None

    def test_corrupt_file_is_none(self) -> None:
        cache_mod._OWNED_IDS_CACHE_FILE.write_text("{nope", encoding="utf-8")
        assert cache_mod.load_owned_records("sid") is None


class TestRefreshOwnedRecords:
    """refresh_owned_records asks Steam (mocked) and rewrites the cache."""

    @pytest.mark.parametrize(
        "config", [Config(steam_id="sid"), Config(steam_api_key="k")]
    )
    def test_unconfigured_never_asks_steam(self, config: Config) -> None:
        with patch(f"{_PKG}.SteamAPIClient") as client:
            assert cache_mod.refresh_owned_records(config) is None
        client.assert_not_called()

    def test_fetches_caches_and_returns_records(self) -> None:
        client = MagicMock()
        client.get_owned_games.return_value = [_FULL, {"name": "no id"}]
        with patch(f"{_PKG}.SteamAPIClient", return_value=client) as ctor:
            records = cache_mod.refresh_owned_records(_configured())
        ctor.assert_called_once_with("k", "sid")
        assert records is not None
        assert [r["app_id"] for r in records] == [10]
        assert cache_mod.load_owned_records("sid") == records

    @pytest.mark.parametrize("error", [OSError("down"), SteamAPIError("bad key")])
    def test_steam_failure_is_none(self, error: Exception) -> None:
        with patch(f"{_PKG}.SteamAPIClient", side_effect=error):
            assert cache_mod.refresh_owned_records(_configured()) is None
        assert cache_mod.owned_cache_stamp() == (0, 0)


class TestGetAllOwnedAppIdsCached:
    """The cached branch merges cached ids with the snapshot, de-duplicated."""

    def test_cache_hit_skips_steam(self) -> None:
        with (
            patch(f"{_PKG}._load_owned_app_ids_cache", return_value=[1, 2]),
            patch(f"{_PKG}.load_snapshot", return_value=[{"app_id": 2}, {"app_id": 3}]),
            patch(f"{_PKG}.SteamAPIClient") as client,
        ):
            assert cache_mod.get_all_owned_app_ids(_configured()) == [1, 2, 3]
        client.assert_not_called()

    def test_api_ids_are_merged_without_duplicates(self) -> None:
        client = MagicMock()
        client.get_owned_games.return_value = [{"appid": 1}, {"appid": 2}]
        with (
            patch(f"{_PKG}._load_owned_app_ids_cache", return_value=None),
            patch(f"{_PKG}.load_snapshot", return_value=[{"app_id": 2}, {"app_id": 3}]),
            patch(f"{_PKG}.SteamAPIClient", return_value=client),
        ):
            assert cache_mod.get_all_owned_app_ids(_configured()) == [1, 2, 3]
