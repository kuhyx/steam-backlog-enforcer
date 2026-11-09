"""Pacing for HLTB requests.

HLTB answers 429 ("Slow your roll!") after about 60 requests in a minute:
unpaced bursts and a 2 req/s run (2026-11-08) both stopped near 60. A full
library refresh is ~800 games, so the single request slot
(``MAX_CONCURRENT``) waits ``REQUEST_INTERVAL_S`` after every request before
the next one goes out: about 55 requests per minute.
"""

from __future__ import annotations

import asyncio

REQUEST_INTERVAL_S = 1.1
# Indirection so tests can drop the wait without touching asyncio itself.
_sleep = asyncio.sleep


async def pause_after_request() -> None:
    """Hold the caller's request slot for the pacing interval."""
    await _sleep(REQUEST_INTERVAL_S)
