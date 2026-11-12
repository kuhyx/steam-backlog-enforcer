"""Golden round-trips: the persisted files keep their exact flat bytes.

``Config``, ``State`` and ``PlaytimeState`` group fields into nested
dataclasses, but the files on disk stay flat. A fully populated file written
by the old flat classes must load and save back byte for byte.
"""

from __future__ import annotations

import json
from typing import Any

from steam_backlog_enforcer import _playtime_state, config
from steam_backlog_enforcer._playtime_state import load_state, save_state

CONFIG: dict[str, Any] = {
    "steam_api_key": "KEY",
    "steam_id": "7656",
    "block_store": False,
    "kill_unauthorized_games": False,
    "uninstall_other_games": False,
    "desktop_notifications": False,
    "max_manual_picks": 3,
    "book_ledger_path": "/b.json",
    "workout_status_url": "http://127.0.0.1:1/w",
    "workout_log_path": "/w.json",
    "leetcode_ledger_path": "/l.json",
    "leetcode_status_url": "http://127.0.0.1:2/l",
    "count_launcher_processes": False,
    "counted_processes": [{"id": "osu", "label": "osu!", "names": ["osu!"]}],
    "playtime_enforcement": False,
}

STATE: dict[str, Any] = {
    "current_app_id": 440,
    "current_game_name": "TF2",
    "finished_app_ids": [10, 20],
    "skipped_until": {"30": "2026-11-20T00:00:00+00:00"},
    "enforcement_started_at": "2026-01-01T00:00:00+00:00",
    "manual_pick_app_id": None,
    "manual_pick_game_name": "",
    "manual_pick_started_at": "",
    "manual_picks": [
        {"app_id": 50, "game_name": "Fifty", "started_at": "2026-11-01T00:00:00"}
    ],
    "current_assigned_at": "2026-11-02T00:00:00+00:00",
    "last_assigned_at": {
        "440": "2026-11-02T00:00:00+00:00",
        "50": "2026-11-01T00:00:00",
    },
    "released_at": {"60": "2026-11-03T00:00:00+00:00"},
    "store_unblocked_until": "2026-11-12T10:00:00+00:00",
}

PLAYTIME: dict[str, Any] = {
    "schema_version": 1,
    "day_key": "2026-11-12",
    "seconds": 120.5,
    "last_tick_at": 1700000000.0,
    "blocked_at": 1700000100.0,
    "per_game": {"app:440": 100.0},
    "last_credited_key": "app:440",
    "warned_seconds": [600, 300],
    "budget_seconds": 7200.0,
    "shadow_seconds": 30.0,
    "shadow_budget_seconds": 3600.0,
    "shadow_per_source": {"media": 30.0},
    "shadow_paused_seconds": 5.0,
}


def _flat(data: dict[str, Any]) -> str:
    """The exact bytes the flat classes wrote."""
    return json.dumps(data, indent=2) + "\n"


def test_config_round_trips_byte_for_byte() -> None:
    """A full config.json loads and saves back unchanged."""
    config.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.CONFIG_FILE.write_text(_flat(CONFIG), encoding="utf-8")
    config.Config.load().save()
    assert config.CONFIG_FILE.read_text(encoding="utf-8") == _flat(CONFIG)


def test_config_defaults_keep_the_flat_shape() -> None:
    """A default config writes every flat key, in the old order."""
    config.Config().save()
    saved = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))
    assert list(saved) == list(CONFIG)


def test_state_round_trips_byte_for_byte() -> None:
    """A full state.json loads and saves back unchanged."""
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.STATE_FILE.write_text(_flat(STATE), encoding="utf-8")
    config.State.load().save()
    assert config.STATE_FILE.read_text(encoding="utf-8") == _flat(STATE)


def test_playtime_state_round_trips_byte_for_byte() -> None:
    """A full playtime state file loads and saves back unchanged."""
    path = _playtime_state.state_path(demo=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_flat(PLAYTIME), encoding="utf-8")
    state = load_state(demo=True)
    assert state is not None
    save_state(state, demo=True)
    assert path.read_text(encoding="utf-8") == _flat(PLAYTIME)
