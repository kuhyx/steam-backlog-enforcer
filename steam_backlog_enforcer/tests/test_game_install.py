"""Tests for game_install module."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from python_pkg.steam_backlog_enforcer.game_install import (
    _assert_not_real_steam,
    _echo,
    _ensure_steam_running,
    _get_real_user,
    _get_uid_gid_for_user,
    _read_install_dir,
    _remove_manifest,
    _trigger_steam_install,
    get_installed_games,
    install_game,
    is_game_installed,
)

if TYPE_CHECKING:
    from pathlib import Path


PKG = "python_pkg.steam_backlog_enforcer.game_install"


class TestAssertNotRealSteam:
    """Tests for the _assert_not_real_steam safety guard."""

    def test_allows_tmp_path(self, tmp_path: Path) -> None:
        """Non-Steam paths pass through without raising."""
        _assert_not_real_steam(tmp_path / "appmanifest_440.acf")

    def test_raises_when_real_steam_not_redirected(self, tmp_path: Path) -> None:
        """Raises when path is under real Steam and STEAMAPPS_PATH is real."""
        real = tmp_path / "real_steam"
        real.mkdir()
        fake_manifest = real / "appmanifest_440.acf"
        fake_manifest.touch()
        with (
            patch(f"{PKG}._REAL_STEAMAPPS", real),
            patch(f"{PKG}.STEAMAPPS_PATH", real),
            pytest.raises(RuntimeError, match="SAFETY"),
        ):
            _assert_not_real_steam(fake_manifest)

    def test_allows_when_steamapps_redirected(self, tmp_path: Path) -> None:
        """No raise when STEAMAPPS_PATH differs from _REAL_STEAMAPPS."""
        real = tmp_path / "real_steam"
        real.mkdir()
        fake_manifest = real / "appmanifest_440.acf"
        fake_manifest.touch()
        redirected = tmp_path / "fake_steam"
        redirected.mkdir()
        with (
            patch(f"{PKG}._REAL_STEAMAPPS", real),
            patch(f"{PKG}.STEAMAPPS_PATH", redirected),
        ):
            _assert_not_real_steam(fake_manifest)


class TestEcho:
    """Tests for _echo."""

    def test_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        _echo("hello")
        assert capsys.readouterr().out == "hello\n"

    def test_custom_end(self, capsys: pytest.CaptureFixture[str]) -> None:
        _echo("hi", end="")
        assert capsys.readouterr().out == "hi"

    def test_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        _echo()
        assert capsys.readouterr().out == "\n"

    def test_flush(self, capsys: pytest.CaptureFixture[str]) -> None:
        _echo("x", flush=True)
        assert capsys.readouterr().out == "x\n"


class TestTriggerSteamInstall:
    """Tests for _trigger_steam_install."""

    def test_success(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.subprocess.run"
        ) as mock_run:
            result = _trigger_steam_install(440, "TF2")
            assert result is True
            mock_run.assert_called_once()

    def test_file_not_found(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = _trigger_steam_install(440, "TF2")
            assert result is False

    def test_os_error(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.subprocess.run",
            side_effect=OSError,
        ):
            result = _trigger_steam_install(440, "TF2")
            assert result is False

    def test_timeout(self) -> None:
        import subprocess

        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.subprocess.run",
            side_effect=subprocess.TimeoutExpired("cmd", 15),
        ):
            result = _trigger_steam_install(440, "TF2")
            assert result is False


class TestGetRealUser:
    """Tests for _get_real_user."""

    def test_sudo_user(self) -> None:
        with patch.dict(os.environ, {"SUDO_USER": "alice", "USER": "root"}):
            assert _get_real_user() == "alice"

    def test_regular_user(self) -> None:
        with patch.dict(os.environ, {"USER": "bob"}, clear=False):
            env = os.environ.copy()
            env.pop("SUDO_USER", None)
            with patch.dict(os.environ, env, clear=True):
                assert _get_real_user() == "bob"


class TestGetUidGid:
    """Tests for _get_uid_gid_for_user."""

    def test_known_user(self) -> None:
        mock_pw = MagicMock()
        mock_pw.pw_uid = 1001
        mock_pw.pw_gid = 1001
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.pwd.getpwnam",
            return_value=mock_pw,
        ):
            assert _get_uid_gid_for_user("alice") == (1001, 1001)

    def test_unknown_user(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.pwd.getpwnam",
            side_effect=KeyError,
        ):
            assert _get_uid_gid_for_user("nobody") == (1000, 1000)


class TestIsGameInstalled:
    """Tests for is_game_installed."""

    def test_installed(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.touch()
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path
        ):
            assert is_game_installed(440) is True

    def test_not_installed(self, tmp_path: Path) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path
        ):
            assert is_game_installed(440) is False


class TestEnsureSteamRunning:
    """Tests for _ensure_steam_running."""

    def test_already_running(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.subprocess.run",
            return_value=mock_result,
        ):
            _ensure_steam_running()

    def test_not_running_starts_as_non_root(self) -> None:
        mock_result = MagicMock(returncode=1)
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.subprocess.Popen"
            ) as mock_popen,
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
            patch("python_pkg.steam_backlog_enforcer.game_install.time.sleep"),
        ):
            _ensure_steam_running()
            mock_popen.assert_called_once()

    def test_not_running_starts_as_root(self) -> None:
        mock_result = MagicMock(returncode=1)
        mock_pw = MagicMock()
        mock_pw.pw_uid = 1000
        mock_pw.pw_gid = 1000
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.subprocess.Popen"
            ) as mock_popen,
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=0,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._get_real_user",
                return_value="alice",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._get_uid_gid_for_user",
                return_value=(1000, 1000),
            ),
            patch("python_pkg.steam_backlog_enforcer.game_install.time.sleep"),
        ):
            _ensure_steam_running()
            mock_popen.assert_called_once()

    def test_pgrep_not_found(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.subprocess.run",
                side_effect=FileNotFoundError,
            ),
            patch("python_pkg.steam_backlog_enforcer.game_install.subprocess.Popen"),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
            patch("python_pkg.steam_backlog_enforcer.game_install.time.sleep"),
        ):
            _ensure_steam_running()

    def test_steam_executable_not_found(self) -> None:
        mock_result = MagicMock(returncode=1)
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.subprocess.Popen",
                side_effect=FileNotFoundError,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
        ):
            _ensure_steam_running()


class TestInstallGame:
    """Tests for install_game."""

    def test_already_installed(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.touch()
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path
        ):
            assert install_game(440, "TF2", "steam123") is True

    def test_use_steam_protocol_success(self, tmp_path: Path) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._ensure_steam_running"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._trigger_steam_install",
                return_value=True,
            ),
        ):
            assert install_game(440, "TF2", "s1", use_steam_protocol=True) is True

    def test_use_steam_protocol_fallback(self, tmp_path: Path) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._ensure_steam_running"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._trigger_steam_install",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
        ):
            assert install_game(440, "TF2", "s1", use_steam_protocol=True) is True
            assert (tmp_path / "appmanifest_440.acf").exists()

    def test_manifest_write_as_root(self, tmp_path: Path) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._ensure_steam_running"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=0,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._get_real_user",
                return_value="alice",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._get_uid_gid_for_user",
                return_value=(1001, 1001),
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.chown"
            ) as mock_chown,
        ):
            assert install_game(440, "TF2", "s1") is True
            mock_chown.assert_called_once()

    def test_manifest_write_failure(self, tmp_path: Path) -> None:
        # Make steamapps path not writable
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path / "nonexistent" / "deep",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._ensure_steam_running"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
        ):
            assert install_game(440, "TF2", "s1") is False

    def test_empty_game_name(self, tmp_path: Path) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._ensure_steam_running"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
        ):
            assert install_game(440, "", "s1") is True

    def test_manifest_not_root_no_chown(self, tmp_path: Path) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._ensure_steam_running"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.chown"
            ) as mock_chown,
        ):
            assert install_game(440, "TF2", "s1") is True
            mock_chown.assert_not_called()

    def test_root_user_is_root(self, tmp_path: Path) -> None:
        """When real user IS root, don't chown."""
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
                tmp_path,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._ensure_steam_running"
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.geteuid",
                return_value=0,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install._get_real_user",
                return_value="root",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.game_install.os.chown"
            ) as mock_chown,
        ):
            assert install_game(440, "TF2", "s1") is True
            mock_chown.assert_not_called()


class TestGetInstalledGames:
    """Tests for get_installed_games."""

    def test_parses_manifests(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"appid"\t\t"440"\n"name"\t\t"Team Fortress 2"\n')
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path
        ):
            result = get_installed_games()
            assert result == [(440, "Team Fortress 2")]

    def test_no_name(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"appid"\t\t"440"\n')
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path
        ):
            result = get_installed_games()
            assert result == [(440, "Unknown (440)")]

    def test_empty_dir(self, tmp_path: Path) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path
        ):
            result = get_installed_games()
            assert result == []

    def test_no_appid_match(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"name"\t\t"NoAppId"\n')
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path
        ):
            result = get_installed_games()
            assert result == []


class TestReadInstallDir:
    """Tests for _read_install_dir."""

    def test_reads_dir(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"installdir"\t\t"Team Fortress 2"\n')
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path
        ):
            result = _read_install_dir(manifest)
            assert result == tmp_path / "common" / "Team Fortress 2"

    def test_no_match(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"appid"\t\t"440"\n')
        with patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path
        ):
            assert _read_install_dir(manifest) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        manifest = tmp_path / "nonexistent.acf"
        assert _read_install_dir(manifest) is None

    def test_os_error(self, tmp_path: Path) -> None:
        manifest = MagicMock()
        manifest.exists.return_value = True
        manifest.read_text.side_effect = OSError
        assert _read_install_dir(manifest) is None


class TestRemoveManifest:
    """Tests for _remove_manifest."""

    def test_removes(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.touch()
        assert _remove_manifest(manifest, "TF2", 440) is True
        assert not manifest.exists()

    def test_already_gone(self, tmp_path: Path) -> None:
        manifest = tmp_path / "nonexistent.acf"
        assert _remove_manifest(manifest, "TF2", 440) is True

    def test_os_error(self) -> None:
        manifest = MagicMock()
        manifest.exists.return_value = True
        manifest.unlink.side_effect = OSError
        assert _remove_manifest(manifest, "TF2", 440) is False
