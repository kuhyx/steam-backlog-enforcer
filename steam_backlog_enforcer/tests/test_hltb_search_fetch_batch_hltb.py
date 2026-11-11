"""Tests for HLTB search, batch-fetch, and page parsing — part 2."""

from __future__ import annotations

import asyncio

import pytest

from steam_backlog_enforcer._hltb_failures import HLTBUnavailableError
from steam_backlog_enforcer._hltb_search import _fetch_batch
from steam_backlog_enforcer.tests._hltb_search_fakes import hltb_auth_patched


class TestFetchBatchHltb:
    """Tests for _fetch_batch (the hltb version)."""

    def test_no_auth(self) -> None:
        """Test no auth."""
        with (
            hltb_auth_patched(None),
            pytest.raises(HLTBUnavailableError, match="nothing refreshed"),
        ):
            asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))


class TestPickBestEntry:
    """Tests for exact-vs-extended entry choice logic."""
