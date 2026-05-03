"""Tests for hltb module — part 2 (missing coverage)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from typing_extensions import Self

from python_pkg.steam_backlog_enforcer.hltb import (
    HLTB_BASE_URL,
    HLTBResult,
    _AuthInfo,
    _fetch_batch_confidence_only,
    fetch_hltb_confidence,
    fetch_hltb_confidence_cached,
    fetch_hltb_times_cached,
    get_hltb_submit_url,
)

PKG = "python_pkg.steam_backlog_enforcer.hltb"


class TestFetchHltbTimesCached:
    """Tests for fetch_hltb_times_cached."""

    def test_all_cached(self) -> None:
        with (
            patch(f"{PKG}.load_hltb_cache", return_value={440: 50.0}),
        ):
            result = fetch_hltb_times_cached([(440, "TF2")])
        assert result == {440: 50.0}

    def test_uncached_games_fetched(self) -> None:
        with (
            patch(f"{PKG}.load_hltb_cache", return_value={440: 50.0}),
            patch(f"{PKG}.fetch_hltb_times") as mock_fetch,
            patch(f"{PKG}.save_hltb_cache") as mock_save,
            patch(f"{PKG}.time.monotonic", side_effect=[0.0, 2.0]),
        ):
            # fetch_hltb_times modifies cache in-place
            def add_to_cache(
                _games: object,
                cache: dict[int, float] | None = None,
                polls: dict[int, int] | None = None,
                progress_cb: object = None,
                count_comp: dict[int, int] | None = None,
            ) -> list[object]:
                if cache is not None:
                    cache[730] = 20.0
                if polls is not None:
                    polls[730] = 0
                if count_comp is not None:
                    count_comp[730] = 0
                return []

            mock_fetch.side_effect = add_to_cache
            result = fetch_hltb_times_cached(
                [(440, "TF2"), (730, "CS")],
            )
        assert result[440] == 50.0
        assert result[730] == 20.0
        mock_save.assert_called_once()

    def test_uncached_with_progress_cb(self) -> None:
        cb = MagicMock()
        with (
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.fetch_hltb_times") as mock_fetch,
            patch(f"{PKG}.save_hltb_cache"),
            patch(f"{PKG}.time.monotonic", side_effect=[0.0, 1.0]),
        ):
            mock_fetch.return_value = []
            result = fetch_hltb_times_cached(
                [(440, "TF2")],
                progress_cb=cb,
            )
        assert 440 not in result or result.get(440) == -1

    def test_uncached_zero_elapsed(self) -> None:
        """Covers the elapsed == 0 branch for rate calculation."""
        with (
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.fetch_hltb_times") as mock_fetch,
            patch(f"{PKG}.save_hltb_cache"),
            patch(f"{PKG}.time.monotonic", side_effect=[5.0, 5.0]),
        ):
            mock_fetch.return_value = []
            fetch_hltb_times_cached([(440, "TF2")])

    def test_found_count(self) -> None:
        """Covers the found count in logging."""
        with (
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.fetch_hltb_times") as mock_fetch,
            patch(f"{PKG}.save_hltb_cache"),
            patch(f"{PKG}.time.monotonic", side_effect=[0.0, 3.0]),
        ):

            def add_found(
                _games: object,
                cache: dict[int, float] | None = None,
                polls: dict[int, int] | None = None,
                progress_cb: object = None,
                count_comp: dict[int, int] | None = None,
            ) -> list[object]:
                if cache is not None:
                    cache[440] = 50.0
                    cache[730] = -1
                if polls is not None:
                    polls[440] = 5
                    polls[730] = 0
                if count_comp is not None:
                    count_comp[440] = 15
                    count_comp[730] = 0
                return []

            mock_fetch.side_effect = add_found
            result = fetch_hltb_times_cached(
                [(440, "TF2"), (730, "CS")],
            )
        assert result[440] == 50.0
        assert result[730] == -1


class TestGetHltbSubmitUrl:
    """Tests for get_hltb_submit_url."""

    def test_found(self) -> None:
        mock_result = HLTBResult(
            app_id=0,
            game_name="TF2",
            completionist_hours=50.0,
            similarity=1.0,
            hltb_game_id=12345,
        )
        with patch(f"{PKG}.fetch_hltb_times", return_value=[mock_result]):
            url = get_hltb_submit_url("TF2")
        assert url == f"{HLTB_BASE_URL}/submit/game/12345"

    def test_not_found_empty(self) -> None:
        with patch(f"{PKG}.fetch_hltb_times", return_value=[]):
            url = get_hltb_submit_url("Unknown Game")
        assert url is None

    def test_not_found_no_id(self) -> None:
        mock_result = HLTBResult(
            app_id=0,
            game_name="TF2",
            completionist_hours=50.0,
            similarity=1.0,
            hltb_game_id=0,
        )
        with patch(f"{PKG}.fetch_hltb_times", return_value=[mock_result]):
            url = get_hltb_submit_url("TF2")
        assert url is None


class _DummySession:
    """Minimal async context manager used to mock aiohttp ClientSession."""

    async def __aenter__(self) -> Self:
        """Enter async context."""
        return self

    async def __aexit__(self, *_args: object) -> bool:
        """Exit async context."""
        return False


class TestConfidenceHelpers:
    """Coverage tests for confidence-fetch helpers."""

    def test_fetch_batch_confidence_only_returns_empty_without_auth(self) -> None:
        with (
            patch(f"{PKG}.aiohttp.ClientSession", return_value=_DummySession()),
            patch(f"{PKG}.aiohttp.TCPConnector"),
            patch(f"{PKG}._get_hltb_search_url", return_value="https://example"),
            patch(f"{PKG}._get_auth_info", return_value=None),
        ):
            result = asyncio.run(
                _fetch_batch_confidence_only([(1, "Game")], {}, {}, None),
            )
        assert result == []

    def test_fetch_batch_confidence_only_handles_empty_hp_and_default_counts(
        self,
    ) -> None:
        auth_token = str(1)
        with (
            patch(f"{PKG}.aiohttp.ClientSession", return_value=_DummySession()),
            patch(f"{PKG}.aiohttp.TCPConnector"),
            patch(f"{PKG}._get_hltb_search_url", return_value="https://example"),
            patch(
                f"{PKG}._get_auth_info",
                return_value=_AuthInfo(token=auth_token, hp_key="", hp_val=""),
            ),
            patch(f"{PKG}._search_one", side_effect=[None]) as mock_search,
        ):
            result = asyncio.run(
                _fetch_batch_confidence_only(
                    games=[(1, "Game")],
                    cache={},
                    polls={},
                    progress_cb=None,
                    count_comp=None,
                ),
            )
        assert result == []
        mock_search.assert_called_once()

    def test_fetch_hltb_confidence_initializes_optional_dicts(self) -> None:
        with patch(f"{PKG}.asyncio.run", return_value=[]) as mock_run:
            result = fetch_hltb_confidence([(1, "Game")])
        assert result == []
        mock_run.assert_called_once()

    def test_fetch_hltb_confidence_empty_games_returns_empty(self) -> None:
        with patch(f"{PKG}.asyncio.run") as mock_run:
            result = fetch_hltb_confidence([])
        assert result == []
        mock_run.assert_not_called()

    def test_fetch_hltb_confidence_cached_all_cached_skips_fetch(self) -> None:
        with (
            patch(f"{PKG}.load_hltb_cache", return_value={1: 12.0}),
            patch(f"{PKG}.load_hltb_polls_cache", return_value={1: 30}),
            patch(f"{PKG}.load_hltb_count_comp_cache", return_value={1: 200}),
            patch(f"{PKG}.fetch_hltb_confidence") as mock_fetch,
            patch(f"{PKG}.save_hltb_cache") as mock_save,
        ):
            result = fetch_hltb_confidence_cached([(1, "Game")])
        assert result == {1: 12.0}
        mock_fetch.assert_not_called()
        mock_save.assert_not_called()
