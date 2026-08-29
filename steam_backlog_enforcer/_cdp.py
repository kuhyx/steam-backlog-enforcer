"""Chrome DevTools Protocol transport for Steam's embedded browser.

Modern Steam runs its UI in CEF, so collections can only be changed by
evaluating JS inside it. Split out of
:mod:`steam_backlog_enforcer.library_hider` to keep both files under the
250-line cap: this module is pure transport and knows nothing about
collections.
"""

from __future__ import annotations

import asyncio
import json
import logging

import requests
import websockets

logger = logging.getLogger(__name__)

# NOTE: was 8080, which collided with a different local service (Open WebUI)
# already bound to 0.0.0.0:8080. requests to 127.0.0.1:8080 resolved to that
# service instead of steamwebhelper's CDP endpoint (which only bound
# [::1]:8080), so CDP detection silently never worked. 9222 is the
# conventional Chrome DevTools debug port and was confirmed free.
_CDP_PORT = 9222
_CDP_TIMEOUT = 120


# ──────────────────────────────────────────────────────────────
# CDP (Chrome DevTools Protocol) helpers
# ──────────────────────────────────────────────────────────────


def _get_shared_js_ws_url() -> str | None:
    """Query the CDP HTTP endpoint and return the SharedJSContext WS URL."""
    try:
        resp = requests.get(f"http://127.0.0.1:{_CDP_PORT}/json", timeout=5)
        targets = resp.json()
    except OSError, ValueError:
        return None

    for target in targets:
        if target.get("title") == "SharedJSContext":
            ws_url: str = target["webSocketDebuggerUrl"]
            return ws_url
    return None


async def _evaluate_js_async(ws_url: str, expression: str) -> dict:
    """Connect to a CDP WebSocket target and evaluate *expression*."""
    async with websockets.connect(ws_url) as ws:
        msg = json.dumps(
            {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            }
        )
        await ws.send(msg)
        resp = await asyncio.wait_for(ws.recv(), timeout=_CDP_TIMEOUT)
        return json.loads(resp)


def _evaluate_js(expression: str) -> dict:
    """Synchronous wrapper around :func:`_evaluate_js_async`."""
    ws_url = _get_shared_js_ws_url()
    if ws_url is None:
        msg = "SharedJSContext not found on CDP port"
        raise RuntimeError(msg)
    return asyncio.run(_evaluate_js_async(ws_url, expression))


def _cdp_result_value(result: dict) -> str:
    """Extract the return value from a CDP Runtime.evaluate response."""
    outer = result.get("result", {})
    inner = outer.get("result", {})
    if "exceptionDetails" in outer:
        exc_details = outer["exceptionDetails"]
        exc = exc_details.get("exception", {})
        desc = (
            inner.get("description")
            or exc.get("description")
            or exc_details.get("text")
            or repr(exc_details)
        )
        logger.debug("CDP exception details: %s", exc_details)
        msg = f"JS evaluation error: {desc}"
        raise RuntimeError(msg)
    value: str = inner.get("value", "")
    return value
