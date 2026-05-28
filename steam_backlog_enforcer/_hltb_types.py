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
    rush_hours: float = -1
    leisure_100h: float = -1


class _HLTBExtras:
    """Mutable accumulator for HLTB data beyond the core hours cache.

    Passed through the fetch pipeline so callers stay within the 5-arg limit.
    """

    def __init__(
        self,
        count_comp: dict[int, int] | None = None,
        rush: dict[int, float] | None = None,
        leisure_100h: dict[int, float] | None = None,
        hltb_game_id: dict[int, int] | None = None,
    ) -> None:
        """Initialize with optional pre-populated dicts."""
        self.count_comp: dict[int, int] = count_comp if count_comp is not None else {}
        self.rush: dict[int, float] = rush if rush is not None else {}
        self.leisure_100h: dict[int, float] = (
            leisure_100h if leisure_100h is not None else {}
        )
        self.hltb_game_id: dict[int, int] = (
            hltb_game_id if hltb_game_id is not None else {}
        )


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
                "count_comp": <int>,
                "rush_hours": <float>,
                "leisure_100h": <float>,
                "hltb_game_id": <int>
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
                "rush_hours": float(v.get("rush_hours", -1)),
                "leisure_100h": float(v.get("leisure_100h", -1)),
                "hltb_game_id": int(v.get("hltb_game_id", 0)),
            }
        else:
            try:
                out[aid] = {
                    "hours": float(v),
                    "polls": 0,
                    "count_comp": 0,
                    "rush_hours": -1,
                    "leisure_100h": -1,
                    "hltb_game_id": 0,
                }
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


def load_hltb_rush_cache() -> dict[int, float]:
    """Load the rush-hours (avg comp_100 + DLC) portion of the HLTB cache.

    Returns: dict mapping app_id -> rush_hours (-1 = not yet computed).
    """
    return {aid: v["rush_hours"] for aid, v in _read_raw_cache().items()}


def load_hltb_leisure_100h_cache() -> dict[int, float]:
    """Load the leisure-100h (comp_100_h + DLC) portion of the HLTB cache.

    Returns: dict mapping app_id -> leisure_100h (-1 = not yet computed).
    """
    return {aid: v["leisure_100h"] for aid, v in _read_raw_cache().items()}


def load_hltb_game_id_cache() -> dict[int, int]:
    """Load the HLTB game ID portion of the cache.

    Returns: dict mapping app_id -> hltb_game_id (0 = not yet looked up).
    """
    return {aid: v["hltb_game_id"] for aid, v in _read_raw_cache().items()}


def save_hltb_cache(
    cache: dict[int, float],
    polls: dict[int, int] | None = None,
    extras: _HLTBExtras | None = None,
) -> None:
    """Save the HLTB cache to disk, including confidence and stats metrics."""
    polls = polls or {}
    if extras is None:
        extras = _HLTBExtras()
    # Preserve existing per-game data when the caller didn't populate the maps.
    # A partial save (e.g. confidence-only) must not clobber rush/leisure/game-id
    # data that a prior detail fetch already wrote.
    needs_existing = (
        not extras.hltb_game_id or not extras.rush or not extras.leisure_100h
    )
    if needs_existing:
        existing = _read_raw_cache()
        game_id_map: dict[int, int] = extras.hltb_game_id or {
            aid: v["hltb_game_id"] for aid, v in existing.items()
        }
        rush_map: dict[int, float] = extras.rush or {
            aid: v["rush_hours"] for aid, v in existing.items() if v["rush_hours"] > 0
        }
        leisure_map: dict[int, float] = extras.leisure_100h or {
            aid: v["leisure_100h"]
            for aid, v in existing.items()
            if v["leisure_100h"] > 0
        }
    else:
        game_id_map = extras.hltb_game_id
        rush_map = extras.rush
        leisure_map = extras.leisure_100h
    out = {
        str(aid): {
            "hours": hours,
            "polls": polls.get(aid, 0),
            "count_comp": extras.count_comp.get(aid, 0),
            "rush_hours": rush_map.get(aid, -1),
            "leisure_100h": leisure_map.get(aid, -1),
            "hltb_game_id": game_id_map.get(aid, 0),
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
