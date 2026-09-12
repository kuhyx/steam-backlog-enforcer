"""HowLongToBeat integration for estimating game completion times.

Fetches leisure completionist hour estimates from howlongtobeat.com with:
- direct API calls (bypassing the slow howlongtobeatpy per-request setup)
- single shared aiohttp session for all requests
- concurrent requests with configurable concurrency
- live progress reporting via callback
- incremental disk-cache saves so crashes don't lose work
- leisure time (upper-bound play time) from individual game pages
- DLC time aggregation (base game + all DLC leisure times combined)
"""

from __future__ import annotations

import asyncio
import logging
import time

from steam_backlog_enforcer._hltb_search import _fetch_batch, _search_batch
from steam_backlog_enforcer._hltb_types import (
    HLTBResult,
    ProgressCb,
    _HLTBExtras,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Confidence-only batch fetch (no leisure/DLC detail pages)
# ──────────────────────────────────────────────────────────────
async def _fetch_batch_confidence_only(
    games: list[tuple[int, str]],
    cache: dict[int, float],
    polls: dict[int, int],
    progress_cb: ProgressCb | None,
    count_comp: dict[int, int] | None = None,
) -> list[HLTBResult]:
    """Fetch only search-level HLTB data (hours + confidence), no detail pages."""
    extras = _HLTBExtras(count_comp=count_comp if count_comp is not None else {})
    return await _search_batch(games, cache, polls, progress_cb, extras)


def fetch_hltb_times(
    games: list[tuple[int, str]],
    cache: dict[int, float] | None = None,
    polls: dict[int, int] | None = None,
    progress_cb: ProgressCb | None = None,
    extras: _HLTBExtras | None = None,
) -> list[HLTBResult]:
    """Synchronous wrapper: fetch HLTB times for games."""
    if not games:
        return []
    if cache is None:
        cache = {}
    if polls is None:
        polls = {}
    return asyncio.run(
        _fetch_batch(
            games,
            cache,
            polls,
            progress_cb,
            extras=extras,
        )
    )


def fetch_hltb_times_timed(
    games: list[tuple[int, str]],
    cache: dict[int, float],
    polls: dict[int, int],
    progress_cb: ProgressCb | None,
    extras: _HLTBExtras,
) -> float:
    """Run :func:`fetch_hltb_times` into the given caches; return the seconds taken."""
    t0 = time.monotonic()
    fetch_hltb_times(
        games, cache=cache, polls=polls, progress_cb=progress_cb, extras=extras
    )
    return time.monotonic() - t0


def games_per_second(count: int, elapsed: float) -> float:
    """Throughput for a completion log line; 0 when nothing was timed."""
    return count / elapsed if elapsed > 0 else 0


def fetch_hltb_confidence(
    games: list[tuple[int, str]],
    cache: dict[int, float] | None = None,
    polls: dict[int, int] | None = None,
    progress_cb: ProgressCb | None = None,
    count_comp: dict[int, int] | None = None,
) -> list[HLTBResult]:
    """Fetch only HLTB search-level data (hours + confidence metrics)."""
    if not games:
        return []
    if cache is None:
        cache = {}
    if polls is None:
        polls = {}
    if count_comp is None:
        count_comp = {}
    return asyncio.run(
        _fetch_batch_confidence_only(
            games,
            cache,
            polls,
            progress_cb,
            count_comp=count_comp,
        )
    )
