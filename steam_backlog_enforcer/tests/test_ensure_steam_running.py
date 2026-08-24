"""Tests for _ensure_steam_running and the steam:// privilege drop.

Split from test_game_install.py to keep both files under the 250-line cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._steam_client import _ensure_steam_running

if TYPE_CHECKING:
    from collections.abc import Iterator

PKG = "steam_backlog_enforcer._steam_client"


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
            "steam_backlog_enforcer._steam_client.subprocess.run",
            return_value=mock_result,
        ):
            _ensure_steam_running()

    def test_not_running_starts_as_non_root(self) -> None:
        mock_result = MagicMock(returncode=1)
        with (
            patch(
                "steam_backlog_enforcer._steam_client.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "steam_backlog_enforcer._steam_client.subprocess.Popen"
            ) as mock_popen,
            patch(
                "steam_backlog_enforcer._steam_client.os.geteuid",
                return_value=1000,
            ),
            patch("steam_backlog_enforcer._steam_client.time.sleep"),
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
                "steam_backlog_enforcer._steam_client.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "steam_backlog_enforcer._steam_client.subprocess.Popen"
            ) as mock_popen,
            patch(
                "steam_backlog_enforcer._steam_client.os.geteuid",
                return_value=0,
            ),
            patch(
                "steam_backlog_enforcer._steam_client._get_real_user",
                return_value="alice",
            ),
            patch(
                "steam_backlog_enforcer._steam_client._get_uid_gid_for_user",
                return_value=(1000, 1000),
            ),
            patch(
                "steam_backlog_enforcer._steam_client.desktop_session_ready",
                return_value=True,
            ),
            patch("steam_backlog_enforcer._steam_client.time.sleep"),
        ):
            _ensure_steam_running()
            mock_popen.assert_called_once()

        # Assert the env vector, not just that a launch happened: dropping
        # XDG_RUNTIME_DIR here is silent, and cost a Proton game its audio
        # backend (winepulse -> winealsa) and a crash on startup.
        cmd = mock_popen.call_args[0][0]
        assert cmd[:4] == ["sudo", "-u", "alice", "env"]
        assert "XDG_RUNTIME_DIR=/run/user/1000" in cmd

    def test_defers_when_runtime_dir_missing(self) -> None:
        """Do not start Steam before the desktop session's runtime dir exists.

        Launching in that window yields a Steam whose Wine children cannot
        find PulseAudio, and it stays that way for the whole session. The
        enforce loop retries every 3s, so deferring is nearly free.
        """
        mock_result = MagicMock(returncode=1)
        with (
            patch(
                "steam_backlog_enforcer._steam_client.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "steam_backlog_enforcer._steam_client.subprocess.Popen"
            ) as mock_popen,
            patch(
                "steam_backlog_enforcer._steam_client.os.geteuid",
                return_value=0,
            ),
            patch(
                "steam_backlog_enforcer._steam_client._get_real_user",
                return_value="alice",
            ),
            patch(
                "steam_backlog_enforcer._steam_client._get_uid_gid_for_user",
                return_value=(1000, 1000),
            ),
            patch(
                "steam_backlog_enforcer._steam_client.desktop_session_ready",
                return_value=False,
            ),
            patch("steam_backlog_enforcer._steam_client.time.sleep") as mock_sleep,
        ):
            _ensure_steam_running()

        mock_popen.assert_not_called()
        mock_sleep.assert_not_called()

    def test_pgrep_not_found(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_client.subprocess.run",
                side_effect=FileNotFoundError,
            ),
            patch("steam_backlog_enforcer._steam_client.subprocess.Popen"),
            patch(
                "steam_backlog_enforcer._steam_client.os.geteuid",
                return_value=1000,
            ),
            patch("steam_backlog_enforcer._steam_client.time.sleep"),
        ):
            _ensure_steam_running()

    def test_steam_executable_not_found(self) -> None:
        mock_result = MagicMock(returncode=1)
        with (
            patch(
                "steam_backlog_enforcer._steam_client.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "steam_backlog_enforcer._steam_client.subprocess.Popen",
                side_effect=FileNotFoundError,
            ),
            patch(
                "steam_backlog_enforcer._steam_client.os.geteuid",
                return_value=1000,
            ),
        ):
            _ensure_steam_running()
