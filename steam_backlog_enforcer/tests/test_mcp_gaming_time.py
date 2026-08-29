"""Tests for the gaming-time MCP tools."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer import _budget_view as budget_view
from steam_backlog_enforcer import _mcp
from steam_backlog_enforcer import _mcp_gaming_time as mcp_gaming_time
from steam_backlog_enforcer import _mcp_server as mcp_server
from steam_backlog_enforcer._playtime_state import PlaytimeState


class TestGetGamingTime:
    def test_reports_unrecorded_state(self) -> None:
        with (
            patch.object(budget_view, "load_state", return_value=None),
            patch.object(budget_view, "mounted_targets", return_value=set()),
        ):
            out = mcp_gaming_time.get_gaming_time()
        assert out["recorded"] is False
        assert out["budget_seconds"] == 8 * 3600

    def test_reports_usage(self) -> None:
        stored = PlaytimeState(day_key="2026-07-27", seconds=100.0)
        with (
            patch.object(budget_view, "load_state", return_value=stored),
            patch.object(budget_view, "mounted_targets", return_value=set()),
        ):
            out = mcp_gaming_time.get_gaming_time()
        assert out["recorded"] is True
        assert out["gaming_day"] == "2026-07-27"
        assert out["seconds_used"] == 100.0
        assert out["seconds_remaining"] == 8 * 3600 - 100.0
        assert out["blocked"] is False

    def test_remaining_never_goes_negative(self) -> None:
        stored = PlaytimeState(day_key="d", seconds=10**9)
        with (
            patch.object(budget_view, "load_state", return_value=stored),
            patch.object(budget_view, "mounted_targets", return_value=set()),
        ):
            out = mcp_gaming_time.get_gaming_time()
        assert out["seconds_remaining"] == 0.0

    def test_lists_masked_launchers(self) -> None:
        stored = PlaytimeState(day_key="d", seconds=1.0, blocked_at=2.0)
        with (
            patch.object(budget_view, "load_state", return_value=stored),
            patch.object(
                budget_view, "mounted_targets", return_value={"/usr/bin/steam"}
            ),
        ):
            out = mcp_gaming_time.get_gaming_time()
        assert out["blocked"] is True
        assert out["masked_launchers"] == ["/usr/bin/steam"]

    def test_leaks_no_secret(self) -> None:
        """No Config secret may cross the MCP boundary."""
        with (
            patch.object(budget_view, "load_state", return_value=None),
            patch.object(budget_view, "mounted_targets", return_value=set()),
        ):
            out = mcp_gaming_time.get_gaming_time()
        assert "steam_api_key" not in out
        assert "steam_id" not in out


class TestResetGamingTime:
    def test_preview_by_default(self) -> None:
        with patch.object(mcp_gaming_time, "release_block") as mock_release:
            out = mcp_gaming_time.reset_gaming_time()
        mock_release.assert_not_called()
        assert out["preview"] is True
        assert out["confirm_required"] is True
        assert out["requires_root"] is True

    def test_confirm_unprivileged_returns_gracefully(self) -> None:
        with (
            patch.object(mcp_gaming_time.os, "geteuid", return_value=1000),
            patch.object(mcp_gaming_time, "release_block") as mock_release,
        ):
            out = mcp_gaming_time.reset_gaming_time(confirm=True)
        mock_release.assert_not_called()
        assert out["ok"] is False
        assert "privileges" in out["reason"]

    def test_confirm_applies_as_root(self) -> None:
        with (
            patch.object(mcp_gaming_time.os, "geteuid", return_value=0),
            patch.object(
                mcp_gaming_time, "release_block", return_value=["/usr/bin/steam"]
            ),
            patch.object(mcp_gaming_time, "save_state") as mock_save,
        ):
            out = mcp_gaming_time.reset_gaming_time(confirm=True)
        mock_save.assert_called_once()
        assert out["applied"] is True
        assert out["released"] == ["/usr/bin/steam"]

    def test_confirm_oserror_returns_gracefully(self) -> None:
        with (
            patch.object(mcp_gaming_time.os, "geteuid", return_value=0),
            patch.object(mcp_gaming_time, "release_block", side_effect=OSError("boom")),
        ):
            out = mcp_gaming_time.reset_gaming_time(confirm=True)
        assert out["ok"] is False
        assert "privileges" in out["reason"]


def test_main_runs_stdio_server() -> None:
    with patch.object(mcp_server.mcp, "run") as run:
        _mcp.main()
    run.assert_called_once_with()
