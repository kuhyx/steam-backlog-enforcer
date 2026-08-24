"""Tests for hltb module."""

from __future__ import annotations

import json

from steam_backlog_enforcer._hltb_search import _AuthInfo
from steam_backlog_enforcer._hltb_search_api import _build_search_payload


class TestBuildSearchPayload:
    """Tests for _build_search_payload."""

    def test_returns_json(self) -> None:
        """Test returns json."""
        payload = _build_search_payload("Half-Life 2")
        data = json.loads(payload)
        assert data["searchType"] == "games"
        assert data["searchTerms"] == ["Half-Life", "2"]

    def test_with_auth(self) -> None:
        """Test with auth."""
        auth = _AuthInfo("t", "ign_x", "ff")
        payload = _build_search_payload("TF2", auth=auth)
        data = json.loads(payload)
        assert data["ign_x"] == "ff"

    def test_with_auth_no_hp_key(self) -> None:
        """Test with auth no hp key."""
        auth = _AuthInfo("t")
        payload = _build_search_payload("TF2", auth=auth)
        data = json.loads(payload)
        assert "" not in data
