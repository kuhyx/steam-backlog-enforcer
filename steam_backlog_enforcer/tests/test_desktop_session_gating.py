"""Tests for gating launches on the desktop session being ready.

Split to keep every test file under the 250-line cap.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer._desktop_env import (
    desktop_runtime_dir,
    desktop_session_ready,
)
from steam_backlog_enforcer._steam_errors import DesktopSessionNotReadyError
from steam_backlog_enforcer._steam_launch import ensure_steam_debug_port

PKG = "steam_backlog_enforcer.library_hider"
DESKTOP_ENV_PKG = "steam_backlog_enforcer._desktop_env"
STEAM_LAUNCH_PKG = "steam_backlog_enforcer._steam_launch"
STEAM_PROCESS_PKG = "steam_backlog_enforcer._steam_process"
ENV_PKG = "steam_backlog_enforcer._desktop_env"


def _env_value(args: list[str], name: str) -> str | None:
    """Return the value assigned to *name* in a list of ``VAR=value`` args."""
    prefix = f"{name}="
    for arg in args:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None


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
            patch(
                "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.steam_is_installed",
                return_value=True,
            ),
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=0),
            patch(
                "steam_backlog_enforcer._steam_launch._resolve_desktop_user",
                return_value="bob",
            ),
            patch(f"{DESKTOP_ENV_PKG}.desktop_uid", return_value=1000),
            patch(f"{STEAM_LAUNCH_PKG}.desktop_session_ready", return_value=False),
            patch(
                "steam_backlog_enforcer._steam_launch._shutdown_steam"
            ) as mock_shutdown,
            patch(
                "steam_backlog_enforcer._steam_launch._launch_steam_with_debug"
            ) as mock_launch,
            pytest.raises(DesktopSessionNotReadyError),
        ):
            ensure_steam_debug_port()

        # Neither bounce a working Steam nor start a broken one.
        mock_launch.assert_not_called()
        mock_shutdown.assert_not_called()

    def test_launches_when_runtime_dir_present(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.steam_is_installed",
                return_value=True,
            ),
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=0),
            patch(
                "steam_backlog_enforcer._steam_launch._resolve_desktop_user",
                return_value="bob",
            ),
            patch(f"{DESKTOP_ENV_PKG}.desktop_uid", return_value=1000),
            patch(f"{STEAM_LAUNCH_PKG}.desktop_session_ready", return_value=True),
            patch(
                "steam_backlog_enforcer._steam_launch._is_steam_running",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._launch_steam_with_debug"
            ) as mock_launch,
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_cdp_ready",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_collections_ready",
                return_value=True,
            ),
        ):
            ensure_steam_debug_port()
        mock_launch.assert_called_once()

    def test_non_root_does_not_gate(self) -> None:
        """Run interactively, the ambient session is already the user's."""
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.steam_is_installed",
                return_value=True,
            ),
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=1000),
            patch(
                "steam_backlog_enforcer._steam_launch._resolve_desktop_user",
                return_value="bob",
            ),
            patch(f"{STEAM_LAUNCH_PKG}.desktop_session_ready", return_value=False),
            patch(
                "steam_backlog_enforcer._steam_launch._is_steam_running",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._launch_steam_with_debug"
            ) as mock_launch,
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_cdp_ready",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_collections_ready",
                return_value=True,
            ),
        ):
            ensure_steam_debug_port()
        mock_launch.assert_called_once()
