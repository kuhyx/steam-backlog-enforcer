"""One HLTB game lookup: query each name variant, classify, write the cache.

Split out of :mod:`steam_backlog_enforcer._hltb_search` to keep both files
under the 250-line cap. A failed request never writes a miss: only a lookup
whose every variant answered a clean 200 with nothing usable does.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from http import HTTPStatus
import logging
import time
from typing import Any

import aiohttp

from steam_backlog_enforcer._hltb_auth_refresh import ensure_fresh_auth
from steam_backlog_enforcer._hltb_failures import (
    SKIPPED_AFTER_RATE_LIMIT,
    Breaker,
    exc_reason,
    record_failure,
    record_success,
    status_reason,
)
from steam_backlog_enforcer._hltb_matching import (
    _build_result_from_best,
    _build_search_variants,
)
from steam_backlog_enforcer._hltb_pacing import pause_after_request
from steam_backlog_enforcer._hltb_search_api import (
    _build_search_payload,
    _collect_candidates,
    _pick_best_hltb_entry,
)
from steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
    HLTBResult,
    ProgressCb,
    _AuthInfo,
    _HLTBExtras,
    save_hltb_cache,
)

logger = logging.getLogger(__name__)


@dataclass
class _AuthSlot:
    """The search token, when it was issued (monotonic), its renewal lock."""

    info: _AuthInfo | None = None
    issued_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class _SearchResults:
    """What the lookups record besides hours: polls, extras and failures."""

    polls: dict[int, int] = field(default_factory=dict)
    extras: _HLTBExtras = field(default_factory=_HLTBExtras)
    failed_ids: set[int] = field(default_factory=set)
    """Games whose lookup failed (the breaker reports them by id)."""
    dirty: bool = False
    """Only flush incrementally once something was actually written."""


@dataclass
class _SearchCtx:
    """Shared context for HLTB search requests."""

    session: aiohttp.ClientSession
    search_url: str
    headers: dict[str, str]
    cache: dict[int, float]
    results: _SearchResults = field(default_factory=_SearchResults)
    auth: _AuthSlot = field(default_factory=_AuthSlot)
    counter: dict[str, int] = field(default_factory=dict)
    total: int = 0
    progress_cb: ProgressCb | None = None
    breaker: Breaker = field(default_factory=Breaker)


_Best = tuple[dict[str, Any], float]


def _full_edition_candidates(
    name: str, query_name: str, candidates: list[_Best]
) -> list[_Best]:
    """Drop unrelated entries when ``query_name`` is ``name`` minus a subtitle.

    When we stripped ": subtitle" from the original name to get query_name,
    only keep full-edition entries (those whose HLTB name starts with
    query_name + ":"/"-") or exact name/alias matches.  This prevents "Vox
    Populi" (stripped from "Vox Populi: Poland 2023") from falsely matching
    "Vox Populi Vox Dei 2".
    """
    if ":" not in name or ":" in query_name:
        return candidates
    lower_q = query_name.lower()
    kept: list[_Best] = []
    for entry, sim in candidates:
        game_name = (entry.get("game_name") or "").lower()
        alias = (entry.get("game_alias") or "").lower()
        if lower_q in {game_name, alias} or game_name.startswith(
            (lower_q + ":", lower_q + " -")
        ):
            kept.append((entry, sim))
    return kept


async def _query_variant(
    ctx: _SearchCtx, name: str, query_name: str
) -> tuple[_Best | None, str | None]:
    """Run one search variant.

    Returns ``(best, None)`` on a match, ``(None, None)`` on a clean 200 with
    no usable entry, and ``(None, reason)`` when the request itself failed.
    """
    payload = _build_search_payload(query_name, ctx.auth.info)
    try:
        async with ctx.session.post(
            ctx.search_url, headers=ctx.headers, data=payload
        ) as resp:
            ctx.breaker.note(resp.status)
            if resp.status != HTTPStatus.OK:
                return None, status_reason(resp.status)
            data = await resp.json()
    except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
        ctx.breaker.note(None)
        return None, exc_reason(exc)
    finally:
        await pause_after_request()
    if not isinstance(data, dict):
        return None, "bad JSON"
    candidates = _full_edition_candidates(
        name, query_name, _collect_candidates(query_name, data)
    )
    return _pick_best_hltb_entry(query_name, candidates), None


def _record_outcome(
    ctx: _SearchCtx, app_id: int, result: HLTBResult | None, failure: str | None
) -> None:
    """Write a match or a clean miss; a failed lookup keeps the old entry."""
    if result is not None:
        ctx.cache[app_id] = result.completionist_hours
        ctx.results.polls[app_id] = result.comp_100_count
        ctx.results.extras.count_comp[app_id] = result.count_comp
        if result.hltb_game_id > 0:
            ctx.results.extras.hltb_game_id[app_id] = result.hltb_game_id
        ctx.counter["found"] += 1
        ctx.results.dirty = True
        record_success()
    elif failure is not None:
        ctx.counter["failed"] += 1
        ctx.results.failed_ids.add(app_id)
        record_failure(failure)
    else:
        # Every variant answered cleanly with nothing usable: a real miss.
        ctx.cache[app_id] = -1
        ctx.results.polls[app_id] = 0
        ctx.results.extras.count_comp[app_id] = 0
        ctx.results.dirty = True
        record_success()


async def _search_one(
    sem: asyncio.Semaphore,
    ctx: _SearchCtx,
    app_id: int,
    name: str,
) -> HLTBResult | None:
    """Search HLTB for one game via direct POST, update cache."""
    async with sem:
        result: HLTBResult | None = None
        failure: str | None = None
        for query_name in _build_search_variants(name):
            if ctx.breaker.tripped:
                failure = failure or SKIPPED_AFTER_RATE_LIMIT
                break
            auth_failure = await ensure_fresh_auth(ctx)
            if auth_failure is not None:
                failure = failure or auth_failure
                break
            best, reason = await _query_variant(ctx, name, query_name)
            if best is not None:
                result = _build_result_from_best(app_id, name, query_name, best)
                break
            failure = failure or reason
        if result is None and failure not in {None, SKIPPED_AFTER_RATE_LIMIT}:
            logger.warning(
                "HLTB lookup failed for '%s' (%s), cache kept", name, failure
            )
        _record_outcome(ctx, app_id, result, failure)

        ctx.counter["done"] += 1
        done = ctx.counter["done"]

        # Incremental save every _SAVE_INTERVAL lookups.
        if ctx.results.dirty and not done % _SAVE_INTERVAL:
            save_hltb_cache(ctx.cache, ctx.results.polls, ctx.results.extras)

        # Report progress.
        if ctx.progress_cb is not None:
            ctx.progress_cb(done, ctx.total, ctx.counter["found"], name)

        return result
