"""Tests for failing fast when a launched Steam cannot come up.

A web job once launched Steam with no DISPLAY: the client logged "Unable to
open X11 display" and exited after ~2 s, yet the CDP wait still polled all 45 s
while the job held the global mutating lock. These pin the fast failures: the
launched process died, or there is no X display to launch it on.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._steam_errors import SteamUnavailableError
from steam_backlog_enforcer._steam_launch import (
    _launch_steam_with_debug,
    _wait_for_cdp_ready,
    ensure_steam_debug_port,
)
from steam_backlog_enforcer._steam_process import _run_as_user
from steam_backlog_enforcer.tests._desktop_launch_patches import (
    STEAM_LAUNCH_PKG,
    STEAM_PROCESS_PKG,
    launch_patches,
)

NO_DISPLAY = "No X display for Steam: :0 is not up"


def _proc(exit_code: int | None) -> MagicMock:
    """A launched process whose ``poll()`` reports *exit_code* (None = alive)."""
    proc = MagicMock()
    proc.poll.return_value = exit_code
    return proc


class TestWaitForCdpReadyWatchesTheLaunch:
    """_wait_for_cdp_ready gives up as soon as the launched Steam is gone."""

    def test_dead_launch_fails_on_the_first_poll(self) -> None:
        """A process that exited with no Steam left stops the wait at once."""
        with (
            patch(f"{STEAM_LAUNCH_PKG}._get_shared_js_ws_url", return_value=None),
            patch(f"{STEAM_LAUNCH_PKG}._is_steam_running", return_value=False),
            patch(f"{STEAM_LAUNCH_PKG}.time.sleep") as sleep,
            pytest.raises(
                SteamUnavailableError,
                match=r"Steam exited during startup \(exit code 1\)",
            ),
        ):
            _wait_for_cdp_ready(_proc(1))
        assert sleep.call_count <= 1

    def test_exited_launcher_with_a_live_client_keeps_waiting(self) -> None:
        """A launcher that handed off to a running client is not a failure.

        ``steam`` may fork the real client and exit; the port then opens a
        few seconds later, so exit alone must not abort the wait.
        """
        with (
            patch(
                f"{STEAM_LAUNCH_PKG}._get_shared_js_ws_url",
                side_effect=[None, None, "ws://steam"],
            ),
            patch(f"{STEAM_LAUNCH_PKG}._is_steam_running", return_value=True),
            patch(f"{STEAM_LAUNCH_PKG}.time.sleep") as sleep,
        ):
            assert _wait_for_cdp_ready(_proc(0)) is True
        assert sleep.call_count == 2

    def test_alive_launch_times_out_as_before(self) -> None:
        """A process that keeps running but never opens the port times out."""
        with (
            patch(f"{STEAM_LAUNCH_PKG}._get_shared_js_ws_url", return_value=None),
            patch(f"{STEAM_LAUNCH_PKG}._STEAM_STARTUP_WAIT", 3),
            patch(f"{STEAM_LAUNCH_PKG}.time.sleep") as sleep,
        ):
            assert _wait_for_cdp_ready(_proc(None)) is False
        assert sleep.call_count == 3


class TestEnsureFailsFast:
    """ensure_steam_debug_port stops early for a dead launch or no display."""

    def test_dead_launch_raises_without_waiting_for_collections(self) -> None:
        """The whole call fails within a poll or two, naming the exit code."""
        with (
            launch_patches(
                "_wait_for_collections_ready",
                _launch_steam_with_debug=_proc(1),
                _steam_has_debug_port=False,
                _get_shared_js_ws_url=None,
                _is_steam_running=False,
                steam_is_installed=True,
                x_display_error=None,
            ) as mocks,
            patch(f"{STEAM_LAUNCH_PKG}.time.sleep") as sleep,
            pytest.raises(SteamUnavailableError, match=r"exited during startup"),
        ):
            ensure_steam_debug_port()
        assert sleep.call_count <= 1
        mocks["_wait_for_collections_ready"].assert_not_called()

    def test_no_display_refuses_before_any_shutdown_or_launch(self) -> None:
        """No X display: Steam is neither shut down nor started."""
        with (
            launch_patches(
                "_launch_steam_with_debug",
                "_shutdown_steam",
                _steam_has_debug_port=False,
                _is_steam_running=True,
                steam_is_installed=True,
                x_display_error=NO_DISPLAY,
            ) as mocks,
            pytest.raises(SteamUnavailableError, match="No X display"),
        ):
            ensure_steam_debug_port()
        mocks["_launch_steam_with_debug"].assert_not_called()
        mocks["_shutdown_steam"].assert_not_called()


class TestLaunchHandsBackTheProcess:
    """The launched process reaches the wait instead of being discarded."""

    def test_launch_returns_the_spawned_handle(self) -> None:
        """_launch_steam_with_debug returns what _run_as_user spawned."""
        spawned = _proc(None)
        with patch(f"{STEAM_LAUNCH_PKG}._run_as_user", return_value=spawned):
            assert _launch_steam_with_debug() is spawned

    def test_run_as_user_returns_the_popen(self) -> None:
        """_run_as_user hands back the Popen it started."""
        with (
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=1000),
            patch(f"{STEAM_PROCESS_PKG}.subprocess.Popen") as popen,
        ):
            assert _run_as_user(["steam"], "bob") is popen.return_value

    def test_run_as_user_refusal_returns_none(self) -> None:
        """Root with no desktop user starts nothing and returns None."""
        with (
            patch(f"{STEAM_PROCESS_PKG}.os.geteuid", return_value=0),
            patch(f"{STEAM_PROCESS_PKG}.subprocess.Popen") as popen,
        ):
            assert _run_as_user(["steam"], None) is None
        popen.assert_not_called()
