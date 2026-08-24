"""Tests for the desktop privilege-drop builder.

Split from test_desktop_env.py to keep both files under the 250-line cap.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from steam_backlog_enforcer._desktop_env import (
    desktop_uid,
    desktop_user_cmd,
    resolve_desktop_user,
)

ENV_PKG = "steam_backlog_enforcer._desktop_env"


def _env_value(args: list[str], name: str) -> str | None:
    """Return the value assigned to *name* in a list of ``VAR=value`` args."""
    prefix = f"{name}="
    for arg in args:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None


class TestResolveDesktopUser:
    """Tests for resolve_desktop_user's precedence."""

    def test_prefers_enforcer_var(self) -> None:
        """The systemd unit's variable wins: it is the only one systemd sets."""
        with patch.dict(
            os.environ,
            {
                "STEAM_ENFORCER_DESKTOP_USER": "kuhy",
                "SUDO_USER": "alice",
                "USER": "bob",
            },
        ):
            assert resolve_desktop_user() == "kuhy"

    def test_falls_back_to_sudo_user(self) -> None:
        env = {
            k: v for k, v in os.environ.items() if k != "STEAM_ENFORCER_DESKTOP_USER"
        }
        env.update({"SUDO_USER": "alice", "USER": "bob"})
        with patch.dict(os.environ, env, clear=True):
            assert resolve_desktop_user() == "alice"

    def test_falls_back_to_user(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("STEAM_ENFORCER_DESKTOP_USER", "SUDO_USER")
        }
        env["USER"] = "bob"
        with patch.dict(os.environ, env, clear=True):
            assert resolve_desktop_user() == "bob"

    def test_returns_none_when_unset(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("STEAM_ENFORCER_DESKTOP_USER", "SUDO_USER", "USER")
        }
        with patch.dict(os.environ, env, clear=True):
            assert resolve_desktop_user() is None


class TestDesktopUserCmd:
    """Tests for desktop_user_cmd — all four branches."""

    def test_non_root_returns_cmd_unchanged(self) -> None:
        with patch(f"{ENV_PKG}.os.geteuid", return_value=1000):
            assert desktop_user_cmd(["steam"], "kuhy") == ["steam"]

    def test_root_with_user_wraps_in_sudo(self) -> None:
        with (
            patch(f"{ENV_PKG}.os.geteuid", return_value=0),
            patch(f"{ENV_PKG}.desktop_uid", return_value=1000),
        ):
            result = desktop_user_cmd(["steam", "-silent"], "kuhy")
        assert result[:4] == ["sudo", "-u", "kuhy", "env"]
        assert result[-2:] == ["steam", "-silent"]
        assert _env_value(result, "XDG_RUNTIME_DIR") == "/run/user/1000"

    def test_root_without_user_returns_cmd_unchanged(self) -> None:
        """Callers must gate on this: bare argv as root is what the guard exists for."""
        with patch(f"{ENV_PKG}.os.geteuid", return_value=0):
            assert desktop_user_cmd(["steam"], None) == ["steam"]

    def test_root_with_root_user_returns_cmd_unchanged(self) -> None:
        with patch(f"{ENV_PKG}.os.geteuid", return_value=0):
            assert desktop_user_cmd(["steam"], "root") == ["steam"]


class TestDesktopUid:
    """Tests for desktop_uid's lookup and fallbacks."""

    def test_known_user(self) -> None:
        with patch(f"{ENV_PKG}.pwd.getpwnam") as mock_getpwnam:
            mock_getpwnam.return_value.pw_uid = 1234
            assert desktop_uid("kuhy") == 1234

    def test_unknown_user_falls_back(self) -> None:
        """An unknown name must not raise — the enforce loop would die."""
        with patch(f"{ENV_PKG}.pwd.getpwnam", side_effect=KeyError):
            assert desktop_uid("nosuchuser") == 1000

    def test_none_falls_back(self) -> None:
        assert desktop_uid(None) == 1000
