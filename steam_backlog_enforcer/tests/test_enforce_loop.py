"""Tests for _enforce_loop module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._enforce_loop import (
    _enforce_auto_install,
    _enforce_hide_games,
    _enforce_setup,
    _guard_installed_games,
    _load_owned_app_ids_cache,
    _save_owned_app_ids_cache,
    get_all_owned_app_ids,
)
from steam_backlog_enforcer.config import Config, State

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer._enforce_loop"


class TestGetAllOwnedAppIds:
    """Tests for get_all_owned_app_ids."""

    def test_snapshot_used_when_api_fails(self) -> None:
        snap = [{"app_id": 1}, {"app_id": 2}]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}._load_owned_app_ids_cache", return_value=None),
            patch(f"{PKG}.SteamAPIClient", side_effect=OSError("boom")),
        ):
            assert get_all_owned_app_ids(Config()) == [1, 2]

    def test_no_snapshot_falls_back_to_api(self) -> None:
        mock_client = MagicMock()
        mock_client.get_owned_games.return_value = [
            {"appid": 10},
            {"appid": 20},
        ]
        with (
            patch(f"{PKG}.load_snapshot", return_value=None),
            patch(f"{PKG}._load_owned_app_ids_cache", return_value=None),
            patch(f"{PKG}.SteamAPIClient", return_value=mock_client),
        ):
            result = get_all_owned_app_ids(
                Config(steam_api_key="k", steam_id="i"),
            )
            assert result == [10, 20]

    def test_api_fails(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=None),
            patch(f"{PKG}._load_owned_app_ids_cache", return_value=None),
            patch(
                f"{PKG}.SteamAPIClient",
                side_effect=OSError("fail"),
            ),
        ):
            assert get_all_owned_app_ids(Config()) == []

    def test_empty_snapshot_falls_through_to_api(self) -> None:
        mock_client = MagicMock()
        mock_client.get_owned_games.return_value = [{"appid": 5}]
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}._load_owned_app_ids_cache", return_value=None),
            patch(f"{PKG}.SteamAPIClient", return_value=mock_client),
        ):
            assert get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i")) == [5]

    def test_merges_snapshot_with_api_results(self) -> None:
        mock_client = MagicMock()
        mock_client.get_owned_games.return_value = [{"appid": 10}, {"appid": 20}]
        with (
            patch(
                f"{PKG}.load_snapshot", return_value=[{"app_id": 20}, {"app_id": 30}]
            ),
            patch(f"{PKG}._load_owned_app_ids_cache", return_value=None),
            patch(f"{PKG}.SteamAPIClient", return_value=mock_client),
        ):
            assert get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i")) == [
                10,
                20,
                30,
            ]

    def test_uses_owned_ids_cache_without_api_call(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[{"app_id": 30}]),
            patch(f"{PKG}._load_owned_app_ids_cache", return_value=[10, 20]),
            patch(f"{PKG}.SteamAPIClient") as mock_client,
        ):
            result = get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i"))

        assert result == [10, 20, 30]
        mock_client.assert_not_called()

    def test_cached_ids_merge_deduplicates_entries(self) -> None:
        with (
            patch(
                f"{PKG}.load_snapshot", return_value=[{"app_id": 20}, {"app_id": 30}]
            ),
            patch(f"{PKG}._load_owned_app_ids_cache", return_value=[10, 20, 20]),
            patch(f"{PKG}.SteamAPIClient") as mock_client,
        ):
            result = get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i"))

        assert result == [10, 20, 30]
        mock_client.assert_not_called()

    def test_api_success_saves_owned_ids_cache(self) -> None:
        mock_client = MagicMock()
        mock_client.get_owned_games.return_value = [{"appid": 10}, {"appid": 20}]
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}._load_owned_app_ids_cache", return_value=None),
            patch(f"{PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{PKG}._save_owned_app_ids_cache") as mock_save,
        ):
            result = get_all_owned_app_ids(Config(steam_api_key="k", steam_id="i"))

        assert result == [10, 20]
        mock_save.assert_called_once_with("i", [10, 20])


class TestOwnedIdsCacheHelpers:
    """Tests for owned app IDs cache helper functions."""

    def test_load_cache_no_steam_id(self, tmp_path: Path) -> None:
        with patch(f"{PKG}._OWNED_IDS_CACHE_FILE", tmp_path / "owned.json"):
            assert _load_owned_app_ids_cache("") is None

    def test_load_cache_missing_file(self, tmp_path: Path) -> None:
        with patch(f"{PKG}._OWNED_IDS_CACHE_FILE", tmp_path / "owned.json"):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_invalid_json(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        cache_file.write_text("{invalid", encoding="utf-8")
        with patch(f"{PKG}._OWNED_IDS_CACHE_FILE", cache_file):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_wrong_steam_id(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps({"steam_id": "other", "fetched_at": 1e12, "app_ids": [1]}),
            encoding="utf-8",
        )
        with patch(f"{PKG}._OWNED_IDS_CACHE_FILE", cache_file):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_stale(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps({"steam_id": "sid", "fetched_at": 0, "app_ids": [1]}),
            encoding="utf-8",
        )
        with (
            patch(f"{PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(f"{PKG}.time.time", return_value=10_000.0),
            patch(f"{PKG}._OWNED_IDS_CACHE_TTL_SECONDS", 60),
        ):
            assert _load_owned_app_ids_cache("sid") is None

    def test_load_cache_non_list_ids(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        cache_file.write_text(
            json.dumps({"steam_id": "sid", "fetched_at": 10_000.0, "app_ids": 1}),
            encoding="utf-8",
        )
        with (
            patch(f"{PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(f"{PKG}.time.time", return_value=10_010.0),
            patch(f"{PKG}._OWNED_IDS_CACHE_TTL_SECONDS", 60),
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
            patch(f"{PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(f"{PKG}.time.time", return_value=10_010.0),
            patch(f"{PKG}._OWNED_IDS_CACHE_TTL_SECONDS", 60),
        ):
            assert _load_owned_app_ids_cache("sid") == [1, 2]

    def test_save_cache_writes_atomic_payload(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "owned.json"
        with (
            patch(f"{PKG}._OWNED_IDS_CACHE_FILE", cache_file),
            patch(f"{PKG}.time.time", return_value=123.0),
            patch(f"{PKG}._atomic_write") as mock_atomic,
        ):
            _save_owned_app_ids_cache("sid", [10, 20])

        mock_atomic.assert_called_once()
        path_arg = mock_atomic.call_args.args[0]
        payload_arg = mock_atomic.call_args.args[1]
        assert path_arg == cache_file
        assert '"steam_id": "sid"' in payload_arg
        assert '"app_ids": [\n    10,\n    20\n  ]' in payload_arg


class TestGuardInstalledGames:
    """Tests for _guard_installed_games."""

    def test_removes_unauthorized(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(999, "Bad Game")],
            ),
            patch(f"{PKG}.uninstall_game", return_value=True),
            patch(f"{PKG}.send_notification"),
        ):
            assert _guard_installed_games({440}) == 1

    def test_skips_allowed(self) -> None:
        with patch(
            f"{PKG}.get_installed_games",
            return_value=[(440, "TF2")],
        ):
            assert _guard_installed_games({440}) == 0

    def test_skips_protected(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(228980, "Runtime")],
            ),
            patch(f"{PKG}.is_protected_app", side_effect=lambda aid: aid == 228980),
        ):
            assert _guard_installed_games({440}) == 0

    def test_uninstall_fails(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(999, "Bad")],
            ),
            patch(f"{PKG}.uninstall_game", return_value=False),
        ):
            assert _guard_installed_games({440}) == 0

    def test_allowed_none_skips(self) -> None:
        assert _guard_installed_games(set()) == 0


class TestEnforceSetup:
    """Tests for _enforce_setup."""

    def test_block_store_success(self) -> None:
        config = Config(block_store=True, uninstall_other_games=False)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.block_store", return_value=True),
            patch(f"{PKG}._echo"),
            patch(f"{PKG}._enforce_auto_install"),
            patch(f"{PKG}._enforce_hide_games"),
        ):
            _enforce_setup(config, state)

    def test_block_store_fail(self) -> None:
        config = Config(block_store=True, uninstall_other_games=False)
        state = State()
        with (
            patch(f"{PKG}.block_store", return_value=False),
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}._enforce_auto_install"),
            patch(f"{PKG}._enforce_hide_games"),
        ):
            _enforce_setup(config, state)
            assert any("FAILED" in str(c) for c in mock_echo.call_args_list)

    def test_no_block_store(self) -> None:
        config = Config(block_store=False, uninstall_other_games=False)
        state = State()
        with (
            patch(f"{PKG}.block_store") as mock_block,
            patch(f"{PKG}._echo"),
            patch(f"{PKG}._enforce_auto_install"),
            patch(f"{PKG}._enforce_hide_games"),
        ):
            _enforce_setup(config, state)
            mock_block.assert_not_called()

    def test_uninstall_other_games(self) -> None:
        config = Config(uninstall_other_games=True, block_store=False)
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.uninstall_other_games", return_value=3),
            patch(f"{PKG}._echo"),
            patch(f"{PKG}._enforce_auto_install"),
            patch(f"{PKG}._enforce_hide_games"),
        ):
            _enforce_setup(config, state)


class TestEnforceAutoInstall:
    """Tests for _enforce_auto_install."""

    def test_no_app_id(self) -> None:
        _enforce_auto_install(Config(), State())

    def test_already_installed(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}._echo"),
        ):
            _enforce_auto_install(Config(), state)

    def test_installs_successfully(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch(f"{PKG}.install_game", return_value=True),
            patch(f"{PKG}.send_notification"),
            patch(f"{PKG}._echo"),
        ):
            _enforce_auto_install(Config(steam_id="i"), state)

    def test_install_fails(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch(f"{PKG}.install_game", return_value=False),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            _enforce_auto_install(Config(steam_id="i"), state)
            assert any("manually" in str(c) for c in mock_echo.call_args_list)


class TestEnforceHideGames:
    """Tests for _enforce_hide_games."""

    def test_hides_some(self) -> None:
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(f"{PKG}.try_hide_other_games", return_value=(2, None)),
            patch(f"{PKG}._echo"),
        ):
            _enforce_hide_games(Config(), state)

    def test_already_hidden(self) -> None:
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{PKG}.try_hide_other_games", return_value=(0, None)),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            _enforce_hide_games(Config(), state)
            assert any("already" in str(c) for c in mock_echo.call_args_list)

    def test_no_owned_ids(self) -> None:
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            _enforce_hide_games(Config(), state)
            assert any("skipped" in str(c) for c in mock_echo.call_args_list)

    def test_unreachable_steam_is_not_fatal(self) -> None:
        """An unreachable Steam must degrade, never propagate.

        Regression guard: this exception used to escape all the way out of
        do_enforce, exiting the process into Restart=always - which spun the
        service through ~1000 restarts against an uninstalled Steam.
        """
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(
                f"{PKG}.try_hide_other_games",
                return_value=(0, "Steam is not installed"),
            ),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            _enforce_hide_games(Config(), state)

        assert any("skipped" in str(c) for c in mock_echo.call_args_list)
