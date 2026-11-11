"""Tests for game_install module (part 3 — install, get, read, remove)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.game_install import install_game
from steam_backlog_enforcer.game_uninstall import (
    _read_install_dir,
    _remove_manifest,
    get_installed_games,
)

if TYPE_CHECKING:
    from pathlib import Path


PKG = "steam_backlog_enforcer.game_install"


class TestInstallGame:
    """Tests for install_game."""

    def test_already_installed(self, tmp_path: Path) -> None:
        """A fully installed game returns True without a fast install."""
        (tmp_path / "appmanifest_440.acf").write_text('"StateFlags"\t\t"4"\n')
        with (
            patch("steam_backlog_enforcer._steam_state.STEAMAPPS_PATH", tmp_path),
            patch(f"{PKG}.fast_install") as fast,
        ):
            assert install_game(440, "TF2", "steam123") is True
        fast.assert_not_called()

    def test_use_steam_protocol_success(self, tmp_path: Path) -> None:
        """The steam:// protocol path succeeds when the trigger does."""
        with (
            patch(
                "steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch("steam_backlog_enforcer.game_install._ensure_steam_running"),
            patch(
                "steam_backlog_enforcer.game_install._trigger_steam_install",
                return_value=True,
            ),
        ):
            assert install_game(440, "TF2", "s1", use_steam_protocol=True) is True

    def test_use_steam_protocol_fallback(self, tmp_path: Path) -> None:
        """A failed protocol trigger falls back to writing the manifest."""
        with (
            patch(
                "steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch("steam_backlog_enforcer.game_install._ensure_steam_running"),
            patch(
                "steam_backlog_enforcer.game_install._trigger_steam_install",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
        ):
            assert install_game(440, "TF2", "s1", use_steam_protocol=True) is True
            assert (tmp_path / "appmanifest_440.acf").exists()

    def test_manifest_write_as_root(self, tmp_path: Path) -> None:
        """Writing the manifest as root chowns it to the real user."""
        with (
            patch(
                "steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch("steam_backlog_enforcer.game_install._ensure_steam_running"),
            patch(
                "steam_backlog_enforcer.game_install.os.geteuid",
                return_value=0,
            ),
            patch(
                "steam_backlog_enforcer.game_install._get_real_user",
                return_value="alice",
            ),
            patch(
                "steam_backlog_enforcer.game_install._get_uid_gid_for_user",
                return_value=(1001, 1001),
            ),
            patch("steam_backlog_enforcer.game_install.os.chown") as mock_chown,
        ):
            assert install_game(440, "TF2", "s1") is True
            mock_chown.assert_called_once()

    def test_manifest_write_failure(self, tmp_path: Path) -> None:
        """An unwritable steamapps dir makes the install fail."""
        # Make steamapps path not writable
        with (
            patch(
                "steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path / "nonexistent" / "deep",
            ),
            patch("steam_backlog_enforcer.game_install._ensure_steam_running"),
            patch(
                "steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
        ):
            assert install_game(440, "TF2", "s1") is False

    def test_empty_game_name(self, tmp_path: Path) -> None:
        """An empty game name still installs."""
        with (
            patch(
                "steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch("steam_backlog_enforcer.game_install._ensure_steam_running"),
            patch(
                "steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
        ):
            assert install_game(440, "", "s1") is True

    def test_manifest_not_root_no_chown(self, tmp_path: Path) -> None:
        """A non-root install does not chown the manifest."""
        with (
            patch(
                "steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch("steam_backlog_enforcer.game_install._ensure_steam_running"),
            patch(
                "steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
            patch("steam_backlog_enforcer.game_install.os.chown") as mock_chown,
        ):
            assert install_game(440, "TF2", "s1") is True
            mock_chown.assert_not_called()

    def test_root_user_is_root(self, tmp_path: Path) -> None:
        """When real user IS root, don't chown."""
        with (
            patch(
                "steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch("steam_backlog_enforcer.game_install._ensure_steam_running"),
            patch(
                "steam_backlog_enforcer.game_install.os.geteuid",
                return_value=0,
            ),
            patch(
                "steam_backlog_enforcer.game_install._get_real_user",
                return_value="root",
            ),
            patch("steam_backlog_enforcer.game_install.os.chown") as mock_chown,
        ):
            assert install_game(440, "TF2", "s1") is True
            mock_chown.assert_not_called()


class TestGetInstalledGames:
    """Tests for get_installed_games."""

    def test_parses_manifests(self, tmp_path: Path) -> None:
        """App id and name are read from each manifest."""
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"appid"\t\t"440"\n"name"\t\t"Team Fortress 2"\n')
        with patch("steam_backlog_enforcer.game_uninstall.STEAMAPPS_PATH", tmp_path):
            result = get_installed_games()
            assert result == [(440, "Team Fortress 2")]

    def test_no_name(self, tmp_path: Path) -> None:
        """A manifest without a name gets an Unknown placeholder."""
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"appid"\t\t"440"\n')
        with patch("steam_backlog_enforcer.game_uninstall.STEAMAPPS_PATH", tmp_path):
            result = get_installed_games()
            assert result == [(440, "Unknown (440)")]

    def test_empty_dir(self, tmp_path: Path) -> None:
        """An empty steamapps dir lists no games."""
        with patch("steam_backlog_enforcer.game_uninstall.STEAMAPPS_PATH", tmp_path):
            result = get_installed_games()
            assert result == []

    def test_no_appid_match(self, tmp_path: Path) -> None:
        """A manifest without an app id is skipped."""
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"name"\t\t"NoAppId"\n')
        with patch("steam_backlog_enforcer.game_uninstall.STEAMAPPS_PATH", tmp_path):
            result = get_installed_games()
            assert result == []


class TestReadInstallDir:
    """Tests for _read_install_dir."""

    def test_reads_dir(self, tmp_path: Path) -> None:
        """installdir resolves under steamapps/common."""
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"installdir"\t\t"Team Fortress 2"\n')
        with patch("steam_backlog_enforcer.game_uninstall.STEAMAPPS_PATH", tmp_path):
            result = _read_install_dir(manifest)
            assert result == tmp_path / "common" / "Team Fortress 2"

    def test_no_match(self, tmp_path: Path) -> None:
        """A manifest without installdir yields None."""
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"appid"\t\t"440"\n')
        with patch("steam_backlog_enforcer.game_uninstall.STEAMAPPS_PATH", tmp_path):
            assert _read_install_dir(manifest) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        """A missing manifest yields None."""
        manifest = tmp_path / "nonexistent.acf"
        assert _read_install_dir(manifest) is None

    def test_os_error(self) -> None:
        """A read error yields None."""
        manifest = MagicMock()
        manifest.exists.return_value = True
        manifest.read_text.side_effect = OSError
        assert _read_install_dir(manifest) is None


class TestRemoveManifest:
    """Tests for _remove_manifest."""

    def test_removes(self, tmp_path: Path) -> None:
        """An existing manifest is deleted."""
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.touch()
        assert _remove_manifest(manifest, "TF2", 440) is True
        assert not manifest.exists()

    def test_already_gone(self, tmp_path: Path) -> None:
        """A manifest already gone counts as removed."""
        manifest = tmp_path / "nonexistent.acf"
        assert _remove_manifest(manifest, "TF2", 440) is True

    def test_os_error(self) -> None:
        """An unlink error reports failure."""
        manifest = MagicMock()
        manifest.exists.return_value = True
        manifest.unlink.side_effect = OSError
        assert _remove_manifest(manifest, "TF2", 440) is False
