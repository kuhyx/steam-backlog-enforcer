"""Tests for _fast_install's run lifecycle: spawn, poll, and fast_install.

The pure helpers live in test_fast_install_helpers.py to keep both files under
the 250-line cap. Every subprocess here is a mock (see _no_subprocess.py).
"""

from __future__ import annotations

import os
import signal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _fast_install, config

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer._fast_install"


def _run(app_id: int, returncode: int | None, log_path: Path) -> MagicMock:
    """Register a fake detached run whose poll() answers *returncode*."""
    proc = MagicMock(pid=4321)
    proc.poll.return_value = returncode
    _fast_install._RUNS.append(_fast_install._DetachedRun(app_id, proc, log_path))
    return proc


class TestPollFastInstalls:
    """Detached runs are reaped, failures remembered, stalls interrupted."""

    def test_success_is_reaped(self, tmp_path: Path) -> None:
        _run(1, 0, tmp_path / "log")
        _fast_install.poll_fast_installs()
        assert _fast_install._RUNS == []
        assert set() == _fast_install._FAILED

    def test_failure_is_remembered(self, tmp_path: Path) -> None:
        _run(2, 3, tmp_path / "log")
        _fast_install.poll_fast_installs()
        assert _fast_install._RUNS == []
        assert {2} == _fast_install._FAILED

    def test_live_and_chatty_is_left_alone(self, tmp_path: Path) -> None:
        log = tmp_path / "log"
        log.write_text("progress\n")
        _run(3, None, log)
        with patch(f"{PKG}.os.killpg") as killpg:
            _fast_install.poll_fast_installs()
        killpg.assert_not_called()
        assert _fast_install.is_fast_installing(3)

    def test_live_without_log_is_left_alone(self, tmp_path: Path) -> None:
        _run(4, None, tmp_path / "missing.log")
        with patch(f"{PKG}.os.killpg") as killpg:
            _fast_install.poll_fast_installs()
        killpg.assert_not_called()

    def test_stalled_run_gets_sigint(self, tmp_path: Path) -> None:
        log = tmp_path / "log"
        log.write_text("Enter account password: ")
        old = log.stat().st_mtime - _fast_install.STALL_SECONDS - 60
        os.utime(log, (old, old))
        _run(5, None, log)
        with patch(f"{PKG}.os.killpg") as killpg:
            _fast_install.poll_fast_installs()
        # SIGINT so the installer's `finally` restarts Steam; kept tracked
        # until it actually exits.
        killpg.assert_called_once_with(4321, signal.SIGINT)
        assert _fast_install.is_fast_installing(5)


class TestSpawnDetached:
    """The daemon's spawn: own session, no stdin, output to the log."""

    def test_as_user_spawns_directly(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=1000),
            patch(f"{PKG}.subprocess.Popen") as popen,
        ):
            _fast_install._spawn_detached(["run.sh"], 9)
        args, kwargs = popen.call_args
        assert args[0] == ["run.sh"]
        assert kwargs["stdin"] == _fast_install.subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        run = _fast_install._RUNS[0]
        assert run.app_id == 9
        assert run.log_path == config.CONFIG_DIR / "fast_install.log"
        assert run.log_path.exists()

    def test_as_root_escapes_the_service_cgroup(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}.shutil.which", return_value="/usr/bin/systemd-run"),
            patch(f"{PKG}.subprocess.Popen") as popen,
        ):
            _fast_install._spawn_detached(["run.sh"], 9)
        assert popen.call_args.args[0] == [
            "systemd-run",
            "--scope",
            "--quiet",
            "--collect",
            "run.sh",
        ]

    def test_as_root_without_systemd_run(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}.shutil.which", return_value=None),
            patch(f"{PKG}.subprocess.Popen") as popen,
        ):
            _fast_install._spawn_detached(["run.sh"], 9)
        assert popen.call_args.args[0] == ["run.sh"]


class TestFastInstall:
    """fast_install picks a mode, or tells the caller to fall back."""

    def _ready(self, tmp_path: Path) -> Path:
        installer = tmp_path / "run.sh"
        installer.write_text("#!/bin/bash\n")
        return installer

    def test_previously_failed_goes_straight_to_fallback(self) -> None:
        _fast_install._FAILED.add(7)
        with patch(f"{PKG}._installer_path") as find:
            assert _fast_install.fast_install(7, "G") is False
        find.assert_not_called()

    def test_no_installer(self) -> None:
        # The autouse guard already hides the real installer.
        assert _fast_install.fast_install(7, "G") is False

    def test_refused(self, tmp_path: Path) -> None:
        with (
            patch(f"{PKG}._installer_path", return_value=self._ready(tmp_path)),
            patch(f"{PKG}._refusal", return_value="a game is running"),
            patch(f"{PKG}._echo") as echo,
            patch(f"{PKG}.subprocess.run") as run,
        ):
            assert _fast_install.fast_install(7, "G") is False
        run.assert_not_called()
        assert "a game is running" in echo.call_args.args[0]

    def test_no_terminal_spawns_detached(self, tmp_path: Path) -> None:
        with (
            patch(f"{PKG}._installer_path", return_value=self._ready(tmp_path)),
            patch(f"{PKG}._refusal", return_value=None),
            patch(f"{PKG}.sys.stdin.isatty", return_value=False),
            patch(f"{PKG}._spawn_detached") as spawn,
            patch(f"{PKG}.subprocess.run") as run,
        ):
            assert _fast_install.fast_install(7, "G") is True
        spawn.assert_called_once()
        run.assert_not_called()

    def test_terminal_runs_in_foreground(self, tmp_path: Path) -> None:
        with (
            patch(f"{PKG}._installer_path", return_value=self._ready(tmp_path)),
            patch(f"{PKG}._refusal", return_value=None),
            patch(f"{PKG}.sys.stdin.isatty", return_value=True),
            patch(f"{PKG}._echo"),
            patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            assert _fast_install.fast_install(7, "G") is True
        assert set() == _fast_install._FAILED

    def test_foreground_failure_falls_back(self, tmp_path: Path) -> None:
        with (
            patch(f"{PKG}._installer_path", return_value=self._ready(tmp_path)),
            patch(f"{PKG}._refusal", return_value=None),
            patch(f"{PKG}.sys.stdin.isatty", return_value=True),
            patch(f"{PKG}._echo") as echo,
            patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=2)),
        ):
            assert _fast_install.fast_install(7, "G") is False
        assert {7} == _fast_install._FAILED
        assert "exit 2" in echo.call_args.args[0]
