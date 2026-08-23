"""Tests for the read-only MCP tools."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer import _mcp_actions as mcp_actions
from steam_backlog_enforcer import _mcp_query as mcp_query
from steam_backlog_enforcer import _mcp_server as mcp_server
from steam_backlog_enforcer.steam_api import GameInfo


def _game(app_id: int, hours: float) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=f"g{app_id}",
        total_achievements=10,
        unlocked_achievements=1,
        playtime_minutes=0,
        completionist_hours=hours,
    )


class TestReadTools:
    def test_get_dataset(self) -> None:
        with (
            patch.object(mcp_query, "State") as state,
            patch.object(mcp_query, "build_web_dataset", return_value="DS") as bwd,
            patch.object(mcp_query, "dataset_to_payload", return_value={"x": 1}) as dtp,
        ):
            assert mcp_query.get_dataset() == {"x": 1}
        bwd.assert_called_once_with(state.load.return_value)
        dtp.assert_called_once_with("DS")

    def test_get_status(self) -> None:
        with (
            patch.object(mcp_query, "State") as state,
            patch.object(mcp_query, "status_payload", return_value={"ok": 1}) as sp,
        ):
            assert mcp_query.get_status() == {"ok": 1}
        sp.assert_called_once_with(state.load.return_value)

    def test_get_stats_subsets_dataset(self) -> None:
        payload = {
            "default_summary": {"qualifying": 3},
            "pace_vs_hltb": None,
            "games": ["ignored"],
        }
        with (
            patch.object(mcp_query, "State"),
            patch.object(mcp_query, "build_web_dataset"),
            patch.object(mcp_query, "dataset_to_payload", return_value=payload),
        ):
            out = mcp_query.get_stats()
        assert out == {"default_summary": {"qualifying": 3}, "pace_vs_hltb": None}


class TestListBacklog:
    def test_no_snapshot_returns_note(self) -> None:
        with patch.object(mcp_query, "load_snapshot", return_value=None):
            out = mcp_query.list_backlog()
        assert out["total"] == 0
        assert out["games"] == []
        assert "note" in out

    def test_sorts_shortest_first_excludes_complete_and_caps(self) -> None:
        snap = [
            {
                "app_id": 440,
                "name": "TF2",
                "total_achievements": 100,
                "unlocked_achievements": 10,
                "completionist_hours": 50.0,
            },
            # complete → excluded
            {
                "app_id": 620,
                "name": "Portal 2",
                "total_achievements": 50,
                "unlocked_achievements": 50,
                "completionist_hours": 20.0,
            },
            {
                "app_id": 70,
                "name": "HL",
                "total_achievements": 10,
                "unlocked_achievements": 1,
                "completionist_hours": 12.0,
            },
            # unknown hours → sorted last
            {
                "app_id": 30,
                "name": "NoHrs",
                "total_achievements": 10,
                "unlocked_achievements": 0,
                "completionist_hours": -1,
            },
        ]
        with patch.object(mcp_query, "load_snapshot", return_value=snap):
            out = mcp_query.list_backlog(limit=2)
        assert out["total"] == 3
        assert out["returned"] == 2
        assert [g["app_id"] for g in out["games"]] == [70, 440]
        assert out["games"][0]["completion_pct"] == 10.0

    def test_negative_limit_returns_none(self) -> None:
        snap = [
            {
                "app_id": 70,
                "name": "HL",
                "total_achievements": 10,
                "unlocked_achievements": 1,
            }
        ]
        with patch.object(mcp_query, "load_snapshot", return_value=snap):
            out = mcp_query.list_backlog(limit=-5)
        assert out["returned"] == 0
        assert out["games"] == []


class TestResolveAndSort:
    def test_resolve_found(self) -> None:
        with patch.object(
            mcp_server, "load_snapshot", return_value=[{"app_id": 440, "name": "TF2"}]
        ):
            assert mcp_actions._resolve_game_name(440) == "TF2"

    def test_resolve_missing(self) -> None:
        with patch.object(
            mcp_server, "load_snapshot", return_value=[{"app_id": 1, "name": "X"}]
        ):
            assert mcp_actions._resolve_game_name(440) is None

    def test_resolve_no_snapshot(self) -> None:
        with patch.object(mcp_query, "load_snapshot", return_value=None):
            assert mcp_actions._resolve_game_name(440) is None

    def test_sort_key_branches(self) -> None:
        assert mcp_query._backlog_sort_key(_game(1, 5.0)) == (0, 5.0)
        assert mcp_query._backlog_sort_key(_game(2, -1)) == (1, 0.0)
