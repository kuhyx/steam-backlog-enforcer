"""Shared fixtures for the zero-achievement "always allowed" tests."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from steam_backlog_enforcer import _achievement_skip as skip
from steam_backlog_enforcer import config

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

SIMS3 = 47890
ASSIGNED = 1091500
WITH_ACH = 570
STEAM_ID = "76561198009649542"
NOW = 1_000_000_000.0


def write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def confirm_zero(*app_ids: int, steam_id: str = STEAM_ID) -> None:
    """Make the real cache say Steam answered "no achievements" for these."""
    write(config.CONFIG_FILE, {"steam_id": STEAM_ID})
    write(
        skip._cache_file(),
        {"steam_id": steam_id, "checked": {str(a): NOW for a in app_ids}},
    )


def write_snapshot(*app_ids: int) -> None:
    write(
        config.SNAPSHOT_FILE, [{"app_id": a, "total_achievements": 5} for a in app_ids]
    )


def recorder(removed: list[int]) -> Callable[..., bool]:
    """An ``uninstall_game`` stand-in that notes which app was removed."""

    def record(app_id: int, _name: str = "") -> bool:
        removed.append(app_id)
        return True

    return record


def js_list(pattern: str, js: str) -> list[int]:
    match = re.search(pattern, js)
    assert match is not None
    return list(json.loads(match.group(1)))
