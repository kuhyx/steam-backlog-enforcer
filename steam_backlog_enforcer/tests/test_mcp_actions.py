"""Tests for the mutating MCP tools and their confirm gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from steam_backlog_enforcer import _mcp_actions as mcp_actions
from steam_backlog_enforcer import _mcp_query as mcp_query
from steam_backlog_enforcer.config import State


class TestPickManualGate:
    """The pick_manual tool previews first and applies only on confirm."""

    def test_not_found(self) -> None:
        """A game missing from the snapshot is refused as not found."""
        with patch.object(mcp_query, "load_snapshot", return_value=[]):
            out = mcp_actions.pick_manual(440)
        assert out["ok"] is False
        assert "not found" in out["reason"]

    def test_preview_does_not_mutate(self) -> None:
        """Without confirm the tool only previews the pick."""
        with (
            patch(
                "steam_backlog_enforcer._snapshot.load_snapshot",
                return_value=[{"app_id": 440, "name": "TF2"}],
            ),
            patch("steam_backlog_enforcer._actions.apply_manual_pick") as amp,
        ):
            out = mcp_actions.pick_manual(440)
        assert out["preview"] is True
        assert out["game_name"] == "TF2"
        amp.assert_not_called()

    def test_confirm_applies(self) -> None:
        """With confirm the pick is applied with the configured pick cap."""
        with (
            patch(
                "steam_backlog_enforcer._snapshot.load_snapshot",
                return_value=[{"app_id": 440, "name": "TF2"}],
            ),
            patch.object(mcp_actions, "State") as state,
            patch.object(mcp_actions, "Config") as config,
            patch(
                "steam_backlog_enforcer._actions.apply_manual_pick", return_value=None
            ) as amp,
        ):
            out = mcp_actions.pick_manual(440, confirm=True)
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
        started = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
        return State(
            manual_picks=[
                {"app_id": app_id, "game_name": "TF2", "started_at": started}
            ],
            current_app_id=app_id,
            current_game_name="TF2",
        )

    def test_no_active_pick(self) -> None:
        """With no manual pick there is nothing to abandon."""
        with patch.object(mcp_query.State, "load", return_value=State()):
            out = mcp_actions.abandon_pick(440)
        assert out["ok"] is False
        assert "No manual pick" in out["reason"]

    def test_wrong_app_id(self) -> None:
        """An app id that is not an active pick is refused."""
        with patch.object(mcp_query.State, "load", return_value=self._state()):
            out = mcp_actions.abandon_pick(999)
        assert out["ok"] is False
        assert "not one of the active manual picks" in out["reason"]

    def test_old_pick_is_still_abandonable(self) -> None:
        # Past the deleted 4-day grace window, inside the 14-day lock.
        """An 8-day-old pick can still be abandoned."""
        state = self._state(days_ago=8)
        with (
            patch.object(mcp_query.State, "load", return_value=state),
            patch.object(mcp_actions, "abandon_manual_pick", return_value=True),
        ):
            out = mcp_actions.abandon_pick(440, confirm=True)
        assert out["ok"] is True

    def test_preview_does_not_mutate(self) -> None:
        """Without confirm the tool previews the pick and its age."""
        with (
            patch.object(mcp_query.State, "load", return_value=self._state()),
            patch.object(mcp_actions, "abandon_manual_pick") as amp,
        ):
            out = mcp_actions.abandon_pick(440)
        assert out["preview"] is True
        assert out["game_name"] == "TF2"
        assert out["age_days"] > 0
        amp.assert_not_called()

    def test_confirm_applies(self) -> None:
        """With confirm the pick is abandoned in the loaded state."""
        state = self._state()
        with (
            patch.object(mcp_query.State, "load", return_value=state),
            patch.object(mcp_actions, "abandon_manual_pick") as amp,
        ):
            out = mcp_actions.abandon_pick(440, confirm=True)
        assert out["applied"] is True
        assert out["app_id"] == 440
        amp.assert_called_once_with(state, 440)

    def test_refused_at_cap(self) -> None:
        """A pick refused at the cap reports the refusal reason."""
        with (
            patch(
                "steam_backlog_enforcer._snapshot.load_snapshot",
                return_value=[{"app_id": 440, "name": "TF2"}],
            ),
            patch.object(mcp_actions, "State"),
            patch.object(mcp_actions, "Config"),
            patch(
                "steam_backlog_enforcer._actions.apply_manual_pick",
                return_value="cap reached",
            ),
        ):
            out = mcp_actions.pick_manual(440, confirm=True)
        assert out["ok"] is False
        assert out["reason"] == "cap reached"


class TestBlockGamingGate:
    """The block_gaming tool validates days and needs root to apply."""

    def test_invalid_days(self) -> None:
        """Zero days is refused."""
        out = mcp_actions.block_gaming(0)
        assert out["ok"] is False

    def test_preview(self) -> None:
        """Without confirm the tool previews and says root is needed."""
        out = mcp_actions.block_gaming(3)
        assert out["preview"] is True
        assert out["requires_root"] is True

    def test_confirm_success(self) -> None:
        """A started block reports it was applied for the given days."""
        with patch.object(mcp_actions, "start_total_block", return_value=True):
            out = mcp_actions.block_gaming(3, confirm=True)
        assert out["applied"] is True
        assert out["days"] == 3

    def test_confirm_unprivileged_returns_gracefully(self) -> None:
        """A block refused for privileges is reported, not raised."""
        with patch.object(mcp_actions, "start_total_block", return_value=False):
            out = mcp_actions.block_gaming(3, confirm=True)
        assert out["ok"] is False
        assert "privileges" in out["reason"]

    def test_confirm_oserror_returns_gracefully(self) -> None:
        """An OSError starting the block is reported as missing privileges."""
        with patch.object(
            mcp_actions, "start_total_block", side_effect=OSError("boom")
        ):
            out = mcp_actions.block_gaming(3, confirm=True)
        assert out["ok"] is False
        assert "privileges" in out["reason"]
