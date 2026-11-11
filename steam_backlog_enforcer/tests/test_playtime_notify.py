"""Tests for _playtime_notify._humanise (kept from test_playtime_procs)."""

from __future__ import annotations

import pytest

from steam_backlog_enforcer._playtime_notify import _humanise, short_duration


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [(30, "30s"), (60, "1m"), (300, "5m"), (3600, "1h"), (5400, "1h 30m")],
)
def test_short_duration(seconds: int, shown: str) -> None:
    """Toasts paint a number + unit, never a word."""
    assert short_duration(seconds) == shown


class TestHumanise:
    """Durations render as the words the playtime warning speaks."""

    def test_seconds(self) -> None:
        """Under a minute reads in seconds."""
        assert _humanise(30) == "30 seconds"

    def test_exact_minute_boundary(self) -> None:
        """Exactly sixty seconds already reads in minutes."""
        assert _humanise(60) == "1 minutes"

    def test_minutes(self) -> None:
        """Several minutes read as a minute count."""
        assert _humanise(300) == "5 minutes"

    def test_one_hour_is_special_cased(self) -> None:
        """One hour reads as the singular ``1 hour``."""
        assert _humanise(3600) == "1 hour"

    def test_thirty_minutes(self) -> None:
        """Half an hour stays in minutes."""
        assert _humanise(1800) == "30 minutes"
