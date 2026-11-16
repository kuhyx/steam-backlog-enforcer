"""Tests for the X display Steam is launched on, and the env it gets.

A web job (a user unit with no DISPLAY) used to run a bare ``steam`` that died
with "Unable to open X11 display". Every launch now carries the desktop env,
root or not, and no launch is attempted when the display is not up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _desktop_env
from steam_backlog_enforcer._desktop_env import desktop_user_cmd, x_display_error
from steam_backlog_enforcer.tests._desktop_launch_patches import (
    DESKTOP_ENV_PKG,
    env_value,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(name="x_dir")
def _x_socket_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty X socket dir, with DISPLAY unset."""
    monkeypatch.setattr(_desktop_env, "X_SOCKET_DIR", str(tmp_path))
    monkeypatch.delenv("DISPLAY", raising=False)
    return tmp_path


class TestXDisplayError:
    """x_display_error: why Steam has no display to open, or None."""

    def test_default_display_is_up(self, x_dir: Path) -> None:
        """Unset DISPLAY falls back to :0, whose socket exists."""
        (x_dir / "X0").touch()
        assert x_display_error() is None

    def test_default_display_missing_names_it(self, x_dir: Path) -> None:
        """No socket for the default :0: the error names the display."""
        message = x_display_error()
        assert message is not None
        assert ":0" in message
        assert str(x_dir / "X0") in message

    def test_explicit_display_with_screen_suffix(
        self, x_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DISPLAY=:1.0 checks the X1 socket and is named in the error."""
        monkeypatch.setenv("DISPLAY", ":1.0")
        message = x_display_error()
        assert message is not None
        assert ":1.0" in message
        (x_dir / "X1").touch()
        assert x_display_error() is None

    def test_remote_display_is_not_checked(
        self, x_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host-qualified display has no local socket to look for."""
        monkeypatch.setenv("DISPLAY", "localhost:10.0")
        assert x_dir.is_dir()
        assert x_display_error() is None


class TestNonRootGetsTheDesktopEnv:
    """desktop_user_cmd prefixes the session env even without sudo."""

    def _cmd(self, user: str | None = "kuhy") -> list[str]:
        owner = MagicMock(pw_name="kuhy")
        with (
            patch(f"{DESKTOP_ENV_PKG}.os.geteuid", return_value=1234),
            patch(f"{DESKTOP_ENV_PKG}.pwd.getpwuid", return_value=owner),
        ):
            return desktop_user_cmd(["steam", "-silent"], user)

    def test_adds_env_without_sudo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The command runs under ``env`` with DISPLAY and the runtime dir."""
        monkeypatch.delenv("DISPLAY", raising=False)
        cmd = self._cmd()
        assert cmd[0] == "env"
        assert "sudo" not in cmd
        assert cmd[-2:] == ["steam", "-silent"]
        assert env_value(cmd, "DISPLAY") == ":0"
        assert env_value(cmd, "XDG_RUNTIME_DIR") == "/run/user/1234"

    def test_keeps_an_inherited_display(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit DISPLAY in the job's environment still wins."""
        monkeypatch.setenv("DISPLAY", ":7")
        assert env_value(self._cmd(), "DISPLAY") == ":7"

    def test_nobody_to_name_leaves_the_command_alone(self) -> None:
        """No desktop user and no passwd entry for the process: no env prefix."""
        with (
            patch(f"{DESKTOP_ENV_PKG}.os.geteuid", return_value=1234),
            patch(f"{DESKTOP_ENV_PKG}.pwd.getpwuid", side_effect=KeyError),
        ):
            assert desktop_user_cmd(["steam"], None) == ["steam"]

    def test_unresolved_user_is_the_process_owner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no desktop user named, the job's own user is the desktop user."""
        monkeypatch.delenv("XAUTHORITY", raising=False)
        cmd = self._cmd(user=None)
        assert env_value(cmd, "XAUTHORITY") == "/home/kuhy/.Xauthority"
