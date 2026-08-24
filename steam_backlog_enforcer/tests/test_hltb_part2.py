"""Tests for hltb module — part 2 (missing coverage)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from typing_extensions import Self

from steam_backlog_enforcer.hltb import (
    HLTB_BASE_URL,
    HLTBResult,
    fetch_hltb_times_cached,
    get_hltb_submit_url,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer._hltb_types import _HLTBExtras

PKG = "steam_backlog_enforcer.hltb"
_CACHED = "steam_backlog_enforcer._hltb_cached"
_CONF = "steam_backlog_enforcer._hltb_confidence"


class _DummySession:
    """Minimal async context manager used to mock aiohttp ClientSession."""

    async def __aenter__(self) -> Self:
        """Enter async context."""
        return self

    async def __aexit__(self, *_args: object) -> bool:
        """Exit async context."""
        return False


class TestFetchHltbTimesCached:
    """Tests for fetch_hltb_times_cached."""

    def test_all_cached(self) -> None:
        """Test all cached."""
        with (
            patch(f"{_CACHED}.load_hltb_cache", return_value={440: 50.0}),
        ):
            result = fetch_hltb_times_cached([(440, "TF2")])
        assert result == {440: 50.0}

    def test_uncached_games_fetched(self) -> None:
        """Test uncached games fetched."""
        with (
            patch(f"{_CACHED}.load_hltb_cache", return_value={440: 50.0}),
            patch(f"{_CACHED}.fetch_hltb_times") as mock_fetch,
            patch(f"{_CACHED}.save_hltb_cache") as mock_save,
            patch(f"{_CACHED}.time.monotonic", side_effect=[0.0, 2.0]),
        ):
            # fetch_hltb_times modifies cache in-place
            def add_to_cache(
                _games: object,
                cache: dict[int, float] | None = None,
                polls: dict[int, int] | None = None,
                progress_cb: object = None,
                extras: _HLTBExtras | None = None,
            ) -> list[object]:
                """Test add to cache."""
                if cache is not None:
                    cache[730] = 20.0
                if polls is not None:
                    polls[730] = 0
                if extras is not None:
                    extras.count_comp[730] = 0
                return []

            mock_fetch.side_effect = add_to_cache
            result = fetch_hltb_times_cached(
                [(440, "TF2"), (730, "CS")],
            )
        assert result[440] == 50.0
        assert result[730] == 20.0
        mock_save.assert_called_once()

    def test_uncached_with_progress_cb(self) -> None:
        """Test uncached with progress cb."""
        cb = MagicMock()
        with (
            patch(f"{_CACHED}.load_hltb_cache", return_value={}),
            patch(f"{_CACHED}.fetch_hltb_times") as mock_fetch,
            patch(f"{_CACHED}.save_hltb_cache"),
            patch(f"{_CACHED}.time.monotonic", side_effect=[0.0, 1.0]),
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
            patch(f"{_CACHED}.load_hltb_cache", return_value={}),
            patch(f"{_CACHED}.fetch_hltb_times") as mock_fetch,
            patch(f"{_CACHED}.save_hltb_cache"),
            patch(f"{_CACHED}.time.monotonic", side_effect=[5.0, 5.0]),
        ):
            mock_fetch.return_value = []
            fetch_hltb_times_cached([(440, "TF2")])

    def test_found_count(self) -> None:
        """Covers the found count in logging."""
        with (
            patch(f"{_CACHED}.load_hltb_cache", return_value={}),
            patch(f"{_CACHED}.fetch_hltb_times") as mock_fetch,
            patch(f"{_CACHED}.save_hltb_cache"),
            patch(f"{_CACHED}.time.monotonic", side_effect=[0.0, 3.0]),
        ):

            def add_found(
                _games: object,
                cache: dict[int, float] | None = None,
                polls: dict[int, int] | None = None,
                progress_cb: object = None,
                extras: _HLTBExtras | None = None,
            ) -> list[object]:
                """Test add found."""
                if cache is not None:
                    cache[440] = 50.0
                    cache[730] = -1
                if polls is not None:
                    polls[440] = 5
                    polls[730] = 0
                if extras is not None:
                    extras.count_comp[440] = 15
                    extras.count_comp[730] = 0
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
        """Test found."""
        mock_result = HLTBResult(
            app_id=0,
            game_name="TF2",
            completionist_hours=50.0,
            similarity=1.0,
            hltb_game_id=12345,
        )
        with patch(f"{_CONF}.fetch_hltb_times", return_value=[mock_result]):
            url = get_hltb_submit_url("TF2")
        assert url == f"{HLTB_BASE_URL}/submit/game/12345"

    def test_not_found_empty(self) -> None:
        """Test not found empty."""
        with patch(f"{_CONF}.fetch_hltb_times", return_value=[]):
            url = get_hltb_submit_url("Unknown Game")
        assert url is None

    def test_not_found_no_id(self) -> None:
        """Test not found no id."""
        mock_result = HLTBResult(
            app_id=0,
            game_name="TF2",
            completionist_hours=50.0,
            similarity=1.0,
            hltb_game_id=0,
        )
        with patch(f"{_CONF}.fetch_hltb_times", return_value=[mock_result]):
            url = get_hltb_submit_url("TF2")
        assert url is None
