"""Tests for the guards around a fast install.

Covers the /proc scan and launch guard in _steam_restart_guard, the
fully-installed predicate and target-app exclusion in _steam_state, and every
place that must keep Steam closed or defer while steam-game-installer runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _steam_state
from steam_backlog_enforcer._enforce_steps import _reinstall_missing_allowed
from steam_backlog_enforcer._steam_client import _ensure_steam_running
from steam_backlog_enforcer._steam_errors import (
    FastInstallInProgressError,
    SteamUnavailableError,
)
from steam_backlog_enforcer._steam_launch import ensure_steam_debug_port, restart_steam

# Bound at import, before the autouse guard replaces the module attribute, so
# the real /proc scan is what gets tested here.
from steam_backlog_enforcer._steam_restart_guard import (
    assert_no_fast_install,
    fast_install_running,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.game_install import install_game

if TYPE_CHECKING:
    from pathlib import Path

GUARD = "steam_backlog_enforcer._steam_restart_guard"
GI = "steam_backlog_enforcer.game_install"
LAUNCH = "steam_backlog_enforcer._steam_launch"


def _manifest(app_id: int, flags: int, *, to_download: int = 0) -> None:
    path = _steam_state.STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    path.write_text(
        f'"AppState"\n{{\n\t"StateFlags"\t\t"{flags}"\n'
        f'\t"BytesToDownload"\t\t"{to_download}"\n\t"BytesDownloaded"\t\t"0"\n}}\n'
    )


class TestFastInstallRunning:
    """The scan matches the wrapper and the module, nothing else."""

    def _proc(self, tmp_path: Path, cmdlines: dict[str, bytes | None]) -> Path:
        proc = tmp_path / "proc"
        for pid, cmdline in cmdlines.items():
            (proc / pid).mkdir(parents=True)
            if cmdline is not None:
                (proc / pid / "cmdline").write_bytes(cmdline)
        return proc

    @pytest.mark.parametrize(
        "cmdline",
        [
            b"bash\0/home/u/src/steam-game-installer/run.sh\0--appid\0001",
            b"python\0-m\0steam_installer.cli\0--appid\0001",
        ],
    )
    def test_detects_installer(self, tmp_path: Path, cmdline: bytes) -> None:
        proc = self._proc(tmp_path, {"self": b"", "10": None, "11": cmdline})
        with patch(f"{GUARD}.Path", return_value=proc):
            assert fast_install_running() is True

    def test_nothing_running(self, tmp_path: Path) -> None:
        proc = self._proc(tmp_path, {"self": b"", "10": None, "11": b"steam\0-silent"})
        with patch(f"{GUARD}.Path", return_value=proc):
            assert fast_install_running() is False

    def test_assert_raises_while_running(self) -> None:
        with (
            patch(f"{GUARD}.fast_install_running", return_value=True),
            pytest.raises(FastInstallInProgressError),
        ):
            assert_no_fast_install()

    def test_assert_passes_when_idle(self) -> None:
        assert_no_fast_install()

    def test_error_degrades_like_other_steam_errors(self) -> None:
        assert issubclass(FastInstallInProgressError, SteamUnavailableError)


class TestFullyInstalled:
    """Only a finished, settled manifest counts as fully installed."""

    def test_missing(self) -> None:
        assert _steam_state.is_game_fully_installed(1) is False

    def test_installed(self) -> None:
        _manifest(1, 4)
        assert _steam_state.is_game_fully_installed(1) is True

    def test_steam_still_downloading(self) -> None:
        _manifest(1, 1042, to_download=10)
        assert _steam_state.is_game_fully_installed(1) is False

    def test_flag_set_but_bytes_in_flight(self) -> None:
        _manifest(1, 1044, to_download=10)
        assert _steam_state.is_game_fully_installed(1) is False

    def test_no_state_flags(self) -> None:
        path = _steam_state.STEAMAPPS_PATH / "appmanifest_1.acf"
        path.write_text('"AppState"\n{\n}\n')
        assert _steam_state.is_game_fully_installed(1) is False

    def test_update_check_can_exclude_the_target(self) -> None:
        _manifest(7, 1026, to_download=10)
        assert _steam_state.steam_update_in_progress() is True
        assert _steam_state.steam_update_in_progress(exclude_app_id=7) is False


class TestInstallGameFastPath:
    """install_game prefers the installer and never reopens Steam under it."""

    def test_own_run_in_progress(self) -> None:
        with (
            patch(f"{GI}.fast_install_running", return_value=True),
            patch(f"{GI}.is_fast_installing", return_value=True),
            patch(f"{GI}.fast_install") as fast,
        ):
            assert install_game(1, "G", "sid", use_steam_protocol=True) is True
        fast.assert_not_called()

    def test_other_run_defers(self) -> None:
        with (
            patch(f"{GI}.fast_install_running", return_value=True),
            patch(f"{GI}.is_fast_installing", return_value=False),
            patch(f"{GI}._trigger_steam_install") as trigger,
        ):
            assert install_game(1, "G", "sid", use_steam_protocol=True) is False
        trigger.assert_not_called()

    def test_fast_install_wins(self) -> None:
        with (
            patch(f"{GI}.fast_install", return_value=True),
            patch(f"{GI}._trigger_steam_install") as trigger,
        ):
            assert install_game(1, "G", "sid", use_steam_protocol=True) is True
        trigger.assert_not_called()

    def test_steams_own_download_is_left_running(self) -> None:
        _manifest(1, 1026, to_download=10)
        before = (_steam_state.STEAMAPPS_PATH / "appmanifest_1.acf").read_text()
        with (
            patch(f"{GI}.fast_install", return_value=False),
            patch(f"{GI}._trigger_steam_install") as trigger,
        ):
            assert install_game(1, "G", "sid", use_steam_protocol=True) is True
        trigger.assert_not_called()
        after = (_steam_state.STEAMAPPS_PATH / "appmanifest_1.acf").read_text()
        assert after == before


class TestSteamStaysClosed:
    """Every Steam start path defers to a live installer."""

    def test_ensure_steam_running(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_client.steam_is_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._steam_client.fast_install_running",
                return_value=True,
            ),
            patch("steam_backlog_enforcer._steam_client.spawn_detached") as spawn,
        ):
            _ensure_steam_running()
        spawn.assert_not_called()

    def test_debug_port(self) -> None:
        with (
            patch(f"{GUARD}.fast_install_running", return_value=True),
            patch(f"{LAUNCH}._launch_steam_with_debug") as launch,
            pytest.raises(FastInstallInProgressError),
        ):
            ensure_steam_debug_port()
        launch.assert_not_called()

    def test_restart(self) -> None:
        with (
            patch(f"{LAUNCH}.game_is_running", return_value=False),
            patch(f"{LAUNCH}.steam_update_in_progress", return_value=False),
            patch(f"{LAUNCH}.fast_install_running", return_value=True),
            patch(f"{LAUNCH}._shutdown_steam") as shutdown,
        ):
            restart_steam()
        shutdown.assert_not_called()


class TestReinstallPollsRuns:
    """The loop reaps detached runs even when no game is missing."""

    def test_polls_every_pass(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._enforce_steps.steam_library_ready",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._enforce_steps.allowed_games", return_value=[]
            ),
            patch("steam_backlog_enforcer._enforce_steps.poll_fast_installs") as poll,
        ):
            _reinstall_missing_allowed(Config(), MagicMock(spec=State))
        poll.assert_called_once()
