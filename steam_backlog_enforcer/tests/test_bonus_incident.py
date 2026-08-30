"""Tests for _bonus_incident: telling the user a bonus could not be checked.

The rate limit is the part worth pinning. The enforcer ticks frequently, so a
single stopped service would otherwise produce a notification every tick and an
unbounded log file -- which trains the user to ignore exactly the message that
means an hour is quietly missing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._bonus_incident import (
    report_leetcode_incident,
    reset_reported,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._bonus_incident"


@pytest.fixture(autouse=True)
def _clear_reported() -> Iterator[None]:
    """Keep reported-incident memory from leaking between tests.

    Yields:
        None, with the memo empty before and after.
    """
    reset_reported()
    yield
    reset_reported()


class TestReporting:
    """All three channels fire, once."""

    def test_it_notifies_logs_and_appends(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A first incident reaches every channel.

        Args:
            tmp_path: pytest's temporary directory.
            caplog: pytest's log capture.
        """
        log = tmp_path / "incidents.log"
        with (
            caplog.at_level(logging.WARNING),
            patch(f"{_PKG}.INCIDENT_LOG", log),
            patch(f"{_PKG}.notify_desktop_user") as notify,
        ):
            report_leetcode_incident("ledger unreadable", fix="systemctl status x")
        assert notify.call_count == 1
        assert "ledger unreadable" in caplog.text
        assert "systemctl status x" in log.read_text(encoding="utf-8")

    def test_the_same_reason_is_reported_once_a_day(self, tmp_path: Path) -> None:
        """A ticking daemon must not produce a notification storm.

        Args:
            tmp_path: pytest's temporary directory.
        """
        log = tmp_path / "incidents.log"
        with (
            patch(f"{_PKG}.INCIDENT_LOG", log),
            patch(f"{_PKG}.notify_desktop_user") as notify,
        ):
            for _ in range(5):
                report_leetcode_incident("ledger unreadable", fix="check it")
        assert notify.call_count == 1
        assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 1

    def test_a_different_reason_still_gets_through(self, tmp_path: Path) -> None:
        """Suppression is per reason, not a blanket daily mute.

        Args:
            tmp_path: pytest's temporary directory.
        """
        log = tmp_path / "incidents.log"
        with (
            patch(f"{_PKG}.INCIDENT_LOG", log),
            patch(f"{_PKG}.notify_desktop_user") as notify,
        ):
            report_leetcode_incident("ledger unreadable", fix="a")
            report_leetcode_incident("status API unreachable", fix="b")
        assert notify.call_count == 2

    def test_a_repeat_is_still_traceable(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A suppressed repeat leaves a debug line, so it does not look cleared.

        Args:
            tmp_path: pytest's temporary directory.
            caplog: pytest's log capture.
        """
        log = tmp_path / "incidents.log"
        with (
            caplog.at_level(logging.DEBUG),
            patch(f"{_PKG}.INCIDENT_LOG", log),
            patch(f"{_PKG}.notify_desktop_user"),
        ):
            report_leetcode_incident("ledger unreadable", fix="a")
            caplog.clear()
            report_leetcode_incident("ledger unreadable", fix="a")
        assert "still unavailable" in caplog.text


class TestDegradedReporting:
    """A channel that fails must not take the others down with it."""

    def test_an_unwritable_log_is_reported_not_raised(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The notification already went out; losing the file is not fatal.

        Args:
            tmp_path: pytest's temporary directory.
            caplog: pytest's log capture.
        """
        unwritable = tmp_path / "no-such-dir" / "incidents.log"
        with (
            caplog.at_level(logging.WARNING),
            patch(f"{_PKG}.INCIDENT_LOG", unwritable),
            patch(f"{_PKG}.notify_desktop_user") as notify,
        ):
            report_leetcode_incident("ledger unreadable", fix="a")
        assert notify.call_count == 1
        assert "Could not append" in caplog.text


class TestResetReported:
    """The test hook itself, used by the autouse fixture above."""

    def test_reset_lets_the_same_reason_fire_again(self, tmp_path: Path) -> None:
        """Without this, one test would mute the next.

        Args:
            tmp_path: pytest's temporary directory.
        """
        log = tmp_path / "incidents.log"
        with (
            patch(f"{_PKG}.INCIDENT_LOG", log),
            patch(f"{_PKG}.notify_desktop_user") as notify,
        ):
            report_leetcode_incident("ledger unreadable", fix="a")
            reset_reported()
            report_leetcode_incident("ledger unreadable", fix="a")
        assert notify.call_count == 2
