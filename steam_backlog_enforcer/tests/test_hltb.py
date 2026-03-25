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
    _build_search_payload,
    _fetch_batch,
    _get_auth_token,
    _get_hltb_search_url,
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


class TestGetAuthToken:
    """Tests for _get_auth_token."""

    def test_success(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"token": "abc123"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_token("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result == "abc123"

    def test_non_200(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_token("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None

    def test_client_error(self) -> None:
        mock_session = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=ctx)

        result = asyncio.run(
            _get_auth_token("https://howlongtobeat.com/api/finder", mock_session)
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

    def test_no_token(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_token",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, None))
            assert results == []

    def test_with_token(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_token",
                new_callable=AsyncMock,
                return_value="token123",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._search_one",
                new_callable=AsyncMock,
                return_value=HLTBResult(
                    app_id=440,
                    game_name="TF2",
                    completionist_hours=50.0,
                    similarity=1.0,
                ),
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, None))
            assert len(results) == 1

    def test_filters_none_results(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_token",
                new_callable=AsyncMock,
                return_value="token123",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._search_one",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, None))
            assert results == []
