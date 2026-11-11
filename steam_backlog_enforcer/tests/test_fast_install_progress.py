"""Tests for _fast_install_progress: reading a live installer log.

The fixture is a verbatim excerpt of a real Baldur's Gate 3 run, see
``_fast_install_excerpt``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from steam_backlog_enforcer import _fast_install_progress as fip
from steam_backlog_enforcer.tests._fast_install_excerpt import upto

if TYPE_CHECKING:
    from pathlib import Path


def _tracker(tmp_path: Path, text: str, *, offset: int = 0) -> fip.InstallTracker:
    log = tmp_path / "fast_install-1000.log"
    log.write_bytes(text.encode())
    tracker = fip.InstallTracker(log, offset=offset, started=100.0)
    tracker.poll()
    return tracker


class TestPhases:
    """Each installer stage the log announces becomes a phase."""

    def test_nothing_yet_is_starting(self, tmp_path: Path) -> None:
        """An empty log reads as starting with the elapsed time."""
        snap = _tracker(tmp_path, "").snapshot(now=103.0)
        assert snap == fip.InstallProgress(fip.STARTING, None, 3)

    def test_shutting_steam_down(self, tmp_path: Path) -> None:
        """The shutdown line reads as shutting Steam down, no percent."""
        snap = _tracker(tmp_path, upto("Shutting down")).snapshot(now=112.0)
        assert snap.phase == "shutting Steam down"
        assert snap.percent is None
        assert snap.describe() == "shutting Steam down, 12s elapsed"

    def test_connecting_before_any_depot(self, tmp_path: Path) -> None:
        """The login line reads as connecting to Steam."""
        snap = _tracker(tmp_path, upto("Logging ")).snapshot(now=100.0)
        assert snap.phase == "connecting to Steam"

    def test_adopting_steams_partial_download(self, tmp_path: Path) -> None:
        """The hardlink line reads as adopting the partial download."""
        line = (
            "Steam already staged 71.53 GB for this app (161 files). Hardlinking "
            "it into place so depotdownloader verifies instead of refetching.\r\n"
        )
        snap = _tracker(tmp_path, line).snapshot(now=100.0)
        assert snap.phase == "adopting Steam's partial download"

    def test_first_depot_percent(self, tmp_path: Path) -> None:
        """A first-depot percent line reads as downloading 1/8 at that percent."""
        snap = _tracker(tmp_path, upto(" 46.90%")).snapshot(now=100.0)
        assert snap.phase == "downloading depot 1/8"
        assert snap.percent == pytest.approx(46.90)
        assert snap.downloading

    def test_new_depot_resets_the_percent(self, tmp_path: Path) -> None:
        """A new depot drops the previous depot percent."""
        # Pre-allocating lines only: the previous depot's 100% must not show.
        text = upto("Downloading depot 228990", extra=3)
        snap = _tracker(tmp_path, text).snapshot(now=100.0)
        assert snap.phase == "downloading depot 2/8"
        assert snap.percent is None
        assert snap.describe() == "downloading depot 2/8, 0s elapsed"

    def test_percent_outside_a_depot_is_ignored(self, tmp_path: Path) -> None:
        """A percent line outside any depot does not set a percent."""
        text = upto("Shutting down") + " 46.90% /x/y.cmd (657.13 Mbit/s)\r\n"
        snap = _tracker(tmp_path, text).snapshot(now=100.0)
        assert snap.phase == "shutting Steam down"
        assert snap.percent is None

    def test_percent_is_per_depot(self, tmp_path: Path) -> None:
        """The percent belongs to the current depot."""
        snap = _tracker(tmp_path, upto(" 92.49%")).snapshot(now=100.0)
        assert snap.phase == "downloading depot 3/8"
        assert snap.percent == pytest.approx(92.49)

    def test_finishing_after_the_download(self, tmp_path: Path) -> None:
        """The DLC check after the download reads as finishing manifest."""
        snap = _tracker(tmp_path, upto("Checking for owned DLC")).snapshot(now=0)
        assert snap.phase == "finishing manifest"
        assert snap.percent is None
        assert not snap.downloading

    def test_whole_run_ends_restarting_steam(self, tmp_path: Path) -> None:
        """A full run ends in the restarting Steam phase."""
        snap = _tracker(tmp_path, upto("Restarting")).snapshot(now=100.0)
        assert snap.phase == "restarting Steam"

    def test_describe_with_percent_and_minutes(self, tmp_path: Path) -> None:
        """describe floors the percent and formats minutes and seconds."""
        snap = _tracker(tmp_path, upto(" 99.35%")).snapshot(now=100.0 + 312)
        assert snap.describe() == "99% (downloading depot 3/8), 5m 12s elapsed"


class TestIncrementalRead:
    """Only bytes written since the spawn are read, a line at a time."""

    def test_previous_run_before_offset_is_ignored(self, tmp_path: Path) -> None:
        """Log bytes before the spawn offset are not read."""
        previous = upto("Restarting")  # the last run ended at 100%...
        log = tmp_path / "fast_install-1000.log"
        log.write_bytes(previous.encode())
        tracker = fip.InstallTracker(log, offset=log.stat().st_size, started=0.0)
        tracker.poll()
        assert tracker.snapshot(now=1.0).phase == fip.STARTING
        with log.open("ab") as out:  # ...and the new one has just begun.
            out.write(upto("Shutting down").encode())
        tracker.poll()
        snap = tracker.snapshot(now=1.0)
        assert snap.phase == "shutting Steam down"
        assert snap.percent is None

    def test_partial_line_waits_for_its_end(self, tmp_path: Path) -> None:
        """An unterminated line is parsed only once it ends."""
        log = tmp_path / "log"
        log.write_bytes(upto("Downloading depot 228989").encode() + b" 46.9")
        tracker = fip.InstallTracker(log, offset=0, started=0.0)
        tracker.poll()
        assert tracker.snapshot(now=0).percent is None
        with log.open("ab") as out:
            out.write(b"0% /x/y.cmd (657.13 Mbit/s)\r\n")
        tracker.poll()
        assert tracker.snapshot(now=0).percent == pytest.approx(46.90)

    def test_missing_log_is_a_no_op(self, tmp_path: Path) -> None:
        """A missing log file leaves the tracker starting."""
        tracker = fip.InstallTracker(tmp_path / "gone.log", offset=0, started=0.0)
        tracker.poll()
        assert tracker.snapshot(now=0).phase == fip.STARTING
