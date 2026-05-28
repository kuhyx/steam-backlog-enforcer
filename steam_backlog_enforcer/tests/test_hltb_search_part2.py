"""Tests for HLTB search entry picking, page parsing, and leisure extraction."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typing_extensions import Self

from steam_backlog_enforcer._hltb_detail import (
    _extract_leisure_hours,
    _parse_game_page,
)
from steam_backlog_enforcer._hltb_search import (
    _build_search_variants,
    _fetch_batch,
    _pick_best_hltb_entry,
)
from steam_backlog_enforcer._hltb_types import (
    HLTBResult,
    _AuthInfo,
)


class _FakeResponse:
    """Async context manager mimicking aiohttp response."""

    def __init__(self, status: int, json_data: dict[str, Any] | None = None) -> None:
        self.status = status
        self._json_data = json_data or {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def json(self) -> dict[str, Any]:
        return self._json_data


def _make_session(resp: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.post.return_value = resp
    return session


class TestPickBestEntry:
    """Tests for exact-vs-extended entry choice logic."""

    def test_prefers_exact_over_low_confidence_modded_extended(self) -> None:
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
        auth = _AuthInfo("token123", "ign_x", "ff")
        with (
            patch(
                "steam_backlog_enforcer._hltb_search._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._get_auth_info",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._search_one",
                new_callable=AsyncMock,
                return_value=HLTBResult(
                    app_id=440,
                    game_name="TF2",
                    completionist_hours=50.0,
                    similarity=1.0,
                    hltb_game_id=12345,
                ),
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._fetch_leisure_times",
                new_callable=AsyncMock,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
            assert len(results) == 1

    def test_with_auth_no_hp(self) -> None:
        auth = _AuthInfo("tok123")
        with (
            patch(
                "steam_backlog_enforcer._hltb_search._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._get_auth_info",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._search_one",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._fetch_leisure_times",
                new_callable=AsyncMock,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
            assert results == []

    def test_filters_none_results(self) -> None:
        auth = _AuthInfo("tok123")
        with (
            patch(
                "steam_backlog_enforcer._hltb_search._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._get_auth_info",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._search_one",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._fetch_leisure_times",
                new_callable=AsyncMock,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
            assert results == []


class TestParseGamePage:
    """Tests for _parse_game_page."""

    def test_valid_html(self) -> None:
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
        assert _parse_game_page("<html></html>") is None

    def test_bad_json(self) -> None:
        html = '<script id="__NEXT_DATA__" type="application/json">{not json}</script>'
        assert _parse_game_page(html) is None

    def test_missing_keys(self) -> None:
        html = (
            '<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>'
        )
        assert _parse_game_page(html) is None


class TestExtractLeisureHours:
    """Tests for _extract_leisure_hours."""

    def test_leisure_time_only(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6800}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == round(21243 / 3600, 2)

    def test_leisure_with_dlc(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6800}],
            "relationships": [
                {"game_type": "dlc", "comp_100": 12298},
                {"game_type": "dlc", "comp_100": 3600},
            ],
        }
        assert _extract_leisure_hours(data) == round((21243 + 12298 + 3600) / 3600, 2)

    def test_fallback_to_comp_100(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100": 7200}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == round(7200 / 3600, 2)

    def test_no_game_data(self) -> None:
        assert _extract_leisure_hours({"game": [], "relationships": []}) == -1

    def test_zero_leisure(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 0, "comp_100": 0}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == -1

    def test_no_game_key(self) -> None:
        assert _extract_leisure_hours({"relationships": []}) == -1

    def test_non_dlc_relationship_ignored(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [
                {"game_type": "game", "comp_100": 9999},
                {"game_type": "dlc", "comp_100": 1800},
            ],
        }
        assert _extract_leisure_hours(data) == round((3600 + 1800) / 3600, 2)

    def test_dlc_zero_comp_100_skipped(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [
                {"game_type": "dlc", "comp_100": 0},
            ],
        }
        assert _extract_leisure_hours(data) == round(3600 / 3600, 2)

    def test_negative_leisure(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": -1, "comp_100": -1}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == -1

    def test_string_numeric_fields(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": "7200", "comp_100": "3600"}],
            "relationships": [{"game_type": "dlc", "game_id": "1", "comp_100": "1800"}],
        }
        assert _extract_leisure_hours(data) == round((7200 + 1800) / 3600, 2)

    def test_bad_string_falls_back_to_comp_100(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": "bad", "comp_100": "3600"}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == 1.0

    def test_relationships_not_list(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": "not-a-list",
        }
        assert _extract_leisure_hours(data) == 1.0


class TestBuildSearchVariants:
    """Tests for _build_search_variants."""

    def test_subtitle_with_edition_strips_edition_from_subtitle_part(self) -> None:
        # "Rocksmith 2014 Edition - Remastered" → no_subtitle = "Rocksmith 2014 Edition"
        # (which != base), so lines 201-202 also add "Rocksmith" and "Rocksmith 2014"
        variants = _build_search_variants("Rocksmith 2014 Edition - Remastered")
        assert "Rocksmith 2014 Edition" in variants
        assert "Rocksmith 2014" in variants
        assert "Rocksmith" in variants

    def test_no_subtitle_skips_edition_strip(self) -> None:
        # No " - " → no_subtitle == base → lines 201-202 are not executed
        variants = _build_search_variants("Portal 2")
        assert "Portal 2" in variants
