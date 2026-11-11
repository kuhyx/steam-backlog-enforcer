"""Tests for _enforce_loop module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._owned_apps_cache import get_all_owned_app_ids
from steam_backlog_enforcer.config import Config

PKG = "steam_backlog_enforcer._enforce_loop"
ENFORCE_STEPS_PKG = "steam_backlog_enforcer._enforce_steps"
OWNED_APPS_CACHE_PKG = "steam_backlog_enforcer._owned_apps_cache"


class TestGetAllOwnedAppIds:
    """Tests for get_all_owned_app_ids."""

    def test_snapshot_used_when_api_fails(self) -> None:
        """The library snapshot answers when the Steam API is down."""
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
        """Without a snapshot the Steam API supplies the ids."""
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
        """No snapshot and a failing API give an empty list."""
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
        """An empty snapshot still asks the Steam API."""
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
        """API and snapshot ids are merged without duplicates."""
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
        """A fresh owned-ids cache skips the API and merges the snapshot."""
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
        """Duplicate ids from the cache and snapshot collapse to one."""
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
        """A successful API fetch is written to the owned-ids cache."""
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
        mock_save.assert_called_once_with("i", [10, 20], [{"appid": 10}, {"appid": 20}])
