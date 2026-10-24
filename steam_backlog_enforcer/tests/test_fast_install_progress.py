"""Tests for _fast_install_progress: reading a live installer log.

The fixture is a verbatim excerpt of a real Baldur's Gate 3 run (the per-file
lines of the big depots trimmed). It is stored with LF endings and written
back with CRLF, which is what the installer's pty actually produces.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from steam_backlog_enforcer import _fast_install_progress as fip

MOD = "steam_backlog_enforcer._fast_install_progress"
EXCERPT = (Path(__file__).parent / "fast_install_log_excerpt.txt").read_text(
    encoding="utf-8"
)
LINES = EXCERPT.splitlines()


def _upto(marker: str, *, extra: int = 0) -> str:
    """The excerpt through the line equal to *marker*, else the first it starts.

    Exact first: ``Downloading depot 228989`` is also the start of the earlier
    ``Downloading depot 228989 manifest``.
    """
    exact = [i for i, line in enumerate(LINES) if line == marker]
    index = (exact or [i for i, ln in enumerate(LINES) if ln.startswith(marker)])[0]
    return "".join(f"{line}\r\n" for line in LINES[: index + 1 + extra])


def _tracker(tmp_path: Path, text: str, *, offset: int = 0) -> fip.InstallTracker:
    log = tmp_path / "fast_install-1000.log"
    log.write_bytes(text.encode())
    tracker = fip.InstallTracker(log, offset=offset, started=100.0)
    tracker.poll()
    return tracker


class TestPhases:
    """Each installer stage the log announces becomes a phase."""

    def test_nothing_yet_is_starting(self, tmp_path: Path) -> None:
        snap = _tracker(tmp_path, "").snapshot(now=103.0)
        assert snap == fip.InstallProgress(fip.STARTING, None, 3)

    def test_shutting_steam_down(self, tmp_path: Path) -> None:
        snap = _tracker(tmp_path, _upto("Shutting down")).snapshot(now=112.0)
        assert snap.phase == "shutting Steam down"
        assert snap.percent is None
        assert snap.describe() == "shutting Steam down, 12s elapsed"

    def test_connecting_before_any_depot(self, tmp_path: Path) -> None:
        snap = _tracker(tmp_path, _upto("Logging ")).snapshot(now=100.0)
        assert snap.phase == "connecting to Steam"

    def test_adopting_steams_partial_download(self, tmp_path: Path) -> None:
        line = (
            "Steam already staged 71.53 GB for this app (161 files). Hardlinking "
            "it into place so depotdownloader verifies instead of refetching.\r\n"
        )
        snap = _tracker(tmp_path, line).snapshot(now=100.0)
        assert snap.phase == "adopting Steam's partial download"

    def test_first_depot_percent(self, tmp_path: Path) -> None:
        snap = _tracker(tmp_path, _upto(" 46.90%")).snapshot(now=100.0)
        assert snap.phase == "downloading depot 1/8"
        assert snap.percent == pytest.approx(46.90)
        assert snap.downloading

    def test_new_depot_resets_the_percent(self, tmp_path: Path) -> None:
        # Pre-allocating lines only: the previous depot's 100% must not show.
        text = _upto("Downloading depot 228990", extra=3)
        snap = _tracker(tmp_path, text).snapshot(now=100.0)
        assert snap.phase == "downloading depot 2/8"
        assert snap.percent is None
        assert snap.describe() == "downloading depot 2/8, 0s elapsed"

    def test_percent_outside_a_depot_is_ignored(self, tmp_path: Path) -> None:
        text = _upto("Shutting down") + " 46.90% /x/y.cmd (657.13 Mbit/s)\r\n"
        snap = _tracker(tmp_path, text).snapshot(now=100.0)
        assert snap.phase == "shutting Steam down"
        assert snap.percent is None

    def test_percent_is_per_depot(self, tmp_path: Path) -> None:
        snap = _tracker(tmp_path, _upto(" 92.49%")).snapshot(now=100.0)
        assert snap.phase == "downloading depot 3/8"
        assert snap.percent == pytest.approx(92.49)

    def test_finishing_after_the_download(self, tmp_path: Path) -> None:
        snap = _tracker(tmp_path, _upto("Checking for owned DLC")).snapshot(now=0)
        assert snap.phase == "finishing manifest"
        assert snap.percent is None
        assert not snap.downloading

    def test_whole_run_ends_restarting_steam(self, tmp_path: Path) -> None:
        snap = _tracker(tmp_path, _upto("Restarting")).snapshot(now=100.0)
        assert snap.phase == "restarting Steam"

    def test_describe_with_percent_and_minutes(self, tmp_path: Path) -> None:
        snap = _tracker(tmp_path, _upto(" 99.35%")).snapshot(now=100.0 + 312)
        assert snap.describe() == "99% (downloading depot 3/8), 5m 12s elapsed"


class TestIncrementalRead:
    """Only bytes written since the spawn are read, a line at a time."""

    def test_previous_run_before_offset_is_ignored(self, tmp_path: Path) -> None:
        previous = _upto("Restarting")  # the last run ended at 100%...
        log = tmp_path / "fast_install-1000.log"
        log.write_bytes(previous.encode())
        tracker = fip.InstallTracker(log, offset=log.stat().st_size, started=0.0)
        tracker.poll()
        assert tracker.snapshot(now=1.0).phase == fip.STARTING
        with log.open("ab") as out:  # ...and the new one has just begun.
            out.write(_upto("Shutting down").encode())
        tracker.poll()
        snap = tracker.snapshot(now=1.0)
        assert snap.phase == "shutting Steam down"
        assert snap.percent is None

    def test_partial_line_waits_for_its_end(self, tmp_path: Path) -> None:
        log = tmp_path / "log"
        log.write_bytes(_upto("Downloading depot 228989").encode() + b" 46.9")
        tracker = fip.InstallTracker(log, offset=0, started=0.0)
        tracker.poll()
        assert tracker.snapshot(now=0).percent is None
        with log.open("ab") as out:
            out.write(b"0% /x/y.cmd (657.13 Mbit/s)\r\n")
        tracker.poll()
        assert tracker.snapshot(now=0).percent == pytest.approx(46.90)

    def test_missing_log_is_a_no_op(self, tmp_path: Path) -> None:
        tracker = fip.InstallTracker(tmp_path / "gone.log", offset=0, started=0.0)
        tracker.poll()
        assert tracker.snapshot(now=0).phase == fip.STARTING


class TestRegistry:
    """Daemon runs are tracked by app id and exposed as status entries."""

    def test_status_lists_live_runs(self, tmp_path: Path) -> None:
        log = tmp_path / "log"
        log.write_bytes(_upto(" 59.16%").encode())
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
        with patch(f"{MOD}._echo") as echo:
            fip.WaitReporter(7, "G", started=0.0)
        echo.assert_called_once_with(
            "  Fast-installing G with steam-game-installer (Steam will close); "
            "progress every 30s..."
        )

    def test_phase_then_percent_step(self, tmp_path: Path) -> None:
        reporter = self._reporter(tmp_path, _upto(" 99.35%"))
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
        reporter = self._reporter(tmp_path, _upto("Shutting down"))
        progress = MagicMock()
        with (
            patch(f"{MOD}.current_progress", return_value=progress),
            patch(f"{MOD}._echo"),
        ):
            reporter.report(now=12.0)
        progress.phase.assert_called_once_with(
            "Fast-installing G: shutting Steam down", None
        )
        progress.advance.assert_called_once_with("12s elapsed", step=0)

    def test_echo_is_throttled_to_30_seconds(self, tmp_path: Path) -> None:
        reporter = self._reporter(tmp_path, _upto(" 46.90%"))
        with patch(f"{MOD}.current_progress"), patch(f"{MOD}._echo") as echo:
            for now in (5.0, 10.0, 29.0, 31.0, 45.0, 62.0):
                reporter.report(now=now)
        assert echo.call_args_list == [
            call("  Fast-installing G: 46% (downloading depot 1/8), 31s elapsed"),
            call("  Fast-installing G: 46% (downloading depot 1/8), 1m 02s elapsed"),
        ]

    def test_untracked_run_reports_nothing(self) -> None:
        progress = MagicMock()
        with (
            patch(f"{MOD}.current_progress", return_value=progress),
            patch(f"{MOD}._echo") as echo,
        ):
            fip.WaitReporter(99, "G", started=0.0).report(now=60.0)
        progress.phase.assert_not_called()
        progress.advance.assert_not_called()
        assert echo.call_count == 1  # the announcement only
