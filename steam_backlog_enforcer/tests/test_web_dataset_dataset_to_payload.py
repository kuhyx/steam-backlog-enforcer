"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._web_dataset import (
    build_web_dataset,
    dataset_to_payload,
)
from steam_backlog_enforcer.config import State

_PKG = "steam_backlog_enforcer._web_games"
# build_web_dataset itself did not move.
_DATASET_PKG = "steam_backlog_enforcer._web_dataset"


class TestDatasetToPayload:
    """Tests for dataset_to_payload."""

    def test_serializes_to_dict(self) -> None:
        """Test serializes to dict."""
        with (
            patch(f"{_DATASET_PKG}.load_snapshot", return_value=None),
            patch(f"{_PKG}._read_raw_cache", return_value={}),
            patch(f"{_PKG}._load_cache", return_value={}),
        ):
            payload = dataset_to_payload(build_web_dataset(State()))
        assert set(payload) == {
            "games",
            "state",
            "defaults",
            "default_summary",
            "pace_vs_hltb",
            "generated_at",
        }
        assert isinstance(payload["games"], list)
        assert isinstance(payload["state"], dict)
