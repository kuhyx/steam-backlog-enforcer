"""Approved whitelist exceptions stay visible and never count as tampering."""

from __future__ import annotations

import json
import re
from unittest.mock import patch

from steam_backlog_enforcer._scanning_tampering import _legitimately_played
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.library_hider import hide_other_games

PKG = "steam_backlog_enforcer.library_hider"
_EXCEPTION = 3126150
_ASSIGNED = 1091500
_OTHER = 10


def _hide_and_capture(allowed: set[int]) -> tuple[list[int], list[int]]:
    """Run hide_other_games against a fake Steam; return (visible, to_hide)."""
    captured: dict[str, str] = {}

    def fake_eval(js: str) -> dict[str, object]:
        captured["js"] = js
        return {}

    with (
        patch(f"{PKG}.ensure_steam_debug_port"),
        patch(f"{PKG}._evaluate_js", side_effect=fake_eval),
        patch(f"{PKG}._cdp_result_value", return_value='{"totalHidden": 0}'),
        patch(
            f"{PKG}.get_approved_exception_ids",
            return_value=frozenset({_EXCEPTION}),
        ),
    ):
        hide_other_games([_EXCEPTION, _ASSIGNED, _OTHER], allowed)
    visible = re.search(r"new Set\((\[.*?\])\)", captured["js"])
    to_hide = re.search(r"const extraIds = (\[.*?\]);", captured["js"])
    assert visible is not None
    assert to_hide is not None
    return json.loads(visible.group(1)), json.loads(to_hide.group(1))


def test_exception_is_kept_visible() -> None:
    visible, to_hide = _hide_and_capture({_ASSIGNED})
    assert visible == [_ASSIGNED, _EXCEPTION]
    assert to_hide == [_OTHER]


def test_caller_set_is_not_mutated() -> None:
    allowed = {_ASSIGNED}
    _hide_and_capture(allowed)
    assert allowed == {_ASSIGNED}


def test_exception_is_exempt_from_tampering() -> None:
    with patch(
        "steam_backlog_enforcer._scanning_tampering.get_approved_exception_ids",
        return_value=frozenset({_EXCEPTION}),
    ):
        exempt = _legitimately_played(State(current_app_id=_ASSIGNED))
    assert {_EXCEPTION, _ASSIGNED} <= exempt
