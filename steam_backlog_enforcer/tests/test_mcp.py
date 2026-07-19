"""Tests for the MCP server tools in ``_mcp``.

Tools are patched at the ``_mcp`` module namespace (where the helpers are
imported), keeping each tool's own logic under test while isolating the
already-tested leaf functions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from steam_backlog_enforcer import _mcp
from steam_backlog_enforcer.config import State
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
            patch.object(_mcp, "State") as state,
            patch.object(_mcp, "build_web_dataset", return_value="DS") as bwd,
            patch.object(_mcp, "dataset_to_payload", return_value={"x": 1}) as dtp,
        ):
            assert _mcp.get_dataset() == {"x": 1}
        bwd.assert_called_once_with(state.load.return_value)
        dtp.assert_called_once_with("DS")

    def test_get_status(self) -> None:
        with (
            patch.object(_mcp, "State") as state,
            patch.object(_mcp, "status_payload", return_value={"ok": 1}) as sp,
        ):
            assert _mcp.get_status() == {"ok": 1}
        sp.assert_called_once_with(state.load.return_value)

    def test_get_stats_subsets_dataset(self) -> None:
        payload = {
            "default_summary": {"qualifying": 3},
            "pace_vs_hltb": None,
            "games": ["ignored"],
        }
        with (
            patch.object(_mcp, "State"),
            patch.object(_mcp, "build_web_dataset"),
            patch.object(_mcp, "dataset_to_payload", return_value=payload),
        ):
            out = _mcp.get_stats()
        assert out == {"default_summary": {"qualifying": 3}, "pace_vs_hltb": None}


class TestListBacklog:
    def test_no_snapshot_returns_note(self) -> None:
        with patch.object(_mcp, "load_snapshot", return_value=None):
            out = _mcp.list_backlog()
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
        with patch.object(_mcp, "load_snapshot", return_value=snap):
            out = _mcp.list_backlog(limit=2)
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
        with patch.object(_mcp, "load_snapshot", return_value=snap):
            out = _mcp.list_backlog(limit=-5)
        assert out["returned"] == 0
        assert out["games"] == []


class TestResolveAndSort:
    def test_resolve_found(self) -> None:
        with patch.object(
            _mcp, "load_snapshot", return_value=[{"app_id": 440, "name": "TF2"}]
        ):
            assert _mcp._resolve_game_name(440) == "TF2"

    def test_resolve_missing(self) -> None:
        with patch.object(
            _mcp, "load_snapshot", return_value=[{"app_id": 1, "name": "X"}]
        ):
            assert _mcp._resolve_game_name(440) is None

    def test_resolve_no_snapshot(self) -> None:
        with patch.object(_mcp, "load_snapshot", return_value=None):
            assert _mcp._resolve_game_name(440) is None

    def test_sort_key_branches(self) -> None:
        assert _mcp._backlog_sort_key(_game(1, 5.0)) == (0, 5.0)
        assert _mcp._backlog_sort_key(_game(2, -1)) == (1, 0.0)


class TestPickManualGate:
    def test_not_found(self) -> None:
        with patch.object(_mcp, "load_snapshot", return_value=[]):
            out = _mcp.pick_manual(440)
        assert out["ok"] is False
        assert "not found" in out["reason"]

    def test_preview_does_not_mutate(self) -> None:
        with (
            patch.object(
                _mcp, "load_snapshot", return_value=[{"app_id": 440, "name": "TF2"}]
            ),
            patch.object(_mcp, "apply_manual_pick") as amp,
        ):
            out = _mcp.pick_manual(440)
        assert out["preview"] is True
        assert out["game_name"] == "TF2"
        amp.assert_not_called()

    def test_confirm_applies(self) -> None:
        with (
            patch.object(
                _mcp, "load_snapshot", return_value=[{"app_id": 440, "name": "TF2"}]
            ),
            patch.object(_mcp, "State") as state,
            patch.object(_mcp, "Config") as config,
            patch.object(_mcp, "apply_manual_pick", return_value=None) as amp,
        ):
            out = _mcp.pick_manual(440, confirm=True)
        assert out["applied"] is True
        assert out["app_id"] == 440
        amp.assert_called_once_with(
            state.load.return_value,
            440,
            "TF2",
            max_picks=config.load.return_value.max_manual_picks,
        )


class TestAbandonPickGate:
    """The MCP escape hatch mirrors the CLI grace rules, state-only."""

    def _state(self, *, days_ago: float = 1.0, app_id: int = 440) -> State:
        started = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        return State(
            manual_picks=[
                {"app_id": app_id, "game_name": "TF2", "started_at": started}
            ],
            current_app_id=app_id,
            current_game_name="TF2",
        )

    def test_no_active_pick(self) -> None:
        with patch.object(_mcp.State, "load", return_value=State()):
            out = _mcp.abandon_pick(440)
        assert out["ok"] is False
        assert "No manual pick" in out["reason"]

    def test_wrong_app_id(self) -> None:
        with patch.object(_mcp.State, "load", return_value=self._state()):
            out = _mcp.abandon_pick(999)
        assert out["ok"] is False
        assert "not one of the active manual picks" in out["reason"]

    def test_expired_grace(self) -> None:
        state = self._state(days_ago=_mcp.MANUAL_GRACE_DAYS + 1)
        with patch.object(_mcp.State, "load", return_value=state):
            out = _mcp.abandon_pick(440)
        assert out["ok"] is False
        assert "grace period has expired" in out["reason"]

    def test_preview_does_not_mutate(self) -> None:
        with (
            patch.object(_mcp.State, "load", return_value=self._state()),
            patch.object(_mcp, "abandon_manual_pick") as amp,
        ):
            out = _mcp.abandon_pick(440)
        assert out["preview"] is True
        assert out["game_name"] == "TF2"
        assert out["grace_days_left"] > 0
        amp.assert_not_called()

    def test_confirm_applies(self) -> None:
        state = self._state()
        with (
            patch.object(_mcp.State, "load", return_value=state),
            patch.object(_mcp, "abandon_manual_pick") as amp,
        ):
            out = _mcp.abandon_pick(440, confirm=True)
        assert out["applied"] is True
        assert out["app_id"] == 440
        amp.assert_called_once_with(state, 440)

    def test_refused_at_cap(self) -> None:
        with (
            patch.object(
                _mcp, "load_snapshot", return_value=[{"app_id": 440, "name": "TF2"}]
            ),
            patch.object(_mcp, "State"),
            patch.object(_mcp, "Config"),
            patch.object(_mcp, "apply_manual_pick", return_value="cap reached"),
        ):
            out = _mcp.pick_manual(440, confirm=True)
        assert out["ok"] is False
        assert out["reason"] == "cap reached"


class TestBlockGamingGate:
    def test_invalid_days(self) -> None:
        out = _mcp.block_gaming(0)
        assert out["ok"] is False

    def test_preview(self) -> None:
        out = _mcp.block_gaming(3)
        assert out["preview"] is True
        assert out["requires_root"] is True

    def test_confirm_success(self) -> None:
        with patch.object(_mcp, "start_total_block", return_value=True):
            out = _mcp.block_gaming(3, confirm=True)
        assert out["applied"] is True
        assert out["days"] == 3

    def test_confirm_unprivileged_returns_gracefully(self) -> None:
        with patch.object(_mcp, "start_total_block", return_value=False):
            out = _mcp.block_gaming(3, confirm=True)
        assert out["ok"] is False
        assert "privileges" in out["reason"]

    def test_confirm_oserror_returns_gracefully(self) -> None:
        with patch.object(_mcp, "start_total_block", side_effect=OSError("boom")):
            out = _mcp.block_gaming(3, confirm=True)
        assert out["ok"] is False
        assert "privileges" in out["reason"]


def test_main_runs_stdio_server() -> None:
    with patch.object(_mcp.mcp, "run") as run:
        _mcp.main()
    run.assert_called_once_with()
