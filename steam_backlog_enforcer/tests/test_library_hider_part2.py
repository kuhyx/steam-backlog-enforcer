"""Tests for library_hider module — part 2 (missing coverage)."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._steam_launch import (
    _resolve_desktop_user,
    steam_is_installed,
)
from steam_backlog_enforcer._steam_process import (
    _SPAWNED,
    _reap_spawned,
    _run_as_user,
)

PKG = "steam_backlog_enforcer.library_hider"
CDP_PKG = "steam_backlog_enforcer._cdp"
STEAM_LAUNCH_PKG = "steam_backlog_enforcer._steam_launch"
STEAM_PROCESS_PKG = "steam_backlog_enforcer._steam_process"
LIBRARY_HIDER_PKG = "steam_backlog_enforcer.library_hider"
ENV_PKG = "steam_backlog_enforcer._desktop_env"


class TestResolveDesktopUser:
    """Tests for _resolve_desktop_user."""

    def test_prefers_steam_enforcer_desktop_user(self) -> None:
        """The systemd unit's explicit var wins over SUDO_USER/USER."""
        with patch.dict(
            os.environ,
            {
                "STEAM_ENFORCER_DESKTOP_USER": "kuhy",
                "SUDO_USER": "someone_else",
                "USER": "root",
            },
        ):
            assert _resolve_desktop_user() == "kuhy"

    def test_falls_back_to_sudo_user(self) -> None:
        """Interactive `sudo` invocations have no explicit var set."""
        env = os.environ.copy()
        env.pop("STEAM_ENFORCER_DESKTOP_USER", None)
        env["SUDO_USER"] = "alice"
        env["USER"] = "root"
        with patch.dict(os.environ, env, clear=True):
            assert _resolve_desktop_user() == "alice"

    def test_falls_back_to_user(self) -> None:
        """A direct, non-sudo invocation has neither var set."""
        env = os.environ.copy()
        env.pop("STEAM_ENFORCER_DESKTOP_USER", None)
        env.pop("SUDO_USER", None)
        env["USER"] = "kuhy"
        with patch.dict(os.environ, env, clear=True):
            assert _resolve_desktop_user() == "kuhy"

    def test_returns_none_when_nothing_set(self) -> None:
        env = os.environ.copy()
        env.pop("STEAM_ENFORCER_DESKTOP_USER", None)
        env.pop("SUDO_USER", None)
        env.pop("USER", None)
        with patch.dict(os.environ, env, clear=True):
            assert _resolve_desktop_user() is None


class TestSteamIsInstalled:
    """Tests for steam_is_installed."""

    def test_true_when_binary_exists(self) -> None:
        with patch("steam_backlog_enforcer._steam_launch.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            assert steam_is_installed() is True

    def test_false_when_binary_missing(self) -> None:
        with patch("steam_backlog_enforcer._steam_launch.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            assert steam_is_installed() is False

    def test_checks_real_binary_not_path_lookup(self) -> None:
        """Must probe the real binary, never a $PATH lookup.

        A launcher wrapper on $PATH keeps `which steam` truthy long after the
        package is uninstalled - which is exactly how a dead Steam went on
        looking installed and got launched ~1000 times.
        """
        with patch("steam_backlog_enforcer._steam_launch.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            steam_is_installed()
        mock_path.assert_called_once_with("/usr/bin/steam")


class TestReapSpawned:
    """Tests for _reap_spawned."""

    def test_drops_exited_processes(self) -> None:
        """An exited launch must be reaped so its name stops showing in /proc.

        This is the zombie that focus-mode read as a live Steam.
        """
        dead = MagicMock()
        dead.poll.return_value = 1
        _SPAWNED[:] = [dead]
        try:
            _reap_spawned()
            assert _SPAWNED == []
        finally:
            _SPAWNED.clear()

    def test_keeps_running_processes(self) -> None:
        """A Steam that is still alive must not be dropped from tracking."""
        alive = MagicMock()
        alive.poll.return_value = None
        _SPAWNED[:] = [alive]
        try:
            _reap_spawned()
            assert [alive] == _SPAWNED
        finally:
            _SPAWNED.clear()


class TestRunAsUser:
    """Tests for _run_as_user."""

    def test_tracks_spawned_process_for_reaping(self) -> None:
        """Every launch must be tracked, or it can never be reaped."""
        _SPAWNED.clear()
        with (
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=1000),
            patch(f"{STEAM_PROCESS_PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "alice")
            try:
                assert [mock_popen.return_value] == _SPAWNED
            finally:
                _SPAWNED.clear()

    def test_non_root_runs_directly(self) -> None:
        with (
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=1000),
            patch(f"{STEAM_PROCESS_PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam", "-shutdown"], "alice")
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd == ["steam", "-shutdown"]

    def test_root_drops_to_user(self) -> None:
        mock_pw = MagicMock()
        mock_pw.pw_uid = 1001
        with (
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=0),
            patch(f"{ENV_PKG}.pwd.getpwnam", return_value=mock_pw),
            patch.dict(
                os.environ,
                {"DISPLAY": ":1", "XAUTHORITY": tempfile.gettempdir() + "/.X"},
            ),
            patch(f"{STEAM_PROCESS_PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam", "-shutdown"], "alice")
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "sudo"
        assert "-u" in cmd
        assert "alice" in cmd

    def test_root_user_key_error(self) -> None:
        with (
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=0),
            patch(f"{ENV_PKG}.pwd.getpwnam", side_effect=KeyError("no user")),
            patch(f"{STEAM_PROCESS_PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "unknownuser")
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        # Falls back to uid 1000
        assert "sudo" in cmd[0]

    def test_root_user_none(self) -> None:
        """When user is None and euid is 0, refuses rather than running as root.

        Running directly here is what put a root Steam — and its "Cannot run
        as root user" modal — on the user's display.
        """
        with (
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=0),
            patch(f"{STEAM_PROCESS_PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], None)
        mock_popen.assert_not_called()

    def test_root_user_is_root(self) -> None:
        """When user is 'root', refuses rather than running as root."""
        with (
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=0),
            patch(f"{STEAM_PROCESS_PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "root")
        mock_popen.assert_not_called()

    def test_root_uses_env_defaults(self) -> None:
        """When DBUS/XAUTHORITY/DISPLAY not in env, uses defaults."""
        mock_pw = MagicMock()
        mock_pw.pw_uid = 1000
        env_copy = os.environ.copy()
        env_copy.pop("DBUS_SESSION_BUS_ADDRESS", None)
        env_copy.pop("XAUTHORITY", None)
        env_copy.pop("DISPLAY", None)
        with (
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=0),
            patch(f"{ENV_PKG}.pwd.getpwnam", return_value=mock_pw),
            patch.dict(os.environ, env_copy, clear=True),
            patch(f"{STEAM_PROCESS_PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "bob")
        cmd = mock_popen.call_args[0][0]
        assert any("DISPLAY=:0" in arg for arg in cmd)
        assert any("/home/bob/.Xauthority" in arg for arg in cmd)
