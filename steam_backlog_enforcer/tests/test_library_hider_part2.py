"""Tests for library_hider module — part 2 (missing coverage)."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

from python_pkg.steam_backlog_enforcer.library_hider import (
    _run_as_user,
    restart_steam,
)

PKG = "python_pkg.steam_backlog_enforcer.library_hider"


class TestRunAsUser:
    """Tests for _run_as_user."""

    def test_non_root_runs_directly(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=1000),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam", "-shutdown"], "alice")
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd == ["steam", "-shutdown"]

    def test_root_drops_to_user(self) -> None:
        mock_pw = MagicMock()
        mock_pw.pw_uid = 1001
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}.pwd.getpwnam", return_value=mock_pw),
            patch.dict(
                os.environ,
                {"DISPLAY": ":1", "XAUTHORITY": tempfile.gettempdir() + "/.X"},
            ),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam", "-shutdown"], "alice")
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "sudo"
        assert "-u" in cmd
        assert "alice" in cmd

    def test_root_user_key_error(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}.pwd.getpwnam", side_effect=KeyError("no user")),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "unknownuser")
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        # Falls back to uid 1000
        assert "sudo" in cmd[0]

    def test_root_user_none(self) -> None:
        """When user is None and euid is 0, runs directly."""
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], None)
        cmd = mock_popen.call_args[0][0]
        assert cmd == ["steam"]

    def test_root_user_is_root(self) -> None:
        """When user is 'root', runs directly."""
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "root")
        cmd = mock_popen.call_args[0][0]
        assert cmd == ["steam"]

    def test_root_uses_env_defaults(self) -> None:
        """When DBUS/XAUTHORITY/DISPLAY not in env, uses defaults."""
        mock_pw = MagicMock()
        mock_pw.pw_uid = 1000
        env_copy = os.environ.copy()
        env_copy.pop("DBUS_SESSION_BUS_ADDRESS", None)
        env_copy.pop("XAUTHORITY", None)
        env_copy.pop("DISPLAY", None)
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}.pwd.getpwnam", return_value=mock_pw),
            patch.dict(os.environ, env_copy, clear=True),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "bob")
        cmd = mock_popen.call_args[0][0]
        assert any("DISPLAY=:0" in arg for arg in cmd)
        assert any("/home/bob/.Xauthority" in arg for arg in cmd)


class TestRestartSteam:
    """Tests for restart_steam."""

    def test_cdp_ready(self) -> None:
        with (
            patch(f"{PKG}._shutdown_steam"),
            patch(f"{PKG}._launch_steam_with_debug"),
            patch(f"{PKG}._wait_for_cdp_ready", return_value=True),
        ):
            restart_steam()

    def test_cdp_not_ready(self) -> None:
        with (
            patch(f"{PKG}._shutdown_steam"),
            patch(f"{PKG}._launch_steam_with_debug"),
            patch(f"{PKG}._wait_for_cdp_ready", return_value=False),
        ):
            restart_steam()
