"""Tests for _fast_install_progress: the run registry and the wait reporter.

Split from test_fast_install_progress.py; both read the recorded installer
log excerpt in ``_fast_install_excerpt``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call, patch

from steam_backlog_enforcer import _fast_install_progress as fip
from steam_backlog_enforcer.tests._fast_install_excerpt import MOD, upto

if TYPE_CHECKING:
    from pathlib import Path


class TestRegistry:
    """Daemon runs are tracked by app id and exposed as status entries."""

    def test_status_lists_live_runs(self, tmp_path: Path) -> None:
        """A tracked live run is listed with phase, percent and elapsed time."""
        log = tmp_path / "log"
        log.write_bytes(upto(" 59.16%").encode())
        fip.track(7, "Baldur's Gate 3", log, offset=0, now=10.0)
        fip.poll_trackers({7})
        assert fip.fast_install_status(now=70.0) == [
            {
                "app_id": 7,
                "name": "Baldur's Gate 3",
                "phase": "downloading depot 1/8",
                "percent": 59.16,
                "elapsed_seconds": 60,
                "error": None,
            }
        ]

    def test_finished_runs_are_dropped(self, tmp_path: Path) -> None:
        """A run no longer live is dropped from status and progress."""
        fip.track(7, "G", tmp_path / "log", offset=0, now=0.0)
        fip.poll_trackers(set())
        assert fip.fast_install_status(now=1.0) == []
        assert fip.progress_of(7, now=1.0) is None


class TestWaitReporter:
    """A waiting web job moves its progress bar and prints a line every 30 s."""

    def _reporter(self, tmp_path: Path, text: str) -> fip.WaitReporter:
        log = tmp_path / "log"
        log.write_bytes(text.encode())
        fip.track(7, "G", log, offset=0, now=0.0)
        fip.poll_trackers({7})
        with patch(f"{MOD}._echo"):
            return fip.WaitReporter(7, "G", started=0.0)

    def test_announces_the_wait(self) -> None:
        """Creating a reporter announces the fast install once."""
        with patch(f"{MOD}._echo") as echo:
            fip.WaitReporter(7, "G", started=0.0)
        echo.assert_called_once_with(
            "  Fast-installing G with steam-game-installer (Steam will close); "
            "progress every 30s..."
        )

    def test_phase_then_percent_step(self, tmp_path: Path) -> None:
        """The phase is set once and the floored percent advances the bar."""
        reporter = self._reporter(tmp_path, upto(" 99.35%"))
        progress = MagicMock()
        with (
            patch(f"{MOD}.current_progress", return_value=progress),
            patch(f"{MOD}._echo"),
        ):
            reporter.report(now=5.0)
            reporter.report(now=10.0)
        # The phase is announced once; 99.35 floors so it never claims done.
        progress.phase.assert_called_once_with(
            "Fast-installing G: downloading depot 3/8", 100
        )
        assert progress.advance.call_args_list == [
            call("G", step=99),
            call("G", step=99),
        ]

    def test_indeterminate_phase_shows_elapsed(self, tmp_path: Path) -> None:
        """A phase without percent shows the elapsed time."""
        reporter = self._reporter(tmp_path, upto("Shutting down"))
        progress = MagicMock()
        with (
            patch(f"{MOD}.current_progress", return_value=progress),
            patch(f"{MOD}._echo"),
        ):
            reporter.report(now=12.0)
        progress.phase.assert_called_once_with(
            "Fast-installing G: shutting Steam down", None
        )
        progress.advance.assert_called_once_with("⏱️ 12s", step=0)

    def test_echo_is_throttled_to_30_seconds(self, tmp_path: Path) -> None:
        """Progress lines are echoed at most every 30 s."""
        reporter = self._reporter(tmp_path, upto(" 46.90%"))
        with patch(f"{MOD}.current_progress"), patch(f"{MOD}._echo") as echo:
            for now in (5.0, 10.0, 29.0, 31.0, 45.0, 62.0):
                reporter.report(now=now)
        assert echo.call_args_list == [
            call("  Fast-installing G: 46% (downloading depot 1/8), 31s elapsed"),
            call("  Fast-installing G: 46% (downloading depot 1/8), 1m 02s elapsed"),
        ]

    def test_untracked_run_reports_nothing(self) -> None:
        """An untracked run moves no bar and echoes only the announcement."""
        progress = MagicMock()
        with (
            patch(f"{MOD}.current_progress", return_value=progress),
            patch(f"{MOD}._echo") as echo,
        ):
            fip.WaitReporter(99, "G", started=0.0).report(now=60.0)
        progress.phase.assert_not_called()
        progress.advance.assert_not_called()
        assert echo.call_count == 1  # the announcement only
