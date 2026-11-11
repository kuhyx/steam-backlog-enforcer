"""Tests for HLTB search, batch-fetch, and page parsing — part 2."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
)
from steam_backlog_enforcer.tests._hltb_search_fakes import (
    FakeResponse,
    hit,
    make_ctx,
    make_session,
    run_search,
    search_tf2,
)


class TestSearchOneGroup2:
    """Tests for _search_one."""

    def test_zero_comp_100_skipped(self) -> None:
        """Test zero comp 100 skipped."""
        result = search_tf2(hit("TF2", 0, 1))
        assert result is None

    def test_alias_match(self) -> None:
        """Test alias match."""
        result = search_tf2(hit("Team Fortress 2", 180000, 12345, alias="TF2"))
        assert result is not None

    def test_full_edition_colon(self) -> None:
        """Test full edition colon."""
        result = search_tf2(hit("TF2: Complete", 180000, 99))
        assert result is not None

    def test_full_edition_dash(self) -> None:
        """Test full edition dash."""
        result = search_tf2(hit("TF2 - Complete", 180000, 99))
        assert result is not None

    def test_save_interval(self) -> None:
        """Trigger the _SAVE_INTERVAL branch."""
        resp = FakeResponse(200, {"data": []})
        ctx = make_ctx(make_session(resp))
        # Set done to one less than _SAVE_INTERVAL so it triggers save

        ctx.counter["done"] = _SAVE_INTERVAL - 1
        with patch(
            "steam_backlog_enforcer._hltb_search_one.save_hltb_cache"
        ) as mock_save:
            run_search(ctx)
            mock_save.assert_called_once()

    def test_colon_strip_fallback_rejects_cross_franchise_match(self) -> None:
        """Colon-stripped fallback must not match a different franchise loosely.

        "Vox Populi: Poland 2023" stripped to "Vox Populi" should NOT match
        "Vox Populi Vox Dei 2" (different game, low-similarity entry).
        """
        empty_resp = FakeResponse(200, {"data": []})
        loose_resp = FakeResponse(
            200,
            hit(
                "Vox Populi Vox Dei 2",
                14400,
                99999,
                game_type="game",
                comp_100_count=9,
                count_comp=57,
            ),
        )
        session = MagicMock()
        session.post.side_effect = [empty_resp, loose_resp]
        ctx = make_ctx(session)
        result = run_search(ctx, 2590810, "Vox Populi: Poland 2023")
        assert result is None

    def test_colon_strip_fallback_accepts_full_edition(self) -> None:
        """Colon-stripped fallback must still match when the HLTB entry is a
        full edition of the stripped name (name starts with stripped + ':').
        """
        empty_resp = FakeResponse(200, {"data": []})
        full_edition_resp = FakeResponse(
            200,
            hit(
                "Batman: Arkham Asylum",
                144000,
                11111,
                game_type="game",
                comp_100_count=300,
                count_comp=5000,
            ),
        )
        session = MagicMock()
        session.post.side_effect = [empty_resp, full_edition_resp]
        ctx = make_ctx(session)
        result = run_search(ctx, 35140, "Batman: Arkham Asylum")
        assert result is not None
        assert result.game_name == "Batman: Arkham Asylum"
