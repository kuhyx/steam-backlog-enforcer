"""Tests for hltb module - part 3 (fetch_hltb_times)."""

from __future__ import annotations

from unittest.mock import patch

from python_pkg.steam_backlog_enforcer.hltb import (
    HLTBResult,
    fetch_hltb_times,
)


class TestFetchHltbTimes:
    """Tests for fetch_hltb_times."""

    def test_empty(self) -> None:
        assert fetch_hltb_times([]) == []

    def test_calls_batch(self) -> None:
        mock_result = HLTBResult(
            app_id=440, game_name="TF2", completionist_hours=50.0, similarity=1.0
        )
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._fetch_batch",
            return_value=[mock_result],
        ):
            results = fetch_hltb_times([(440, "TF2")])
            assert len(results) == 1

    def test_none_cache(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._fetch_batch",
            return_value=[],
        ):
            results = fetch_hltb_times([(440, "TF2")])
            assert results == []

    def test_explicit_cache(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._fetch_batch",
            return_value=[],
        ):
            cache: dict[int, float] = {440: 10.0}
            results = fetch_hltb_times([(440, "TF2")], cache=cache)
            assert results == []
