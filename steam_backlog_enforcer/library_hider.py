"""Hide / unhide games in the Steam library via Chrome DevTools Protocol.

Modern Steam clients (2023+) use an internal ``collectionStore`` JS
object running inside the CEF (Chromium Embedded Framework) browser.
Game collections (including "hidden") are synced to Steam Cloud and
can only be reliably modified through this API.

This module connects to Steam's ``SharedJSContext`` page over CDP
(Chrome DevTools Protocol) on a local debug port and evaluates
JavaScript to call ``collectionStore.SetAppsAsHidden()``.

Steam must be running with ``-cef-enable-debugging`` and
``-devtools-port=<PORT>`` for this to work.  If it isn't, the module
will shut Steam down and relaunch it with the required flags.
"""

from __future__ import annotations

import json
import logging

from steam_backlog_enforcer._cdp import _cdp_result_value, _evaluate_js
from steam_backlog_enforcer._steam_errors import (
    SteamUnavailableError,
)
from steam_backlog_enforcer._steam_launch import (
    ensure_steam_debug_port,
    restart_steam,
    steam_is_installed,
)

logger = logging.getLogger(__name__)

# Re-exported: the Steam lifecycle now lives in _steam_launch, but callers
# still import these from here. __all__ stops the linter deleting them.
__all__ = [
    "hide_other_games",
    "restart_steam",
    "steam_is_installed",
    "try_hide_other_games",
    "unhide_all_games",
]

_CDP_PORT = 9222
_CDP_TIMEOUT = 120
_STEAM_STARTUP_WAIT = 45


# ──────────────────────────────────────────────────────────────
# Hide / unhide logic
# ──────────────────────────────────────────────────────────────


_HIDE_BATCH_SIZE = 50
_MAX_HIDE_PASSES = 30
_SETTLE_DELAY_MS = 200


def hide_other_games(
    owned_app_ids: list[int],
    allowed_app_ids: set[int],
) -> int:
    """Hide every game except *allowed_app_ids* in the Steam library.

    Uses the Chrome DevTools Protocol to call
    ``collectionStore.SetAppsAsHidden()`` in Steam's JS context.

    The entire retry loop runs inside a single JS evaluation to avoid
    WebSocket round-trip overhead.  ``SetAppsAsHidden`` is unreliable
    in a single pass for large libraries, so the JS loop retries until
    ``visibleApps`` converges to only the allowed game.

    On the first pass, caller-provided *owned_app_ids* are included to
    cover games that might not yet appear in ``visibleApps`` due to
    stale MobX state.

    Returns the total number of games hidden across all passes.
    """
    ensure_steam_debug_port()

    allowed_json = json.dumps(sorted(allowed_app_ids))
    extra_ids = sorted(aid for aid in owned_app_ids if aid not in allowed_app_ids)
    extra_json = json.dumps(extra_ids)
    js = f"""
    (async () => {{
        const allowed = new Set({allowed_json});
        const coll = collectionStore.allGamesCollection;
        const extraIds = {extra_json};
        let totalHidden = 0;
        const maxPasses = {_MAX_HIDE_PASSES};
        const batchSize = {_HIDE_BATCH_SIZE};

        async function safeHide(ids) {{
            if (ids.length === 0) return 0;
            try {{
                await collectionStore.SetAppsAsHidden(ids, true);
                return ids.length;
            }} catch(e) {{
                if (ids.length === 1) return 0;
                const mid = Math.floor(ids.length / 2);
                return (await safeHide(ids.slice(0, mid))) +
                       (await safeHide(ids.slice(mid)));
            }}
        }}

        for (let pass = 0; pass < maxPasses; pass++) {{
            let visible = coll && coll.visibleApps
                ? coll.visibleApps.map(a => a.appid).filter(id => !allowed.has(id))
                : [];

            if (pass === 0) {{
                const visSet = new Set(visible);
                for (const id of extraIds) {{
                    if (!visSet.has(id)) visible.push(id);
                }}
            }}

            if (visible.length === 0) break;

            for (let i = 0; i < visible.length; i += batchSize) {{
                const batch = visible.slice(i, i + batchSize);
                totalHidden += await safeHide(batch);
            }}

            await new Promise(r => setTimeout(r, {_SETTLE_DELAY_MS}));
        }}

        if (allowed.size > 0) {{
            await collectionStore.SetAppsAsHidden([...allowed], false);
        }}

        return JSON.stringify({{ totalHidden }});
    }})()
    """

    result = _evaluate_js(js)
    value = _cdp_result_value(result)
    parsed = json.loads(value)
    count: int = parsed["totalHidden"]
    logger.info("Hid %d games via CDP.", count)
    return count


def try_hide_other_games(
    owned_app_ids: list[int],
    allowed_app_ids: set[int],
) -> tuple[int, str | None]:
    """Hide other games, degrading gracefully when Steam cannot be driven.

    An unreachable Steam (not running, no debug port) or a deferred restart
    (a game update is in flight) is never fatal: there is simply no library to
    reconcile this pass. Every interactive command should skip and carry on
    rather than abort with a traceback, so this wrapper turns the
    :class:`SteamUnavailableError` family into a return value.

    Stdout-free on purpose — callers phrase the skip message themselves.

    Args:
        owned_app_ids: All owned app ids, used to seed the first hide pass.
        allowed_app_ids: Every game that must stay visible.

    Returns:
        ``(hidden_count, skip_reason)``. ``skip_reason`` is ``None`` when the
        pass ran; otherwise it explains why hiding was skipped and the count
        is 0.
    """
    try:
        return hide_other_games(owned_app_ids, allowed_app_ids), None
    except SteamUnavailableError as exc:
        return 0, str(exc)


def unhide_all_games(owned_app_ids: list[int]) -> int:
    """Remove all games from the hidden collection.

    Returns the number of games that were unhidden.
    """
    ensure_steam_debug_port()

    json.dumps(sorted(owned_app_ids))
    js = """
    (async () => {
        const hidden = collectionStore.GetCollection('hidden');
        if (!hidden || !hidden.allApps) return JSON.stringify({ count: 0 });
        const hiddenIds = hidden.allApps.map(a => a.appid);
        if (hiddenIds.length === 0) return JSON.stringify({ count: 0 });
        await collectionStore.SetAppsAsHidden(hiddenIds, false);
        return JSON.stringify({ count: hiddenIds.length });
    })()
    """

    result = _evaluate_js(js)
    value = _cdp_result_value(result)
    parsed = json.loads(value)
    count: int = parsed["count"]
    logger.info("Unhidden %d games via CDP.", count)
    return count
