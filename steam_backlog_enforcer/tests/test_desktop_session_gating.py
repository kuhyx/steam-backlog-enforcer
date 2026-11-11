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
from steam_backlog_enforcer.tests._desktop_launch_patches import (
    DESKTOP_ENV_PKG,
    STEAM_PROCESS_PKG,
    fresh_launch_patches,
    launch_patches,
)

ENV_PKG = DESKTOP_ENV_PKG


class TestDesktopSessionReady:
    """Tests for desktop_session_ready."""

    def test_ready_when_runtime_dir_exists(self) -> None:
        """An existing /run/user/<uid> means the session is ready."""
        with patch(f"{ENV_PKG}.Path.is_dir", return_value=True):
            assert desktop_session_ready(1000) is True

    def test_not_ready_when_runtime_dir_missing(self) -> None:
        """A missing runtime dir means the session is not ready."""
        with patch(f"{ENV_PKG}.Path.is_dir", return_value=False):
            assert desktop_session_ready(1000) is False

    def test_runtime_dir_path(self) -> None:
        """The runtime dir is /run/user/<uid>."""
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
        """Steam is not launched while the runtime dir is missing."""
        with (
            launch_patches(
                "_shutdown_steam",
                "_launch_steam_with_debug",
                extra={
                    f"{STEAM_PROCESS_PKG}.os.geteuid": 0,
                    f"{DESKTOP_ENV_PKG}.desktop_uid": 1000,
                },
                _steam_has_debug_port=False,
                steam_is_installed=True,
                _resolve_desktop_user="bob",
                desktop_session_ready=False,
            ) as mocks,
            pytest.raises(DesktopSessionNotReadyError),
        ):
            ensure_steam_debug_port()

        # Neither bounce a working Steam nor start a broken one.
        mocks["_launch_steam_with_debug"].assert_not_called()
        mocks["_shutdown_steam"].assert_not_called()

    def test_launches_when_runtime_dir_present(self) -> None:
        """Steam is launched once the runtime dir exists."""
        with fresh_launch_patches(
            extra={
                f"{STEAM_PROCESS_PKG}.os.geteuid": 0,
                f"{DESKTOP_ENV_PKG}.desktop_uid": 1000,
            },
            steam_is_installed=True,
            _resolve_desktop_user="bob",
            desktop_session_ready=True,
            _is_steam_running=False,
        ) as mocks:
            ensure_steam_debug_port()
        mocks["_launch_steam_with_debug"].assert_called_once()

    def test_non_root_does_not_gate(self) -> None:
        """Run interactively, the ambient session is already the user's."""
        with fresh_launch_patches(
            extra={f"{STEAM_PROCESS_PKG}.os.geteuid": 1000},
            steam_is_installed=True,
            _resolve_desktop_user="bob",
            desktop_session_ready=False,
            _is_steam_running=False,
        ) as mocks:
            ensure_steam_debug_port()
        mocks["_launch_steam_with_debug"].assert_called_once()
