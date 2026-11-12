"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from steam_backlog_enforcer._web_dataset import (
    WebDataset,
    WebGame,
    build_web_dataset,
    dataset_to_payload,
)
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.tests._web_dataset_factories import _wg

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

    def test_game_rows_are_served_flat(self) -> None:
        """The HLTB group is inlined: the browser's row keys do not change."""
        dataset = build_web_dataset_with([_wg(rush_hours=3.0)])
        row = dataset_to_payload(dataset)["games"][0]
        assert list(row) == [
            "app_id",
            "name",
            "completion_pct",
            "playtime_minutes",
            "rush_hours",
            "leisure_hours",
            "worst_hours",
            "count_comp",
            "comp_100_count",
            "hltb_game_id",
            "protondb_tier",
            "protondb_trending_tier",
            "protondb_score",
        ]
        assert row["rush_hours"] == 3.0


def build_web_dataset_with(games: list[WebGame]) -> WebDataset:
    """An otherwise empty dataset carrying *games*."""
    with (
        patch(f"{_DATASET_PKG}.load_snapshot", return_value=None),
        patch(f"{_PKG}._read_raw_cache", return_value={}),
        patch(f"{_PKG}._load_cache", return_value={}),
    ):
        return replace(build_web_dataset(State()), games=games)
