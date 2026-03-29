"""Tests for hltb module."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from typing_extensions import Self

from python_pkg.steam_backlog_enforcer.hltb import (
    HLTBResult,
    _apply_dlc_leisure_overrides,
    _as_positive_int,
    _AuthInfo,
    _build_search_payload,
    _collect_dlc_relationships,
    _extract_base_leisure_hours,
    _extract_dlc_relationships,
    _extract_leisure_hours,
    _fetch_batch,
    _fetch_detail_one,
    _fetch_dlc_leisure_hours,
    _fetch_leisure_times,
    _get_auth_info,
    _get_hltb_search_url,
    _parse_game_page,
    _pick_best_hltb_entry,
    _search_one,
    _SearchCtx,
    _similarity,
    load_hltb_cache,
    save_hltb_cache,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class TestHltbCache:
    """Tests for HLTB cache I/O."""

    def test_load_cache_exists(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(json.dumps({"440": 10.5}), encoding="utf-8")
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb.HLTB_CACHE_FILE", cache_file
        ):
            result = load_hltb_cache()
            assert result == {440: 10.5}

    def test_load_cache_missing(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "nonexistent.json"
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb.HLTB_CACHE_FILE", cache_file
        ):
            assert load_hltb_cache() == {}

    def test_load_cache_corrupt(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text("not json", encoding="utf-8")
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb.HLTB_CACHE_FILE", cache_file
        ):
            assert load_hltb_cache() == {}

    def test_save_cache(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch("python_pkg.steam_backlog_enforcer.hltb.HLTB_CACHE_FILE", cache_file),
            patch("python_pkg.steam_backlog_enforcer.hltb.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5})
            assert cache_file.exists()

    def test_save_cache_os_error(self, tmp_path: Path) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._atomic_write",
            side_effect=OSError("disk full"),
        ):
            save_hltb_cache({440: 10.5})  # Should not raise


class TestGetHltbSearchUrl:
    """Tests for _get_hltb_search_url."""

    def test_discovers_url(self) -> None:
        mock_info = MagicMock()
        mock_info.search_url = "/api/search/abc"
        with patch("python_pkg.steam_backlog_enforcer.hltb.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.return_value = mock_info
            mock_html.BASE_URL = "https://howlongtobeat.com"
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/search/abc"

    def test_fallback_url(self) -> None:
        with patch("python_pkg.steam_backlog_enforcer.hltb.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.return_value = None
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/finder"

    def test_first_returns_none_second_returns_info(self) -> None:
        mock_info = MagicMock()
        mock_info.search_url = "/api/search/xyz"
        with patch("python_pkg.steam_backlog_enforcer.hltb.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.side_effect = [None, mock_info]
            mock_html.BASE_URL = "https://howlongtobeat.com"
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/search/xyz"

    def test_exception_fallback(self) -> None:
        with patch("python_pkg.steam_backlog_enforcer.hltb.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.side_effect = RuntimeError
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/finder"


class TestGetAuthInfo:
    """Tests for _get_auth_info."""

    def test_success(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"token": "abc123", "hpKey": "ign_x", "hpVal": "ff"}
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result == _AuthInfo("abc123", "ign_x", "ff")

    def test_success_no_hp(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"token": "abc123"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result == _AuthInfo("abc123")

    def test_no_token_key(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"notoken": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None

    def test_non_200(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None

    def test_client_error(self) -> None:
        mock_session = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=ctx)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None


class TestSimilarity:
    """Tests for _similarity."""

    def test_identical(self) -> None:
        assert _similarity("hello", "hello") == 1.0

    def test_different(self) -> None:
        assert _similarity("abc", "xyz") < 0.5

    def test_case_insensitive(self) -> None:
        assert _similarity("Hello", "hello") == 1.0


class TestBuildSearchPayload:
    """Tests for _build_search_payload."""

    def test_returns_json(self) -> None:
        payload = _build_search_payload("Half-Life 2")
        data = json.loads(payload)
        assert data["searchType"] == "games"
        assert data["searchTerms"] == ["Half-Life", "2"]

    def test_with_auth(self) -> None:
        auth = _AuthInfo("t", "ign_x", "ff")
        payload = _build_search_payload("TF2", auth=auth)
        data = json.loads(payload)
        assert data["ign_x"] == "ff"

    def test_with_auth_no_hp_key(self) -> None:
        auth = _AuthInfo("t")
        payload = _build_search_payload("TF2", auth=auth)
        data = json.loads(payload)
        assert "" not in data


class TestPickBestHltbEntry:
    """Tests for _pick_best_hltb_entry."""

    def test_empty(self) -> None:
        assert _pick_best_hltb_entry("game", []) is None

    def test_single(self) -> None:
        entry: dict[str, Any] = {"game_name": "Game", "comp_100": 3600}
        result = _pick_best_hltb_entry("Game", [(entry, 1.0)])
        assert result is not None
        assert result[0]["game_name"] == "Game"

    def test_prefers_full_edition_colon(self) -> None:
        demo: dict[str, Any] = {"game_name": "FAITH", "comp_100": 1800}
        full: dict[str, Any] = {
            "game_name": "FAITH: The Unholy Trinity",
            "comp_100": 7200,
        }
        result = _pick_best_hltb_entry("FAITH", [(demo, 1.0), (full, 0.8)])
        assert result is not None
        assert result[0]["game_name"] == "FAITH: The Unholy Trinity"

    def test_prefers_full_edition_dash(self) -> None:
        demo: dict[str, Any] = {"game_name": "FAITH", "comp_100": 1800}
        full: dict[str, Any] = {"game_name": "FAITH - Complete", "comp_100": 7200}
        result = _pick_best_hltb_entry("FAITH", [(demo, 1.0), (full, 0.8)])
        assert result is not None
        assert result[0]["game_name"] == "FAITH - Complete"

    def test_falls_back_to_highest_similarity(self) -> None:
        a: dict[str, Any] = {"game_name": "ABC", "comp_100": 3600}
        b: dict[str, Any] = {"game_name": "DEF", "comp_100": 7200}
        result = _pick_best_hltb_entry("ABC", [(a, 0.9), (b, 0.7)])
        assert result is not None
        assert result[1] == 0.9

    def test_prefers_non_dlc_when_available(self) -> None:
        base: dict[str, Any] = {
            "game_name": "Helltaker",
            "game_type": "game",
            "comp_100": 6846,
        }
        dlc: dict[str, Any] = {
            "game_name": "Helltaker - Bonus Chapter: Examtaker",
            "game_type": "dlc",
            "comp_100": 4075,
        }
        result = _pick_best_hltb_entry("Helltaker", [(dlc, 0.95), (base, 0.8)])
        assert result is not None
        assert result[0]["game_type"] == "game"

    def test_skips_prologue_subset(self) -> None:
        """A '- Prologue' entry should not beat the full game."""
        full: dict[str, Any] = {
            "game_name": "A Space For The Unbound",
            "comp_100": 45000,
        }
        prologue: dict[str, Any] = {
            "game_name": "A Space for the Unbound - Prologue",
            "comp_100": 1680,
        }
        result = _pick_best_hltb_entry(
            "A Space for the Unbound",
            [(prologue, 0.9), (full, 0.95)],
        )
        assert result is not None
        assert result[0]["game_name"] == "A Space For The Unbound"

    def test_skips_demo_subset(self) -> None:
        """A ': Demo' entry should not beat the full game."""
        full: dict[str, Any] = {"game_name": "MyGame", "comp_100": 36000}
        demo: dict[str, Any] = {"game_name": "MyGame: Demo", "comp_100": 1800}
        result = _pick_best_hltb_entry("MyGame", [(demo, 0.9), (full, 1.0)])
        assert result is not None
        assert result[0]["game_name"] == "MyGame"

    def test_still_prefers_full_edition_over_demo(self) -> None:
        """A ': Full Edition' entry should still be preferred (not a subset)."""
        short: dict[str, Any] = {"game_name": "FAITH", "comp_100": 1800}
        full: dict[str, Any] = {
            "game_name": "FAITH: The Unholy Trinity",
            "comp_100": 7200,
        }
        result = _pick_best_hltb_entry("FAITH", [(short, 1.0), (full, 0.8)])
        assert result is not None
        assert result[0]["game_name"] == "FAITH: The Unholy Trinity"

    def test_exact_match_beats_unrelated_subtitle(self) -> None:
        """Exact name with more hours wins over an unrelated subtitle entry.

        'Killing Floor: Toy Master' (1.2 h) must NOT beat 'Killing Floor'
        (296 h) just because it starts with 'Killing Floor:'.
        """
        base: dict[str, Any] = {
            "game_name": "Killing Floor",
            "comp_100": 1065600,  # 296 h
        }
        spinoff: dict[str, Any] = {
            "game_name": "Killing Floor: Toy Master",
            "comp_100": 4320,  # 1.2 h
        }
        result = _pick_best_hltb_entry("Killing Floor", [(spinoff, 0.7), (base, 1.0)])
        assert result is not None
        assert result[0]["game_name"] == "Killing Floor"


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


def _make_ctx(
    session: MagicMock,
    *,
    cache: dict[int, float] | None = None,
    progress_cb: Callable[..., object] | None = None,
) -> _SearchCtx:
    return _SearchCtx(
        session=session,
        search_url="https://example.com/search",
        headers={},
        cache=cache if cache is not None else {},
        counter={"done": 0, "found": 0},
        total=1,
        progress_cb=progress_cb,
    )


class TestSearchOne:
    """Tests for _search_one."""

    def test_found(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "TF2",
                        "game_alias": "",
                        "comp_100": 180000,
                        "game_id": 12345,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is not None
        assert result.app_id == 440

    def test_not_found(self) -> None:
        resp = _FakeResponse(200, {"data": []})
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None
        assert ctx.cache[440] == -1

    def test_error(self) -> None:
        session = MagicMock()
        session.post.side_effect = aiohttp.ClientError("fail")
        ctx = _make_ctx(session)
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None

    def test_non_200(self) -> None:
        resp = _FakeResponse(500)
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None

    def test_with_progress_cb(self) -> None:
        resp = _FakeResponse(200, {"data": []})
        cb = MagicMock()
        ctx = _make_ctx(_make_session(resp), progress_cb=cb)
        asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        cb.assert_called_once()

    def test_low_similarity_skipped(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "Completely Different Name",
                        "game_alias": "",
                        "comp_100": 3600,
                        "game_id": 1,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None

    def test_zero_comp_100_skipped(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "TF2",
                        "game_alias": "",
                        "comp_100": 0,
                        "game_id": 1,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None

    def test_alias_match(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "Team Fortress 2",
                        "game_alias": "TF2",
                        "comp_100": 180000,
                        "game_id": 12345,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is not None

    def test_full_edition_colon(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "TF2: Complete",
                        "game_alias": "",
                        "comp_100": 180000,
                        "game_id": 99,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is not None

    def test_full_edition_dash(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "TF2 - Complete",
                        "game_alias": "",
                        "comp_100": 180000,
                        "game_id": 99,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is not None

    def test_save_interval(self) -> None:
        """Trigger the _SAVE_INTERVAL branch."""
        resp = _FakeResponse(200, {"data": []})
        ctx = _make_ctx(_make_session(resp))
        # Set done to one less than _SAVE_INTERVAL so it triggers save
        from python_pkg.steam_backlog_enforcer.hltb import _SAVE_INTERVAL

        ctx.counter["done"] = _SAVE_INTERVAL - 1
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb.save_hltb_cache"
        ) as mock_save:
            asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
            mock_save.assert_called_once()


class TestFetchBatchHltb:
    """Tests for _fetch_batch (the hltb version)."""

    def test_no_auth(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, None))
            assert results == []

    def test_with_auth(self) -> None:
        auth = _AuthInfo("token123", "ign_x", "ff")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_info",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._search_one",
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
                "python_pkg.steam_backlog_enforcer.hltb._fetch_leisure_times",
                new_callable=AsyncMock,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, None))
            assert len(results) == 1

    def test_with_auth_no_hp(self) -> None:
        auth = _AuthInfo("tok123")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_info",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._search_one",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._fetch_leisure_times",
                new_callable=AsyncMock,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, None))
            assert results == []

    def test_filters_none_results(self) -> None:
        auth = _AuthInfo("tok123")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_info",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._search_one",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._fetch_leisure_times",
                new_callable=AsyncMock,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, None))
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


class TestInternalHelpers:
    """Tests for internal helper coverage."""

    def test_as_positive_int_float(self) -> None:
        assert _as_positive_int(1.9) == 1

    def test_as_positive_int_invalid_type(self) -> None:
        assert _as_positive_int(object()) == 0

    def test_extract_base_leisure_non_dict_game(self) -> None:
        data: dict[str, Any] = {"game": [123]}
        assert _extract_base_leisure_hours(data) == -1

    def test_extract_dlc_relationships_skips_non_dict(self) -> None:
        data: dict[str, Any] = {
            "relationships": [
                "bad",
                {"game_type": "dlc", "game_id": 7, "comp_100": 3600},
            ],
        }
        assert _extract_dlc_relationships(data) == [(7, 1.0)]

    def test_collect_dlc_relationships_ignores_non_positive_id(self) -> None:
        valid = [
            HLTBResult(
                app_id=1,
                game_name="Game",
                completionist_hours=1.0,
                similarity=1.0,
                hltb_game_id=123,
            )
        ]
        details: list[dict[str, Any] | None] = [
            {
                "relationships": [
                    {"game_type": "dlc", "game_id": 0, "comp_100": 3600},
                ]
            }
        ]
        by_app, ids = _collect_dlc_relationships(valid, details)
        assert by_app[1] == [(0, 1.0)]
        assert ids == []

    def test_apply_dlc_leisure_overrides(self) -> None:
        adjusted = _apply_dlc_leisure_overrides(
            base_hours=6.0,
            dlc_rels=[(10, 1.0), (11, 2.0)],
            dlc_hours_by_id={10: 3.0},
        )
        assert adjusted == 8.0

    def test_fetch_dlc_leisure_hours_empty(self) -> None:
        async def _run() -> dict[int, float]:
            async with aiohttp.ClientSession() as session:
                return await _fetch_dlc_leisure_hours(asyncio.Semaphore(1), session, [])

        assert asyncio.run(_run()) == {}

    def test_fetch_dlc_leisure_hours_skips_none_data(self) -> None:
        async def _run() -> dict[int, float]:
            async with aiohttp.ClientSession() as session:
                with patch(
                    "python_pkg.steam_backlog_enforcer.hltb._fetch_detail_one",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    return await _fetch_dlc_leisure_hours(
                        asyncio.Semaphore(1),
                        session,
                        [1],
                    )

        assert asyncio.run(_run()) == {}

    def test_fetch_dlc_leisure_hours_skips_non_positive_leisure(self) -> None:
        bad_dlc_data: dict[str, Any] = {
            "game": [{"comp_100_h": 0, "comp_100": 0}],
            "relationships": [],
        }

        async def _run() -> dict[int, float]:
            async with aiohttp.ClientSession() as session:
                with patch(
                    "python_pkg.steam_backlog_enforcer.hltb._fetch_detail_one",
                    new_callable=AsyncMock,
                    return_value=bad_dlc_data,
                ):
                    return await _fetch_dlc_leisure_hours(
                        asyncio.Semaphore(1),
                        session,
                        [1],
                    )

        assert asyncio.run(_run()) == {}


class _FakeTextResponse:
    """Async context manager mimicking aiohttp response for text."""

    def __init__(self, status: int, text: str = "") -> None:
        self.status = status
        self._text = text

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def text(self) -> str:
        return self._text


class TestFetchDetailOne:
    """Tests for _fetch_detail_one."""

    def test_success(self) -> None:
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243}],
            "relationships": [],
        }
        next_data = {"props": {"pageProps": {"game": {"data": game_data}}}}
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(next_data)
            + "</script>"
        )
        resp = _FakeTextResponse(200, html)
        session = MagicMock()
        session.get = MagicMock(return_value=resp)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result == game_data

    def test_non_200(self) -> None:
        resp = _FakeTextResponse(404)
        session = MagicMock()
        session.get = MagicMock(return_value=resp)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result is None

    def test_client_error(self) -> None:
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.get = MagicMock(return_value=ctx)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result is None

    def test_parse_failure(self) -> None:
        resp = _FakeTextResponse(200, "<html>no script</html>")
        session = MagicMock()
        session.get = MagicMock(return_value=resp)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result is None


class TestFetchLeisureTimes:
    """Tests for _fetch_leisure_times."""

    def test_updates_cache(self) -> None:
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=12345,
            ),
        ]
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243}],
            "relationships": [],
        }
        cache: dict[int, float] = {}
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, None))
        assert cache[440] == round(21243 / 3600, 2)
        assert results[0].completionist_hours == round(21243 / 3600, 2)

    def test_no_valid_results(self) -> None:
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=0,
            ),
        ]
        cache: dict[int, float] = {}
        asyncio.run(_fetch_leisure_times(results, cache, None))
        assert cache == {}

    def test_empty_results(self) -> None:
        cache: dict[int, float] = {}
        asyncio.run(_fetch_leisure_times([], cache, None))
        assert cache == {}

    def test_detail_returns_none(self) -> None:
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=12345,
            ),
        ]
        cache: dict[int, float] = {}
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=None,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, None))
        assert cache == {}
        assert results[0].completionist_hours == 50.0

    def test_negative_leisure(self) -> None:
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=12345,
            ),
        ]
        game_data: dict[str, Any] = {"game": [], "relationships": []}
        cache: dict[int, float] = {}
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, None))
        assert cache == {}
        assert results[0].completionist_hours == 50.0

    def test_with_progress_cb(self) -> None:
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=12345,
            ),
        ]
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [],
        }
        cache: dict[int, float] = {}
        cb = MagicMock()
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, cb))
        cb.assert_called_once()

    def test_save_interval(self) -> None:
        """Trigger the _SAVE_INTERVAL branch in leisure fetching."""
        from python_pkg.steam_backlog_enforcer.hltb import _SAVE_INTERVAL

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
        cache: dict[int, float] = {}
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._fetch_detail_one",
                new_callable=AsyncMock,
                return_value=game_data,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb.save_hltb_cache"
            ) as mock_save,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, None))
            mock_save.assert_called_once()

    def test_dlc_detail_overrides_relationship_fallback(self) -> None:
        results = [
            HLTBResult(
                app_id=1289310,
                game_name="Helltaker",
                completionist_hours=1.0,
                similarity=1.0,
                hltb_game_id=78118,
            ),
        ]
        base_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6846}],
            "relationships": [{"game_type": "dlc", "game_id": 92236, "comp_100": 4075}],
        }
        dlc_data: dict[str, Any] = {
            "game": [{"comp_100_h": 12298, "comp_100": 4075}],
            "relationships": [],
        }
        cache: dict[int, float] = {}
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._fetch_detail_one",
            new_callable=AsyncMock,
            side_effect=[base_data, dlc_data],
        ):
            asyncio.run(_fetch_leisure_times(results, cache, None))

        expected = round((21243 + 12298) / 3600, 2)
        assert cache[1289310] == expected
        assert results[0].completionist_hours == expected

    def test_missing_dlc_detail_keeps_relationship_fallback(self) -> None:
        results = [
            HLTBResult(
                app_id=1289310,
                game_name="Helltaker",
                completionist_hours=1.0,
                similarity=1.0,
                hltb_game_id=78118,
            ),
        ]
        base_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6846}],
            "relationships": [{"game_type": "dlc", "game_id": 92236, "comp_100": 4075}],
        }
        cache: dict[int, float] = {}
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb._fetch_detail_one",
            new_callable=AsyncMock,
            side_effect=[base_data, None],
        ):
            asyncio.run(_fetch_leisure_times(results, cache, None))

        expected = round((21243 + 4075) / 3600, 2)
        assert cache[1289310] == expected
        assert results[0].completionist_hours == expected
