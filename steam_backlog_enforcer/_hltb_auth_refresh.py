"""Renew the HLTB auth token during a long, paced search batch.

The token from ``/api/search/site/init`` stops working a few minutes after it
is issued: on 2026-11-08 every search ~3 min in came back 403 while a fresh
token got 200 for the same game. Unpaced batches finished before that; a
paced ~800-game refresh takes 15+ min, so the token is renewed by age.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from steam_backlog_enforcer._hltb_pacing import pause_after_request
from steam_backlog_enforcer._hltb_search_api import _get_auth_info

if TYPE_CHECKING:
    from steam_backlog_enforcer._hltb_search_one import _SearchCtx
    from steam_backlog_enforcer._hltb_types import _AuthInfo

logger = logging.getLogger(__name__)

# Well inside the observed ~3 min lifetime (still valid at ~146 s).
AUTH_MAX_AGE_S = 90.0
# Indirection so tests can drive a fake clock.
_now = time.monotonic


def apply_auth(headers: dict[str, str], auth: _AuthInfo) -> None:
    """Put *auth* into the search request headers, replacing any old values."""
    headers["x-auth-token"] = auth.token
    if auth.hp_key:
        headers["x-hp-key"] = auth.hp_key
        headers["x-hp-val"] = auth.hp_val
    else:
        headers.pop("x-hp-key", None)
        headers.pop("x-hp-val", None)


async def ensure_fresh_auth(ctx: _SearchCtx) -> str | None:
    """Renew ``ctx.auth.info`` once it is too old.

    Returns ``None`` when the auth is usable, else the failure reason. A
    failed renewal trips the breaker: the stale token is never used again.
    """
    if _now() - ctx.auth.issued_at < AUTH_MAX_AGE_S:
        return None
    async with ctx.auth.lock:
        if _now() - ctx.auth.issued_at < AUTH_MAX_AGE_S:
            return None  # another lookup renewed it while we waited
        failures: list[str] = []
        auth = await _get_auth_info(ctx.search_url, ctx.session, failures)
        await pause_after_request()
        if auth is None:
            ctx.breaker.tripped = True
            return f"auth refresh {failures[0] if failures else 'no token'}"
        ctx.auth.info = auth
        apply_auth(ctx.headers, auth)
        ctx.auth.issued_at = _now()
        logger.info("HLTB auth token refreshed.")
        return None
