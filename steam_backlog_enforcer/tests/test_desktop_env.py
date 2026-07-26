"""Tests for _desktop_env — the env allowlist for desktop-session launches."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._desktop_env import (
    desktop_env_args,
    desktop_runtime_dir,
    desktop_session_ready,
)
from steam_backlog_enforcer.library_hider import (
    DesktopSessionNotReadyError,
    _desktop_uid,
    _run_as_user,
    ensure_steam_debug_port,
)

PKG = "steam_backlog_enforcer.library_hider"
ENV_PKG = "steam_backlog_enforcer._desktop_env"


def _env_value(args: list[str], name: str) -> str | None:
    """Return the value assigned to *name* in a list of ``VAR=value`` args."""
    prefix = f"{name}="
    for arg in args:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None


class TestDesktopEnvArgs:
    """Tests for desktop_env_args."""

    def test_exports_xdg_runtime_dir_for_uid(self) -> None:
        """XDG_RUNTIME_DIR must be present — Wine needs it to find PulseAudio.

        Without it winepulse.drv cannot reach $XDG_RUNTIME_DIR/pulse/native,
        Wine silently falls back to winealsa.drv, and Proton games get raw
        ALSA devices instead of the session sink.
        """
        args = desktop_env_args("bob", 1000)
        assert _env_value(args, "XDG_RUNTIME_DIR") == "/run/user/1000"

    def test_runtime_dir_follows_uid(self) -> None:
        """The path is derived from the target uid, not hardcoded."""
        args = desktop_env_args("bob", 1234)
        assert _env_value(args, "XDG_RUNTIME_DIR") == "/run/user/1234"

    def test_root_runtime_dir_does_not_leak(self) -> None:
        """Root's own XDG_RUNTIME_DIR must never reach the desktop child.

        The enforcer runs as root under systemd. Reading the ambient value
        would hand the child /run/user/0, which it cannot use.
        """
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/0"}):
            args = desktop_env_args("bob", 1000)
        assert _env_value(args, "XDG_RUNTIME_DIR") == "/run/user/1000"

    def test_dbus_address_defaults_to_uid_path(self) -> None:
        """DBUS falls back to the uid-derived socket when unset."""
        env_copy = os.environ.copy()
        env_copy.pop("DBUS_SESSION_BUS_ADDRESS", None)
        with patch.dict(os.environ, env_copy, clear=True):
            args = desktop_env_args("bob", 1000)
        expected = "unix:path=/run/user/1000/bus"
        assert _env_value(args, "DBUS_SESSION_BUS_ADDRESS") == expected

    def test_dbus_address_prefers_ambient_value(self) -> None:
        """An explicit DBUS address in the environment still wins."""
        with patch.dict(
            os.environ,
            {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/custom/bus"},
        ):
            args = desktop_env_args("bob", 1000)
        assert _env_value(args, "DBUS_SESSION_BUS_ADDRESS") == "unix:path=/custom/bus"

    def test_xauthority_defaults_to_user_home(self) -> None:
        """XAUTHORITY falls back to the target user's home."""
        env_copy = os.environ.copy()
        env_copy.pop("XAUTHORITY", None)
        with patch.dict(os.environ, env_copy, clear=True):
            args = desktop_env_args("bob", 1000)
        assert _env_value(args, "XAUTHORITY") == "/home/bob/.Xauthority"

    def test_xauthority_prefers_ambient_value(self) -> None:
        """An explicit XAUTHORITY in the environment still wins."""
        with patch.dict(os.environ, {"XAUTHORITY": "/custom/xauth"}):
            args = desktop_env_args("bob", 1000)
        assert _env_value(args, "XAUTHORITY") == "/custom/xauth"

    def test_display_defaults_to_zero(self) -> None:
        """DISPLAY falls back to :0."""
        env_copy = os.environ.copy()
        env_copy.pop("DISPLAY", None)
        with patch.dict(os.environ, env_copy, clear=True):
            args = desktop_env_args("bob", 1000)
        assert _env_value(args, "DISPLAY") == ":0"

    def test_display_prefers_ambient_value(self) -> None:
        """An explicit DISPLAY in the environment still wins."""
        with patch.dict(os.environ, {"DISPLAY": ":1"}):
            args = desktop_env_args("bob", 1000)
        assert _env_value(args, "DISPLAY") == ":1"


class TestRunAsUserUsesSharedBuilder:
    """The privileged launch path must go through desktop_env_args."""

    def test_launch_command_carries_runtime_dir(self) -> None:
        """A root-launched Steam gets XDG_RUNTIME_DIR for the desktop uid.

        This is the regression guard for the KCD2 startup crash: the enforcer
        launched Steam without XDG_RUNTIME_DIR, so every Proton child fell
        back to raw ALSA and the game died in its Bink startup video.
        """
        mock_pw = MagicMock()
        mock_pw.pw_uid = 1000
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}.pwd.getpwnam", return_value=mock_pw),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "bob")
        cmd = mock_popen.call_args[0][0]
        assert cmd[:4] == ["sudo", "-u", "bob", "env"]
        assert "XDG_RUNTIME_DIR=/run/user/1000" in cmd
        assert cmd[-1] == "steam"

    def test_unknown_user_falls_back_to_uid_1000(self) -> None:
        """An unresolvable user still yields a usable runtime dir."""
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}.pwd.getpwnam", side_effect=KeyError),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "ghost")
        cmd = mock_popen.call_args[0][0]
        assert "XDG_RUNTIME_DIR=/run/user/1000" in cmd


class TestDesktopUid:
    """Tests for _desktop_uid."""

    def test_resolves_known_user(self) -> None:
        mock_pw = MagicMock()
        mock_pw.pw_uid = 1234
        with patch(f"{PKG}.pwd.getpwnam", return_value=mock_pw):
            assert _desktop_uid("bob") == 1234

    def test_unknown_user_falls_back(self) -> None:
        with patch(f"{PKG}.pwd.getpwnam", side_effect=KeyError):
            assert _desktop_uid("ghost") == 1000

    def test_no_user_falls_back(self) -> None:
        assert _desktop_uid(None) == 1000


class TestDesktopSessionReady:
    """Tests for desktop_session_ready."""

    def test_ready_when_runtime_dir_exists(self) -> None:
        with patch(f"{ENV_PKG}.Path.is_dir", return_value=True):
            assert desktop_session_ready(1000) is True

    def test_not_ready_when_runtime_dir_missing(self) -> None:
        with patch(f"{ENV_PKG}.Path.is_dir", return_value=False):
            assert desktop_session_ready(1000) is False

    def test_runtime_dir_path(self) -> None:
        assert desktop_runtime_dir(1000) == "/run/user/1000"


class TestLaunchDefersUntilSessionReady:
    """The enforcer must not launch Steam into a session that does not exist.

    Regression guard for the boot race: the enforcer is a system service
    ordered only after the network, and on a measured boot it started 54ms
    before user-runtime-dir@1000. A Steam launched in that window comes up
    with a runtime dir that is not there, silently falls back to winealsa,
    and stays audio-broken until something restarts it.
    """

    def test_defers_when_runtime_dir_missing(self) -> None:
        with (
            patch(f"{PKG}._steam_has_debug_port", return_value=False),
            patch(f"{PKG}.steam_is_installed", return_value=True),
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._resolve_desktop_user", return_value="bob"),
            patch(f"{PKG}._desktop_uid", return_value=1000),
            patch(f"{PKG}.desktop_session_ready", return_value=False),
            patch(f"{PKG}._shutdown_steam") as mock_shutdown,
            patch(f"{PKG}._launch_steam_with_debug") as mock_launch,
            pytest.raises(DesktopSessionNotReadyError),
        ):
            ensure_steam_debug_port()

        # Neither bounce a working Steam nor start a broken one.
        mock_launch.assert_not_called()
        mock_shutdown.assert_not_called()

    def test_launches_when_runtime_dir_present(self) -> None:
        with (
            patch(f"{PKG}._steam_has_debug_port", return_value=False),
            patch(f"{PKG}.steam_is_installed", return_value=True),
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._resolve_desktop_user", return_value="bob"),
            patch(f"{PKG}._desktop_uid", return_value=1000),
            patch(f"{PKG}.desktop_session_ready", return_value=True),
            patch(f"{PKG}._is_steam_running", return_value=False),
            patch(f"{PKG}._launch_steam_with_debug") as mock_launch,
            patch(f"{PKG}._wait_for_cdp_ready", return_value=True),
            patch(f"{PKG}._wait_for_collections_ready", return_value=True),
        ):
            ensure_steam_debug_port()
        mock_launch.assert_called_once()

    def test_non_root_does_not_gate(self) -> None:
        """Run interactively, the ambient session is already the user's."""
        with (
            patch(f"{PKG}._steam_has_debug_port", return_value=False),
            patch(f"{PKG}.steam_is_installed", return_value=True),
            patch(f"{PKG}.os.geteuid", return_value=1000),
            patch(f"{PKG}._resolve_desktop_user", return_value="bob"),
            patch(f"{PKG}.desktop_session_ready", return_value=False),
            patch(f"{PKG}._is_steam_running", return_value=False),
            patch(f"{PKG}._launch_steam_with_debug") as mock_launch,
            patch(f"{PKG}._wait_for_cdp_ready", return_value=True),
            patch(f"{PKG}._wait_for_collections_ready", return_value=True),
        ):
            ensure_steam_debug_port()
        mock_launch.assert_called_once()
