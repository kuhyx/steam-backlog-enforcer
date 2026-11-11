"""Tests for HLTB internal helpers, detail fetching, and leisure times — part 3."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
    HLTBResult,
    _HLTBExtras,
)
from steam_backlog_enforcer.tests._hltb_leisure_runs import (
    helltaker_result,
    run_leisure,
    tf2_result,
)


class TestFetchLeisureTimesGroup2:
    """Tests for _fetch_leisure_times."""

    def test_save_interval(self) -> None:
        """Trigger the _SAVE_INTERVAL branch in leisure fetching."""
        results = [
            HLTBResult(
                app_id=i,
                game_name=f"Game{i}",
                completionist_hours=1.0,
                similarity=1.0,
                hltb_game_id=i + 1000,
            )
            for i in range(_SAVE_INTERVAL)
        ]
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [],
        }
        with patch("steam_backlog_enforcer._hltb_detail.save_hltb_cache") as mock_save:
            run_leisure(results, game_data)
            mock_save.assert_called_once()

    def test_dlc_detail_overrides_relationship_fallback(self) -> None:
        """Test dlc detail overrides relationship fallback."""
        results = [helltaker_result()]
        base_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6846}],
            "relationships": [{"game_type": "dlc", "game_id": 92236, "comp_100": 4075}],
        }
        dlc_data: dict[str, Any] = {
            "game": [{"comp_100_h": 12298, "comp_100": 4075}],
            "relationships": [],
        }
        cache = run_leisure(results, details=[base_data, dlc_data])

        expected = round((21243 + 12298) / 3600, 2)
        assert cache[1289310] == expected
        assert results[0].completionist_hours == expected

    def test_missing_dlc_detail_keeps_relationship_fallback(self) -> None:
        """Test missing dlc detail keeps relationship fallback."""
        results = [helltaker_result()]
        base_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6846}],
            "relationships": [{"game_type": "dlc", "game_id": 92236, "comp_100": 4075}],
        }
        cache = run_leisure(results, details=[base_data, None])

        expected = round((21243 + 4075) / 3600, 2)
        assert cache[1289310] == expected
        assert results[0].completionist_hours == expected

    def test_extras_populated_with_rush_and_l100(self) -> None:
        """rush_h and l100 are stored in extras when game has comp_100 data."""
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 10800, "comp_100": 7200}],
            "relationships": [],
        }
        extras = _HLTBExtras(count_comp={440: 5})
        run_leisure([tf2_result()], game_data, extras=extras)
        assert extras.rush[440] == round(7200 / 3600, 2)
        assert extras.leisure_100h[440] == round(10800 / 3600, 2)

    def test_with_explicit_extras(self) -> None:
        """Pass a pre-populated _HLTBExtras to cover the non-None extras branch."""
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [],
        }
        extras = _HLTBExtras(count_comp={440: 5})
        cache = run_leisure([tf2_result()], game_data, extras=extras)
        assert cache[440] == 1.0

    def test_count_comp_from_detail_page_stored_in_extras(self) -> None:
        """Line 254: extras.count_comp updated when game detail has count_comp > 0."""
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600, "count_comp": 99}],
            "relationships": [],
        }
        extras = _HLTBExtras()
        run_leisure([tf2_result()], game_data, extras=extras)
        assert extras.count_comp[440] == 99
