"""Tests for library_hider module — part 2 (missing coverage)."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.library_hider import (
    _SPAWNED,
    SteamUnavailableError,
    SteamUpdateInProgressError,
    _reap_spawned,
    _resolve_desktop_user,
    _run_as_user,
    hide_other_games,
    restart_steam,
    steam_is_installed,
    try_hide_other_games,
    unhide_all_games,
)

PKG = "steam_backlog_enforcer.library_hider"


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
        with patch(f"{PKG}.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            assert steam_is_installed() is True

    def test_false_when_binary_missing(self) -> None:
        with patch(f"{PKG}.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            assert steam_is_installed() is False

    def test_checks_real_binary_not_path_lookup(self) -> None:
        """Must probe the real binary, never a $PATH lookup.

        A launcher wrapper on $PATH keeps `which steam` truthy long after the
        package is uninstalled - which is exactly how a dead Steam went on
        looking installed and got launched ~1000 times.
        """
        with patch(f"{PKG}.Path") as mock_path:
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
            patch(f"{PKG}.os.geteuid", return_value=1000),
            patch(f"{PKG}.subprocess.Popen") as mock_popen,
        ):
            _run_as_user(["steam"], "alice")
            try:
                assert [mock_popen.return_value] == _SPAWNED
            finally:
                _SPAWNED.clear()

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


class TestHideOtherGames:
    """Tests for hide_other_games."""

    def test_hides(self) -> None:
        with (
            patch(f"{PKG}.ensure_steam_debug_port"),
            patch(
                f"{PKG}._evaluate_js",
                return_value={
                    "result": {"result": {"value": '{"totalHidden": 5}'}},
                },
            ),
            patch(
                f"{PKG}._cdp_result_value",
                return_value='{"totalHidden": 5}',
            ),
        ):
            count = hide_other_games([1, 2, 3], 1)
            assert count == 5

    def test_empty_list(self) -> None:
        with (
            patch(f"{PKG}.ensure_steam_debug_port"),
            patch(
                f"{PKG}._evaluate_js",
                return_value={
                    "result": {"result": {"value": '{"totalHidden": 0}'}},
                },
            ),
            patch(
                f"{PKG}._cdp_result_value",
                return_value='{"totalHidden": 0}',
            ),
        ):
            count = hide_other_games([1], 1)
            assert count == 0

    def test_no_allowed(self) -> None:
        with (
            patch(f"{PKG}.ensure_steam_debug_port"),
            patch(
                f"{PKG}._evaluate_js",
                return_value={
                    "result": {"result": {"value": '{"totalHidden": 2}'}},
                },
            ),
            patch(
                f"{PKG}._cdp_result_value",
                return_value='{"totalHidden": 2}',
            ),
        ):
            count = hide_other_games([1, 2], None)
            assert count == 2


class TestTryHideOtherGames:
    """Tests for the graceful wrapper around hide_other_games.

    Regression guard: an unreachable Steam (or a deferred restart while a game
    update is in flight) used to escape as a traceback out of every
    interactive command that reconciles the library.
    """

    def test_success_returns_count_and_no_reason(self) -> None:
        with patch(f"{PKG}.hide_other_games", return_value=7):
            assert try_hide_other_games([1, 2], 1) == (7, None)

    def test_steam_unavailable_is_reported_not_raised(self) -> None:
        with patch(
            f"{PKG}.hide_other_games",
            side_effect=SteamUnavailableError("Steam is not installed"),
        ):
            hidden, reason = try_hide_other_games([1, 2], 1)
        assert hidden == 0
        assert reason == "Steam is not installed"

    def test_update_in_progress_is_reported_not_raised(self) -> None:
        with patch(
            f"{PKG}.hide_other_games",
            side_effect=SteamUpdateInProgressError("update in progress"),
        ):
            hidden, reason = try_hide_other_games([1, 2], 1)
        assert hidden == 0
        assert reason == "update in progress"


class TestUnhideAllGames:
    """Tests for unhide_all_games."""

    def test_unhides(self) -> None:
        with (
            patch(f"{PKG}.ensure_steam_debug_port"),
            patch(
                f"{PKG}._evaluate_js",
                return_value={"result": {"result": {"value": '{"count": 10}'}}},
            ),
            patch(
                f"{PKG}._cdp_result_value",
                return_value='{"count": 10}',
            ),
        ):
            count = unhide_all_games([1, 2, 3])
            assert count == 10
