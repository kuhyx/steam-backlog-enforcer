"""Refetch paths must not lose polls/count_comp when the refetch writes nothing.

The fetch itself is stubbed to a no-op, which is exactly what a failed HLTB
lookup now does: it leaves the in-memory caches untouched.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from steam_backlog_enforcer import _hltb_confidence, _hltb_types, _scanning_confidence
from steam_backlog_enforcer.steam_api import GameInfo

_ENTRY = {
    "hours": 20.0,
    "polls": 100,
    "count_comp": 500,
    "rush_hours": 15.0,
    "leisure_100h": 30.0,
    "hltb_game_id": 77,
}


def _seed(entries: dict[int, dict[str, float]]) -> None:
    _hltb_types.HLTB_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _hltb_types.HLTB_CACHE_FILE.write_text(
        json.dumps({str(k): v for k, v in entries.items()}), encoding="utf-8"
    )


def _raw() -> dict[str, dict[str, float]]:
    data: dict[str, dict[str, float]] = json.loads(
        _hltb_types.HLTB_CACHE_FILE.read_text(encoding="utf-8")
    )
    return data


def test_refetch_poll_counts_keeps_polls_on_failure() -> None:
    """refetch_poll_counts used to drop the entry and restore only its hours."""
    _seed({1: dict(_ENTRY)})
    with patch.object(_hltb_confidence, "fetch_hltb_confidence"):
        polls = _hltb_confidence.refetch_poll_counts([(1, "Game")])
    assert polls[1] == 100
    assert _raw()["1"] == _ENTRY


def test_confidence_refresh_keeps_entry_on_failure() -> None:
    """The candidate confidence refresh popped hours/polls/count_comp to disk."""
    _seed({1: dict(_ENTRY)})
    game = GameInfo(
        app_id=1,
        name="Game",
        total_achievements=10,
        unlocked_achievements=0,
        playtime_minutes=0,
    )
    with patch.object(_hltb_confidence, "fetch_hltb_confidence"):
        _scanning_confidence._refresh_candidate_confidence_batch([game], force=True)
    assert _raw()["1"] == _ENTRY
    assert (game.comp_100_count, game.count_comp) == (100, 500)


def test_detail_missing_keeps_known_miss_on_failure() -> None:
    """A cached miss (-1) must not vanish from the cache when the refetch fails."""
    miss = dict(
        _ENTRY, hours=-1.0, rush_hours=-1.0, leisure_100h=-1.0, polls=0, count_comp=0
    )
    _seed({1: miss, 2: dict(_ENTRY, rush_hours=-1.0)})
    with patch.object(_hltb_confidence, "fetch_hltb_times_timed", return_value=0.0):
        _hltb_confidence.fetch_hltb_detail_missing([(1, "Gone"), (2, "Known")])
    raw = _raw()
    assert raw["1"]["hours"] == -1
    assert raw["2"]["hours"] == 20.0
    assert raw["2"]["polls"] == 100
