"""Kept games (released, no-lock picks) are visible in every status view.

``pick`` parks the outgoing game as a released pick; it is installed and
playable, so ``status``, ``GET /api/status`` and the web Picks card must list
it (under the active picks) with a way to abandon it.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer import _web_views
from steam_backlog_enforcer._manual_pick_lifecycle import status_payload
from steam_backlog_enforcer._total_block import TotalBlockStatus
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import cmd_status
from steam_backlog_enforcer.tests._main_helpers import STARTED_AT
from steam_backlog_enforcer.tests._web_request import make_request, payload_of

_ACTIVE = {"app_id": 1, "game_name": "Locked", "started_at": STARTED_AT}
_KEPT = {
    "app_id": 2,
    "game_name": "Kept",
    "started_at": STARTED_AT,
    "released_at": STARTED_AT,
}
_NO_BLOCK = TotalBlockStatus(
    active=False, started_at=None, until=None, days=0, days_remaining=0.0
)
_STATUS = "steam_backlog_enforcer.main.status"


def _state() -> State:
    return State(
        current_app_id=3,
        current_game_name="Current",
        manual_picks=[dict(_ACTIVE), dict(_KEPT)],
    )


def test_payload_lists_kept_picks_apart_from_active_ones() -> None:
    with patch.multiple(
        "steam_backlog_enforcer._manual_pick_lifecycle",
        get_total_block_status=lambda: _NO_BLOCK,
        get_installed_games=list,
        is_store_blocked=lambda: True,
        is_protected_app=lambda _aid: False,
    ):
        payload = status_payload(_state())
    assert [p["app_id"] for p in payload["manual_picks"]] == [1]
    assert payload["kept_picks"] == [_KEPT]


def test_status_view_projects_kept_picks() -> None:
    raw = {"assigned_game_installed": True, "manual_picks": [], "kept_picks": [_KEPT]}
    with patch(f"{_web_views.__name__}.status_payload", return_value=raw):
        body = payload_of(_web_views.status_view(make_request()))
    assert body["kept_picks"] == [{"app_id": 2, "name": "Kept"}]


def test_cli_status_lists_kept_games() -> None:
    with (
        patch(f"{_STATUS}.is_store_blocked", return_value=False),
        patch(f"{_STATUS}.get_installed_games", return_value=[]),
        patch(f"{_STATUS}.report_completion", return_value=[]),
        patch(f"{_STATUS}._echo") as mock_echo,
    ):
        cmd_status(Config(), _state())
    output = " ".join(str(c) for c in mock_echo.call_args_list)
    assert "Kept games, no lock (1):" in output
    assert "Kept (AppID=2)" in output
    assert "abandon-pick 2" in output
