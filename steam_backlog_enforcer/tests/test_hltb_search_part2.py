"""Tests for HLTB search entry picking, page parsing, and leisure extraction."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typing_extensions import Self

from steam_backlog_enforcer._hltb_detail import (
    _parse_game_page,
)
from steam_backlog_enforcer._hltb_search import (
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
        """Test init."""
        self.status = status
        self._json_data = json_data or {}

    async def __aenter__(self) -> Self:
        """Test aenter."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Test aexit."""

    async def json(self) -> dict[str, Any]:
        """Test json."""
        return self._json_data


def _make_session(resp: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.post.return_value = resp
    return session


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
        """Test with auth no hp."""
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
        """Test filters none results."""
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
