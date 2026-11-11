"""Readers for the playtime history file shared by its test modules."""

from __future__ import annotations

import json
from typing import Any

from steam_backlog_enforcer import _playtime_history as history_mod


def raw() -> dict[str, Any]:
    """The history file as stored, read through the (patched) module path."""
    data: dict[str, Any] = json.loads(
        history_mod.HISTORY_FILE.read_text(encoding="utf-8")
    )
    return data


def stored() -> dict[str, float]:
    """Day totals, with the per-game breakdown unwrapped away."""
    return {day: entry["seconds"] for day, entry in raw()["days"].items()}
