"""Tests for a failed daemon-started fast install staying visible.

The root daemon has no job to print to: before, a failed run's tracker was
dropped and the Dashboard card simply vanished, as if nothing had happened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _fast_install
from steam_backlog_enforcer import _fast_install_progress as fip

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer._fast_install"


def _failed_run(tmp_path: Path, app_id: int = 7) -> None:
    """A tracked daemon run of *app_id* that has just exited 1."""
    log = tmp_path / "log"
    log.write_text("Restarting the Steam client...\n")
    fip.track(app_id, "Baldur's Gate 3", log, offset=0, now=0.0)
    proc = MagicMock(pid=4321)
    proc.poll.return_value = 1
    _fast_install._RUNS.append(_fast_install._DetachedRun(app_id, proc, log))


class TestFailedRunsStayListed:
    def test_status_carries_the_reason(self, tmp_path: Path) -> None:
        _failed_run(tmp_path)
        with patch(f"{PKG}.is_game_fully_installed", return_value=False):
            _fast_install.poll_fast_installs()
        assert fip.fast_install_status(now=9.0) == [
            {
                "app_id": 7,
                "name": "Baldur's Gate 3",
                "phase": "failed",
                "percent": None,
                "elapsed_seconds": 0,
                "error": "exit 1: Restarting the Steam client...",
            }
        ]

    def test_live_runs_have_no_error(self, tmp_path: Path) -> None:
        fip.track(8, "G", tmp_path / "log", offset=0, now=0.0)
        fip.poll_trackers({8})
        assert fip.fast_install_status(now=1.0)[0]["error"] is None

    def test_gone_once_the_game_is_installed(self, tmp_path: Path) -> None:
        """Steam's own download finished: the failure is history."""
        _failed_run(tmp_path)
        with patch(f"{PKG}.is_game_fully_installed", return_value=False):
            _fast_install.poll_fast_installs()
        with patch(f"{PKG}.is_game_fully_installed", return_value=True):
            _fast_install.poll_fast_installs()
        assert fip.fast_install_status(now=9.0) == []

    def test_a_new_run_replaces_the_failure(self, tmp_path: Path) -> None:
        _failed_run(tmp_path)
        with patch(f"{PKG}.is_game_fully_installed", return_value=False):
            _fast_install.poll_fast_installs()
        fip.track(7, "Baldur's Gate 3", tmp_path / "log", offset=0, now=0.0)
        assert [s["phase"] for s in fip.fast_install_status(now=1.0)] == [fip.STARTING]
