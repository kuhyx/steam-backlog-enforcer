"""Tests for hltb module — part 2 (missing coverage)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self
from unittest.mock import patch

from steam_backlog_enforcer.hltb import (
    fetch_hltb_detail_missing,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer._hltb_types import _HLTBExtras

PKG = "steam_backlog_enforcer._hltb_confidence"


class _DummySession:
    """Minimal async context manager used to mock aiohttp ClientSession."""

    async def __aenter__(self) -> Self:
        """Enter async context."""
        return self

    async def __aexit__(self, *_args: object) -> bool:
        """Exit async context."""
        return False


class TestFetchHltbDetailMissing:
    """Tests for fetch_hltb_detail_missing."""

    def test_no_missing_returns_zero(self) -> None:
        """All games in rush cache with known game IDs → early return."""
        with (
            patch(f"{PKG}.load_hltb_rush_cache", return_value={440: 15.0}),
            patch(f"{PKG}.load_hltb_game_id_cache", return_value={440: 12345}),
            patch(f"{PKG}.fetch_hltb_times") as mock_fetch,
        ):
            result = fetch_hltb_detail_missing([(440, "TF2")])
        assert result == 0
        mock_fetch.assert_not_called()

    def test_fetches_missing_and_returns_count(self) -> None:
        """Games not in rush cache are fetched; returns count with rush data."""

        def add_rush(
            _games: object,
            cache: dict[int, float] | None = None,
            polls: dict[int, int] | None = None,
            progress_cb: object = None,
            extras: _HLTBExtras | None = None,
        ) -> list[object]:
            """Test add rush."""
            if extras is not None:
                extras.rush[730] = 10.0
            if cache is not None:
                cache[730] = 25.0
            return []

        with (
            patch(f"{PKG}.load_hltb_rush_cache", return_value={440: 15.0}),
            patch(f"{PKG}.load_hltb_cache", return_value={730: 20.0}),
            patch(f"{PKG}.load_hltb_polls_cache", return_value={}),
            patch(f"{PKG}.load_hltb_count_comp_cache", return_value={}),
            patch(f"{PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{PKG}.fetch_hltb_times", side_effect=add_rush),
            patch(f"{PKG}.save_hltb_cache") as mock_save,
            patch(f"{PKG}.time.monotonic", side_effect=[0.0, 2.0]),
        ):
            result = fetch_hltb_detail_missing([(440, "TF2"), (730, "CS")])
        assert result == 1
        mock_save.assert_called_once()

    def test_restores_prior_hours_when_not_refound(self) -> None:
        """Hours are restored when re-fetch finds nothing for the game."""
        saved: dict[int, float] = {}

        def capture_save(
            cache: dict[int, float],
            _polls: object,
            _extras: object = None,
        ) -> None:
            """Test capture save."""
            saved.update(cache)

        with (
            patch(f"{PKG}.load_hltb_rush_cache", return_value={}),
            patch(f"{PKG}.load_hltb_cache", return_value={730: 20.0}),
            patch(f"{PKG}.load_hltb_polls_cache", return_value={}),
            patch(f"{PKG}.load_hltb_count_comp_cache", return_value={}),
            patch(f"{PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{PKG}.fetch_hltb_times"),  # no-op, cache stays empty
            patch(f"{PKG}.save_hltb_cache", side_effect=capture_save),
            patch(f"{PKG}.time.monotonic", side_effect=[0.0, 1.0]),
        ):
            fetch_hltb_detail_missing([(730, "CS")])
        assert saved[730] == 20.0

    def test_does_not_restore_when_refound(self) -> None:
        """Prior hours are NOT restored when re-fetch successfully finds game."""

        def add_hours_and_rush(
            _games: object,
            cache: dict[int, float] | None = None,
            polls: dict[int, int] | None = None,
            progress_cb: object = None,
            extras: _HLTBExtras | None = None,
        ) -> list[object]:
            """Test add hours and rush."""
            if cache is not None:
                cache[730] = 30.0
            if extras is not None:
                extras.rush[730] = 12.0
            return []

        saved: dict[int, float] = {}

        def capture_save(
            cache: dict[int, float],
            _polls: object,
            _extras: object = None,
        ) -> None:
            """Test capture save."""
            saved.update(cache)

        with (
            patch(f"{PKG}.load_hltb_rush_cache", return_value={}),
            patch(f"{PKG}.load_hltb_cache", return_value={730: 20.0}),
            patch(f"{PKG}.load_hltb_polls_cache", return_value={}),
            patch(f"{PKG}.load_hltb_count_comp_cache", return_value={}),
            patch(f"{PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{PKG}.fetch_hltb_times", side_effect=add_hours_and_rush),
            patch(f"{PKG}.save_hltb_cache", side_effect=capture_save),
            patch(f"{PKG}.time.monotonic", side_effect=[0.0, 1.0]),
        ):
            result = fetch_hltb_detail_missing([(730, "CS")])
        assert result == 1
        assert saved[730] == 30.0

    def test_zero_elapsed_rate(self) -> None:
        """Covers the elapsed == 0 branch in the rate calculation."""
        with (
            patch(f"{PKG}.load_hltb_rush_cache", return_value={}),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.load_hltb_polls_cache", return_value={}),
            patch(f"{PKG}.load_hltb_count_comp_cache", return_value={}),
            patch(f"{PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{PKG}.fetch_hltb_times"),
            patch(f"{PKG}.save_hltb_cache"),
            patch(f"{PKG}.time.monotonic", side_effect=[5.0, 5.0]),
        ):
            result = fetch_hltb_detail_missing([(730, "CS")])
        assert result == 0

    def test_id_only_missing_logs_else_branch(self) -> None:
        """Rush data present but game ID missing → else branch in log selection."""
        with (
            patch(f"{PKG}.load_hltb_rush_cache", return_value={440: 15.0}),
            patch(f"{PKG}.load_hltb_cache", return_value={440: 15.0}),
            patch(f"{PKG}.load_hltb_polls_cache", return_value={}),
            patch(f"{PKG}.load_hltb_count_comp_cache", return_value={}),
            patch(f"{PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{PKG}.fetch_hltb_times"),
            patch(f"{PKG}.save_hltb_cache"),
            patch(f"{PKG}.time.monotonic", side_effect=[0.0, 1.0]),
        ):
            result = fetch_hltb_detail_missing([(440, "TF2")])
        assert result == 0
