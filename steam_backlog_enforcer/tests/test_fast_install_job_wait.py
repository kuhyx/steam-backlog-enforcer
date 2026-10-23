"""Tests for a fast install started outside the daemon (a web job, a pipe).

Only the root daemon reaps detached runs on its later passes. Any other
process exits once the command returns, so it must wait for the installer
itself - otherwise a stalled login prompt would hold Steam closed with
nobody left to interrupt it. Its log must also be its own: the daemon's
log is root-owned, and opening it as the desktop user used to raise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _fast_install, _fast_install_progress, config
from steam_backlog_enforcer._progress import use_progress

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer._fast_install"


def _ready(tmp_path: Path) -> Path:
    installer = tmp_path / "run.sh"
    installer.write_text("#!/bin/bash\n")
    return installer


def _fake_spawn(*returncodes: int | None, log_text: bytes | None = None) -> MagicMock:
    """A ``_spawn_detached`` that registers a run answering *returncodes*.

    With *log_text*, the run also gets a log holding it, tracked from byte 0.
    """

    def spawn(_cmd: list[str], app_id: int, label: str = "") -> None:
        proc = MagicMock(pid=4321)
        proc.poll.side_effect = list(returncodes)
        log = config.CONFIG_DIR / "x.log"
        if log_text is not None:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_bytes(log_text)
            _fast_install_progress.track(app_id, label, log, offset=0, now=0.0)
        _fast_install._RUNS.append(_fast_install._DetachedRun(app_id, proc, log))

    return MagicMock(side_effect=spawn)


class TestJobWaitsForInstaller:
    """A non-root, non-terminal caller blocks until the run is reaped."""

    def _install(self, tmp_path: Path, spawn: MagicMock, euid: int) -> bool:
        with (
            patch(f"{PKG}._installer_path", return_value=_ready(tmp_path)),
            patch(f"{PKG}._refusal", return_value=None),
            patch(f"{PKG}.sys.stdin.isatty", return_value=False),
            patch(f"{PKG}.os.geteuid", return_value=euid),
            patch(f"{PKG}._spawn_detached", spawn),
            patch(f"{PKG}.time.sleep"),
            patch(f"{PKG}._echo"),
        ):
            return _fast_install.fast_install(7, "G")

    def test_success_after_waiting(self, tmp_path: Path) -> None:
        assert self._install(tmp_path, _fake_spawn(None, None, 0), 1000) is True
        assert _fast_install._RUNS == []

    def test_failure_falls_back(self, tmp_path: Path) -> None:
        assert self._install(tmp_path, _fake_spawn(None, 3), 1000) is False
        assert {7} == _fast_install._FAILED

    def test_progress_is_reported_while_waiting(self, tmp_path: Path) -> None:
        text = b"Shutting down the Steam client...\r\nDownloading via depot\r\n"
        text += b"Processing depot 1\r\nDownloading depot 1\r\n"
        text += b" 46.90% /x/a.pak (657.13 Mbit/s)\r\n"
        progress = MagicMock()
        with use_progress(progress):
            assert self._install(tmp_path, _fake_spawn(None, 0, log_text=text), 1000)
        progress.phase.assert_called_with(
            "Fast-installing G: downloading depot 1/1", 100
        )
        progress.advance.assert_called_with("G", step=46)

    def test_daemon_returns_at_once(self, tmp_path: Path) -> None:
        assert self._install(tmp_path, _fake_spawn(), 0) is True
        assert _fast_install.is_fast_installing(7)


class TestLogIsPerUser:
    """A root-owned daemon log never blocks the desktop user's spawn."""

    def test_unwritable_daemon_log_is_not_used(self) -> None:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        daemon_log = config.CONFIG_DIR / "fast_install.log"
        daemon_log.write_text("root's\n")
        daemon_log.chmod(0o400)
        with (
            patch(f"{PKG}.os.geteuid", return_value=1000),
            patch(f"{PKG}.subprocess.Popen") as popen,
        ):
            _fast_install._spawn_detached(["run.sh"], 9)
        popen.assert_called_once()
        assert _fast_install._RUNS[0].log_path != daemon_log

    def test_progress_starts_at_the_current_end(self) -> None:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        log = config.CONFIG_DIR / "fast_install-1000.log"
        log.write_bytes(b"Restarting the Steam client...\r\n")  # the last run
        with (
            patch(f"{PKG}.os.geteuid", return_value=1000),
            patch(f"{PKG}.subprocess.Popen"),
        ):
            _fast_install._spawn_detached(["run.sh"], 9, "G")
        _fast_install_progress.poll_trackers({9})
        progress = _fast_install_progress.progress_of(9, now=0.0)
        assert progress is not None
        assert progress.phase == _fast_install_progress.STARTING
