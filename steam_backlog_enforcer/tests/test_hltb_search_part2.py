"""Tests for HLTB search entry picking, page parsing, and leisure extraction."""

from __future__ import annotations

import json
from typing import Any

from steam_backlog_enforcer._hltb_page_parse import _parse_game_page
from steam_backlog_enforcer._hltb_search_api import _pick_best_hltb_entry
from steam_backlog_enforcer._hltb_types import (
    HLTBResult,
    _AuthInfo,
)
from steam_backlog_enforcer.tests._hltb_search_fakes import fetch_tf2_batch


class TestPickBestEntry:
    """Tests for exact-vs-extended entry choice logic."""

    def test_prefers_exact_over_low_confidence_modded_extended(self) -> None:
        """Test prefers exact over low confidence modded extended."""
        exact = (
            {
                "game_name": "Celeste",
                "game_alias": "",
                "game_type": "game",
                "comp_100": 141105,
                "comp_100_count": 899,
                "count_comp": 14055,
            },
            1.0,
        )
        mod_extended = (
            {
                "game_name": "Celeste - Strawberry Jam",
                "game_alias": "",
                "game_type": "mod",
                "comp_100": 952080,
                "comp_100_count": 1,
                "count_comp": 6,
            },
            0.9,
        )

        best = _pick_best_hltb_entry("Celeste", [exact, mod_extended])
        assert best is not None
        assert best[0]["game_name"] == "Celeste"

    def test_prefers_extended_when_confident_and_longer(self) -> None:
        """Test prefers extended when confident and longer."""
        exact_demo = (
            {
                "game_name": "FAITH",
                "game_alias": "",
                "game_type": "game",
                "comp_100": 1800,
                "comp_100_count": 1,
                "count_comp": 1,
            },
            1.0,
        )
        full_extended = (
            {
                "game_name": "FAITH: The Unholy Trinity",
                "game_alias": "",
                "game_type": "game",
                "comp_100": 25200,
                "comp_100_count": 50,
                "count_comp": 500,
            },
            0.9,
        )

        best = _pick_best_hltb_entry("FAITH", [exact_demo, full_extended])
        assert best is not None
        assert best[0]["game_name"] == "FAITH: The Unholy Trinity"

    def test_with_auth(self) -> None:
        """Test with auth."""
        auth = _AuthInfo("token123", "ign_x", "ff")
        found = HLTBResult(
            app_id=440,
            game_name="TF2",
            completionist_hours=50.0,
            similarity=1.0,
            hltb_game_id=12345,
        )
        results = fetch_tf2_batch(auth, found)
        assert len(results) == 1

    def test_with_auth_no_hp(self) -> None:
        """Test with auth no hp."""
        auth = _AuthInfo("tok123")
        results = fetch_tf2_batch(auth, None)
        assert results == []

    def test_filters_none_results(self) -> None:
        """Test filters none results."""
        auth = _AuthInfo("tok123")
        results = fetch_tf2_batch(auth, None)
        assert results == []


class TestParseGamePage:
    """Tests for _parse_game_page."""

    def test_valid_html(self) -> None:
        """Test valid html."""
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6800}],
            "relationships": [],
        }
        next_data = {
            "props": {"pageProps": {"game": {"data": game_data}}},
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(next_data)
            + "</script></html>"
        )
        assert _parse_game_page(html) == game_data

    def test_no_script_tag(self) -> None:
        """Test no script tag."""
        assert _parse_game_page("<html></html>") is None

    def test_bad_json(self) -> None:
        """Test bad json."""
        html = '<script id="__NEXT_DATA__" type="application/json">{not json}</script>'
        assert _parse_game_page(html) is None

    def test_missing_keys(self) -> None:
        """Test missing keys."""
        html = (
            '<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>'
        )
        assert _parse_game_page(html) is None
