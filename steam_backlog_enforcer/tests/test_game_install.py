"""Tests for game_install module."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer.game_install import (
    _assert_not_real_steam,
    _echo,
    _ensure_steam_running,
    _get_real_user,
    _get_uid_gid_for_user,
    _trigger_steam_install,
    is_game_installed,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


PKG = "steam_backlog_enforcer.game_install"


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

    def test_noop_outside_pytest(self, tmp_path: Path) -> None:
        """In production (no PYTEST_CURRENT_TEST) the guard is a no-op."""
        real = tmp_path / "real_steam"
        real.mkdir()
        fake_manifest = real / "appmanifest_440.acf"
        fake_manifest.touch()
        env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch(f"{PKG}._REAL_STEAMAPPS", real),
            patch(f"{PKG}.STEAMAPPS_PATH", real),
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
        with patch("steam_backlog_enforcer.game_install.subprocess.run") as mock_run:
            result = _trigger_steam_install(440, "TF2")
            assert result is True
            mock_run.assert_called_once()

    def test_file_not_found(self) -> None:
        with patch(
            "steam_backlog_enforcer.game_install.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = _trigger_steam_install(440, "TF2")
            assert result is False

    def test_os_error(self) -> None:
        with patch(
            "steam_backlog_enforcer.game_install.subprocess.run",
            side_effect=OSError,
        ):
            result = _trigger_steam_install(440, "TF2")
            assert result is False

    def test_timeout(self) -> None:
        import subprocess

        with patch(
            "steam_backlog_enforcer.game_install.subprocess.run",
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
            "steam_backlog_enforcer.game_install.pwd.getpwnam",
            return_value=mock_pw,
        ):
            assert _get_uid_gid_for_user("alice") == (1001, 1001)

    def test_unknown_user(self) -> None:
        with patch(
            "steam_backlog_enforcer.game_install.pwd.getpwnam",
            side_effect=KeyError,
        ):
            assert _get_uid_gid_for_user("nobody") == (1000, 1000)


class TestIsGameInstalled:
    """Tests for is_game_installed."""

    def test_installed(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.touch()
        with patch("steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path):
            assert is_game_installed(440) is True

    def test_not_installed(self, tmp_path: Path) -> None:
        with patch("steam_backlog_enforcer.game_install.STEAMAPPS_PATH", tmp_path):
            assert is_game_installed(440) is False


class TestEnsureSteamRunning:
    """Tests for _ensure_steam_running."""

    @pytest.fixture(autouse=True)
    def _steam_present(self) -> Iterator[None]:
        """Pretend Steam is installed for every test in this class.

        Without it the function returns before any launch, which on a test
        machine without Steam would make the launch assertions vacuous. The
        absent case is covered by test_skips_when_steam_absent.
        """
        with patch(f"{PKG}.steam_is_installed", return_value=True):
            yield

    def test_skips_when_steam_absent(self) -> None:
        """With Steam uninstalled, do not try to launch a missing client.

        Regression guard: this path used to exec a dead launcher wrapper and
        then sleep 15s, leaving a zombie named "steam" behind each time.
        """
        with (
            patch(f"{PKG}.steam_is_installed", return_value=False),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
            patch(f"{PKG}.time.sleep") as mock_sleep,
        ):
            _ensure_steam_running()

        mock_popen.assert_not_called()
        mock_sleep.assert_not_called()

    def test_already_running(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch(
            "steam_backlog_enforcer.game_install.subprocess.run",
            return_value=mock_result,
        ):
            _ensure_steam_running()

    def test_not_running_starts_as_non_root(self) -> None:
        mock_result = MagicMock(returncode=1)
        with (
            patch(
                "steam_backlog_enforcer.game_install.subprocess.run",
                return_value=mock_result,
            ),
            patch("steam_backlog_enforcer.game_install.subprocess.Popen") as mock_popen,
            patch(
                "steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
            patch("steam_backlog_enforcer.game_install.time.sleep"),
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
                "steam_backlog_enforcer.game_install.subprocess.run",
                return_value=mock_result,
            ),
            patch("steam_backlog_enforcer.game_install.subprocess.Popen") as mock_popen,
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
                return_value=(1000, 1000),
            ),
            patch("steam_backlog_enforcer.game_install.time.sleep"),
        ):
            _ensure_steam_running()
            mock_popen.assert_called_once()

    def test_pgrep_not_found(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer.game_install.subprocess.run",
                side_effect=FileNotFoundError,
            ),
            patch("steam_backlog_enforcer.game_install.subprocess.Popen"),
            patch(
                "steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
            patch("steam_backlog_enforcer.game_install.time.sleep"),
        ):
            _ensure_steam_running()

    def test_steam_executable_not_found(self) -> None:
        mock_result = MagicMock(returncode=1)
        with (
            patch(
                "steam_backlog_enforcer.game_install.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "steam_backlog_enforcer.game_install.subprocess.Popen",
                side_effect=FileNotFoundError,
            ),
            patch(
                "steam_backlog_enforcer.game_install.os.geteuid",
                return_value=1000,
            ),
        ):
            _ensure_steam_running()
