"""Tests for HLTB search, batch-fetch, and page parsing — part 2."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import aiohttp

from steam_backlog_enforcer.tests._hltb_search_fakes import (
    FakeResponse,
    hit,
    make_ctx,
    make_session,
    run_search,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from steam_backlog_enforcer._hltb_search import _SearchCtx


def _ctx(
    session: MagicMock, *, progress_cb: Callable[..., object] | None = None
) -> _SearchCtx:
    """Return a search context whose counter also tracks failures."""
    return make_ctx(
        session,
        progress_cb=progress_cb,
        counter={"done": 0, "found": 0, "failed": 0},
    )


class TestSearchOne:
    """Tests for _search_one."""

    def test_found(self) -> None:
        """Test found."""
        ctx = _ctx(make_session(FakeResponse(200, hit("TF2", 180000, 12345))))
        result = run_search(ctx)
        assert result is not None
        assert result.app_id == 440

    def test_found_without_game_id(self) -> None:
        """Found result with hltb_game_id=0 does not populate ctx.hltb_game_id."""
        ctx = _ctx(make_session(FakeResponse(200, hit("TF2", 180000, 0))))
        result = run_search(ctx)
        assert result is not None
        assert 440 not in ctx.results.extras.hltb_game_id

    def test_not_found(self) -> None:
        """Test not found."""
        ctx = _ctx(make_session(FakeResponse(200, {"data": []})))
        result = run_search(ctx)
        assert result is None
        assert ctx.cache[440] == -1

    def test_error(self) -> None:
        """Test error."""
        session = MagicMock()
        session.post.side_effect = aiohttp.ClientError("fail")
        ctx = _ctx(session)
        result = run_search(ctx)
        assert result is None
        assert 440 not in ctx.cache  # a failed lookup is not a miss
        assert ctx.counter["failed"] == 1

    def test_non_200(self) -> None:
        """Test non 200."""
        ctx = _ctx(make_session(FakeResponse(500)))
        result = run_search(ctx)
        assert result is None
        assert 440 not in ctx.cache  # a failed lookup is not a miss
        assert ctx.counter["failed"] == 1

    def test_fallback_name_without_year_suffix(self) -> None:
        """Test fallback name without year suffix."""
        session = MagicMock()
        session.post.side_effect = [
            FakeResponse(200, {"data": []}),
            FakeResponse(
                200,
                hit(
                    "Final Fantasy VII",
                    141120,
                    435,
                    game_type="game",
                    comp_100_count=746,
                    count_comp=10450,
                ),
            ),
        ]
        ctx = _ctx(session)
        result = run_search(ctx, 39140, "Final Fantasy VII (2013)")
        assert result is not None
        assert result.app_id == 39140
        assert result.comp_100_count == 746
        assert result.count_comp == 10450
        assert session.post.call_count == 2

    def test_with_progress_cb(self) -> None:
        """Test with progress cb."""
        cb = MagicMock()
        ctx = _ctx(make_session(FakeResponse(200, {"data": []})), progress_cb=cb)
        run_search(ctx)
        cb.assert_called_once()

    def test_low_similarity_skipped(self) -> None:
        """Test low similarity skipped."""
        body = hit("Completely Different Name", 3600, 1)
        result = run_search(_ctx(make_session(FakeResponse(200, body))))
        assert result is None
