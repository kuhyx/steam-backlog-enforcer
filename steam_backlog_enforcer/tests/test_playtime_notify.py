"""Tests for _playtime_notify._humanise (kept from test_playtime_procs)."""

from __future__ import annotations

from steam_backlog_enforcer._playtime_notify import _humanise


class TestHumanise:
    def test_seconds(self) -> None:
        assert _humanise(30) == "30 seconds"

    def test_exact_minute_boundary(self) -> None:
        assert _humanise(60) == "1 minutes"

    def test_minutes(self) -> None:
        assert _humanise(300) == "5 minutes"

    def test_one_hour_is_special_cased(self) -> None:
        assert _humanise(3600) == "1 hour"

    def test_thirty_minutes(self) -> None:
        assert _humanise(1800) == "30 minutes"
