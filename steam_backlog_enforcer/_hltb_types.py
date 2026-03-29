"""Shared types, constants, and cache I/O for the HLTB integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import logging

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


@dataclass
class _AuthInfo:
    """HLTB API authentication details."""

    token: str
    hp_key: str = ""
    hp_val: str = ""


def load_hltb_cache() -> dict[int, float]:
    """Load the persistent HLTB cache from disk.

    Returns: dict mapping app_id -> completionist_hours (-1 = no data on HLTB).
    """
    if HLTB_CACHE_FILE.exists():
        try:
            data = json.loads(HLTB_CACHE_FILE.read_text(encoding="utf-8"))
            return {int(k): float(v) for k, v in data.items()}
        except (json.JSONDecodeError, ValueError, OSError):
            logger.warning("Corrupt HLTB cache, starting fresh.")
    return {}


def save_hltb_cache(cache: dict[int, float]) -> None:
    """Save the HLTB cache to disk."""
    try:
        _atomic_write(
            HLTB_CACHE_FILE,
            json.dumps({str(k): v for k, v in cache.items()}, indent=2) + "\n",
        )
    except OSError:
        logger.exception("Failed to save HLTB cache")
