"""Tests for game_install module."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._steam_client import (
    _get_real_user,
    _get_uid_gid_for_user,
    is_game_installed,
)
from steam_backlog_enforcer._steam_state import _assert_not_real_steam
from steam_backlog_enforcer.game_install import (
    _trigger_steam_install,
)

if TYPE_CHECKING:
    from pathlib import Path


PKG = "steam_backlog_enforcer.game_install"
ECHO_PKG = "steam_backlog_enforcer._echo"
STEAM_CLIENT_PKG = "steam_backlog_enforcer._steam_client"


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
            patch("steam_backlog_enforcer._steam_state._REAL_STEAMAPPS", real),
            patch("steam_backlog_enforcer._steam_state.STEAMAPPS_PATH", real),
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
            patch("steam_backlog_enforcer._steam_state._REAL_STEAMAPPS", real),
            patch("steam_backlog_enforcer._steam_state.STEAMAPPS_PATH", redirected),
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
            patch("steam_backlog_enforcer._steam_state._REAL_STEAMAPPS", real),
            patch("steam_backlog_enforcer._steam_state.STEAMAPPS_PATH", real),
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
            "steam_backlog_enforcer._steam_client.pwd.getpwnam",
            return_value=mock_pw,
        ):
            assert _get_uid_gid_for_user("alice") == (1001, 1001)

    def test_unknown_user(self) -> None:
        with patch(
            "steam_backlog_enforcer._steam_client.pwd.getpwnam",
            side_effect=KeyError,
        ):
            assert _get_uid_gid_for_user("nobody") == (1000, 1000)


class TestIsGameInstalled:
    """Tests for is_game_installed."""

    def test_installed(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.touch()
        with patch("steam_backlog_enforcer._steam_client.STEAMAPPS_PATH", tmp_path):
            assert is_game_installed(440) is True

    def test_not_installed(self, tmp_path: Path) -> None:
        with patch("steam_backlog_enforcer._steam_client.STEAMAPPS_PATH", tmp_path):
            assert is_game_installed(440) is False


class TestTriggerSteamInstallPrivilegeDrop:
    """Regression tests: never invoke the steam:// handler as root.

    A bare root ``xdg-open steam://install/...`` makes Steam answer with a
    "Cannot run as root user" modal on the user's display.
    """

    _PKG = "steam_backlog_enforcer.game_install"

    def test_root_drops_to_desktop_user(self) -> None:
        with (
            patch(f"{self._PKG}.os.geteuid", return_value=0),
            patch(f"{self._PKG}._get_real_user", return_value="kuhy"),
            patch(f"{self._PKG}.desktop_session_ready", return_value=True),
            patch(f"{self._PKG}.desktop_uid", return_value=1000),
            patch(f"{self._PKG}.subprocess.run") as mock_run,
        ):
            assert _trigger_steam_install(440, "TF2") is True

        argv = mock_run.call_args[0][0]
        assert argv[:4] == ["sudo", "-u", "kuhy", "env"]
        assert argv[-1] == "steam://install/440"

    def test_non_root_does_not_wrap(self) -> None:
        with (
            patch(f"{self._PKG}.os.geteuid", return_value=1000),
            patch(f"{self._PKG}._get_real_user", return_value="kuhy"),
            patch(f"{self._PKG}.subprocess.run") as mock_run,
        ):
            assert _trigger_steam_install(440, "TF2") is True

        assert mock_run.call_args[0][0][0] != "sudo"

    def test_defers_when_session_not_ready(self) -> None:
        """No runtime dir means a Steam launched now loses audio all session."""
        with (
            patch(f"{self._PKG}.os.geteuid", return_value=0),
            patch(f"{self._PKG}._get_real_user", return_value="kuhy"),
            patch(f"{self._PKG}.desktop_session_ready", return_value=False),
            patch(f"{self._PKG}.subprocess.run") as mock_run,
        ):
            assert _trigger_steam_install(440, "TF2") is False

        mock_run.assert_not_called()
