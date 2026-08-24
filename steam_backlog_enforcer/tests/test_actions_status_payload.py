"""Tests for the stdout-free, state-only cores in ``_actions``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from steam_backlog_enforcer._actions import (
    status_payload,
)
from steam_backlog_enforcer._total_block import TotalBlockStatus
from steam_backlog_enforcer.config import State


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _pick(app_id: int = 440, name: str = "TF2", days_ago: float = 1.0) -> dict:
    return {
        "app_id": app_id,
        "game_name": name,
        "started_at": _iso_days_ago(days_ago),
    }


class TestStatusPayload:
    """Tests for Status Payload."""

    def _patch_leaves(
        self,
        *,
        total_block: TotalBlockStatus,
        installed: list[tuple[int, str]],
        store_blocked: bool,
        protected_ids: set[int],
    ) -> object:
        """Test patch leaves."""
        return patch.multiple(
            "steam_backlog_enforcer._manual_pick_lifecycle",
            get_total_block_status=lambda: total_block,
            get_installed_games=lambda: installed,
            is_store_blocked=lambda: store_blocked,
            is_protected_app=lambda aid: aid in protected_ids,
        )

    def test_assigned_and_installed(self) -> None:
        """Test assigned and installed."""
        block = TotalBlockStatus(
            active=False, started_at=None, until=None, days=0, days_remaining=0.0
        )
        with self._patch_leaves(
            total_block=block,
            installed=[(440, "TF2"), (70, "HL")],
            store_blocked=True,
            protected_ids=set(),
        ):
            payload = status_payload(State(current_app_id=440, current_game_name="TF2"))
        assert payload["current_app_id"] == 440
        assert payload["installed_count"] == 2
        assert payload["assigned_game_installed"] is True
        assert payload["store_blocked"] is True
        assert payload["manual_pick_locked"] is False

    def test_no_assignment_and_protected_filtering(self) -> None:
        """Test no assignment and protected filtering."""
        block = TotalBlockStatus(
            active=True,
            started_at=None,
            until=datetime(2030, 1, 1, tzinfo=timezone.utc),
            days=3,
            days_remaining=2.55,
        )
        with self._patch_leaves(
            total_block=block,
            installed=[(440, "TF2"), (228980, "Steamworks")],
            store_blocked=False,
            protected_ids={228980},
        ):
            payload = status_payload(State())
        assert payload["current_app_id"] is None
        assert payload["current_game_name"] is None
        assert payload["assigned_game_installed"] is None
        # protected app filtered out of the count.
        assert payload["installed_count"] == 1
        assert payload["total_block"]["active"] is True
        assert payload["total_block"]["days_remaining"] == 2.5
        assert payload["total_block"]["until"] == "2030-01-01T00:00:00+00:00"
