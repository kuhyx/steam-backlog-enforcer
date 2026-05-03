"""Shared types, constants, and cache I/O for the HLTB integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import logging
from typing import Any

from python_pkg.steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write

logger = logging.getLogger(__name__)

HLTB_CACHE_FILE = CONFIG_DIR / "hltb_cache.json"
MAX_CONCURRENT = 60  # parallel requests to HLTB
_SAVE_INTERVAL = 50  # flush cache to disk every N results
MIN_SIMILARITY = 0.5
HLTB_BASE_URL = "https://howlongtobeat.com"

# Suffixes that indicate a subset release (prologue, demo, etc.).
# Used to avoid preferring "Game - Prologue" over "Game" when both exist.
_SUBSET_SUFFIXES = frozenset(
    {
        "prologue",
        "demo",
        "trial",
        "lite",
        "prelude",
    }
)

# Type for progress callbacks: (done, total, found, game_name)
ProgressCb = Callable[[int, int, int, str], None]


@dataclass
class HLTBResult:
    """Result from a HowLongToBeat lookup."""

    app_id: int
    game_name: str
    completionist_hours: float
    similarity: float
    hltb_game_id: int = 0
    comp_100_count: int = 0
    count_comp: int = 0


@dataclass
class _AuthInfo:
    """HLTB API authentication details."""

    token: str
    hp_key: str = ""
    hp_val: str = ""


def _read_raw_cache() -> dict[int, dict[str, Any]]:
    """Read the persistent HLTB cache, normalizing legacy float entries.

    Cache schema on disk (current):
        {
            "<app_id>": {
                "hours": <float>,
                "polls": <int>,
                "count_comp": <int>
            }
        }

    Legacy format (single float value per app) is migrated transparently.
    """
    if not HLTB_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(HLTB_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt HLTB cache, starting fresh.")
        return {}
    out: dict[int, dict[str, Any]] = {}
    for k, v in data.items():
        try:
            aid = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            out[aid] = {
                "hours": float(v.get("hours", -1)),
                "polls": int(v.get("polls", 0)),
                "count_comp": int(v.get("count_comp", 0)),
            }
        else:
            try:
                out[aid] = {"hours": float(v), "polls": 0, "count_comp": 0}
            except (TypeError, ValueError):
                continue
    return out


def load_hltb_cache() -> dict[int, float]:
    """Load the hours portion of the HLTB cache.

    Returns: dict mapping app_id -> completionist_hours (-1 = no data on HLTB).
    """
    return {aid: v["hours"] for aid, v in _read_raw_cache().items()}


def load_hltb_polls_cache() -> dict[int, int]:
    """Load the polled-completionist-times portion of the HLTB cache.

    Returns: dict mapping app_id -> ``comp_100_count`` (0 = unknown).
    """
    return {aid: v["polls"] for aid, v in _read_raw_cache().items()}


def load_hltb_count_comp_cache() -> dict[int, int]:
    """Load the ``count_comp`` portion of the HLTB cache.

    Returns: dict mapping app_id -> ``count_comp`` (0 = unknown).
    """
    return {aid: v["count_comp"] for aid, v in _read_raw_cache().items()}


def save_hltb_cache(
    cache: dict[int, float],
    polls: dict[int, int] | None = None,
    count_comp: dict[int, int] | None = None,
) -> None:
    """Save the HLTB cache to disk, including confidence metrics."""
    polls = polls or {}
    count_comp = count_comp or {}
    out = {
        str(aid): {
            "hours": hours,
            "polls": polls.get(aid, 0),
            "count_comp": count_comp.get(aid, 0),
        }
        for aid, hours in cache.items()
    }
    try:
        _atomic_write(
            HLTB_CACHE_FILE,
            json.dumps(out, indent=2) + "\n",
        )
    except OSError:
        logger.exception("Failed to save HLTB cache")
