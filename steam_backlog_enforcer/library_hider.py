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

import asyncio
import json
import logging
import os
import pwd
import shutil
import subprocess
import time
import urllib.request

import websockets

logger = logging.getLogger(__name__)

_CDP_PORT = 8080
_CDP_TIMEOUT = 30
_STEAM_STARTUP_WAIT = 45


# ──────────────────────────────────────────────────────────────
# CDP (Chrome DevTools Protocol) helpers
# ──────────────────────────────────────────────────────────────


def _get_shared_js_ws_url() -> str | None:
    """Query the CDP HTTP endpoint and return the SharedJSContext WS URL."""
    url = f"http://127.0.0.1:{_CDP_PORT}/json"
    try:
        if not url.startswith(("http://", "https://")):
            return None
        with urllib.request.urlopen(url, timeout=5) as resp:
            targets = json.loads(resp.read())
    except (OSError, ValueError):
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
    inner = result.get("result", {}).get("result", {})
    if "exceptionDetails" in result.get("result", {}):
        desc = inner.get("description", "Unknown JS error")
        msg = f"JS evaluation error: {desc}"
        raise RuntimeError(msg)
    value: str = inner.get("value", "")
    return value


# ──────────────────────────────────────────────────────────────
# Ensure Steam is running with devtools port
# ──────────────────────────────────────────────────────────────


def _is_steam_running() -> bool:
    """Check whether any Steam process is alive."""
    pgrep = shutil.which("pgrep") or "/usr/bin/pgrep"
    result = subprocess.run(
        [pgrep, "-x", "steam"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _steam_has_debug_port() -> bool:
    """Check whether steamwebhelper is listening on the CDP port."""
    return _get_shared_js_ws_url() is not None


def _wait_for_cdp_ready() -> bool:
    """Wait up to *_STEAM_STARTUP_WAIT* seconds for CDP to become ready."""
    for _ in range(_STEAM_STARTUP_WAIT):
        if _get_shared_js_ws_url() is not None:
            return True
        time.sleep(1)
    return False


def _wait_for_collections_ready() -> bool:
    """Wait until ``collectionStore`` is fully initialised.

    Right after Steam starts, the CDP port may be open but the
    internal collection data hasn't loaded yet.  Poll a lightweight
    JS check until ``GetCollection`` stops throwing.
    """
    js = (
        "(() => { try { collectionStore.GetCollection('hidden');"
        " return 'ok'; } catch(e) { return 'not_ready'; } })()"
    )
    for _ in range(_STEAM_STARTUP_WAIT):
        try:
            result = _evaluate_js(js)
            if _cdp_result_value(result) == "ok":
                return True
        except RuntimeError:
            pass
        time.sleep(1)
    return False


def _shutdown_steam() -> None:
    """Send ``steam -shutdown`` and wait for the process to exit."""
    real_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
    try:
        _run_as_user(["steam", "-shutdown"], real_user)
    except FileNotFoundError:
        return

    pgrep = shutil.which("pgrep") or "/usr/bin/pgrep"
    for _ in range(30):
        result = subprocess.run(
            [pgrep, "-x", "steam"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return
        time.sleep(1)


def _launch_steam_with_debug() -> None:
    """Launch Steam with CEF debugging enabled."""
    real_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
    _run_as_user(
        [
            "steam",
            "-cef-enable-debugging",
            f"-devtools-port={_CDP_PORT}",
            "-silent",
        ],
        real_user,
    )


def ensure_steam_debug_port() -> None:
    """Make sure Steam is running with the CDP debug port open.

    If Steam is running without the port, it is restarted.
    If Steam is not running, it is launched.
    """
    if _steam_has_debug_port():
        logger.debug("Steam CDP port already available.")
        return

    logger.info("Steam CDP port not available — (re)starting Steam...")
    if _is_steam_running():
        _shutdown_steam()

    _launch_steam_with_debug()

    if not _wait_for_cdp_ready():
        msg = "Timed out waiting for Steam CDP port to become ready"
        raise RuntimeError(msg)
    logger.info("Steam CDP port ready.")

    if not _wait_for_collections_ready():
        msg = "Timed out waiting for Steam collections to initialise"
        raise RuntimeError(msg)
    logger.info("Steam collection store ready.")


# ──────────────────────────────────────────────────────────────
# Hide / unhide logic
# ──────────────────────────────────────────────────────────────


def hide_other_games(
    owned_app_ids: list[int],
    allowed_app_id: int | None,
) -> int:
    """Hide every owned game except *allowed_app_id* in the Steam library.

    Uses the Chrome DevTools Protocol to call
    ``collectionStore.SetAppsAsHidden()`` in Steam's JS context.
    Changes take effect immediately — no restart required.

    Returns the number of games newly hidden.
    """
    ensure_steam_debug_port()

    hide_ids = sorted(aid for aid in owned_app_ids if aid != allowed_app_id)
    if not hide_ids:
        return 0

    ids_json = json.dumps(hide_ids)
    js = f"""
    (() => {{
        const toHide = {ids_json};
        const already = new Set();
        const hidden = collectionStore.GetCollection('hidden');
        if (hidden && hidden.allApps) {{
            for (const app of hidden.allApps) already.add(app.appid);
        }}
        const newIds = toHide.filter(id => !already.has(id));
        if (newIds.length > 0) {{
            collectionStore.SetAppsAsHidden(newIds, true);
        }}
        // Unhide the allowed game if it was hidden.
        const allowedId = {allowed_app_id if allowed_app_id is not None else 'null'};
        if (allowedId !== null && collectionStore.BIsHidden(allowedId)) {{
            collectionStore.SetAppsAsHidden([allowedId], false);
        }}
        return JSON.stringify({{ newlyHidden: newIds.length }});
    }})()
    """

    result = _evaluate_js(js)
    value = _cdp_result_value(result)
    parsed = json.loads(value)
    count: int = parsed["newlyHidden"]
    logger.info("Hidden %d new games via CDP.", count)
    return count


def unhide_all_games(owned_app_ids: list[int]) -> int:
    """Remove all games from the hidden collection.

    Returns the number of games that were unhidden.
    """
    ensure_steam_debug_port()

    json.dumps(sorted(owned_app_ids))
    js = """
    (() => {
        const hidden = collectionStore.GetCollection('hidden');
        if (!hidden || !hidden.allApps) return JSON.stringify({ count: 0 });
        const hiddenIds = hidden.allApps.map(a => a.appid);
        if (hiddenIds.length === 0) return JSON.stringify({ count: 0 });
        collectionStore.SetAppsAsHidden(hiddenIds, false);
        return JSON.stringify({ count: hiddenIds.length });
    })()
    """

    result = _evaluate_js(js)
    value = _cdp_result_value(result)
    parsed = json.loads(value)
    count: int = parsed["count"]
    logger.info("Unhidden %d games via CDP.", count)
    return count


# ──────────────────────────────────────────────────────────────
# Steam restart helper
# ──────────────────────────────────────────────────────────────


def restart_steam() -> None:
    """Gracefully restart the Steam client with CEF debugging enabled."""
    logger.info("Restarting Steam client with debug port...")
    _shutdown_steam()
    _launch_steam_with_debug()

    if not _wait_for_cdp_ready():
        logger.warning("Steam restarted but CDP port not ready.")
    else:
        logger.info("Steam restarted with CDP port ready.")


def _run_as_user(cmd: list[str], user: str | None) -> None:
    """Run a command, dropping to *user* if currently root."""
    if os.geteuid() == 0 and user and user != "root":
        try:
            pw = pwd.getpwnam(user)
            uid = pw.pw_uid
        except KeyError:
            uid = 1000

        dbus_default = f"unix:path=/run/user/{uid}/bus"
        dbus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", dbus_default)
        xauth = os.environ.get("XAUTHORITY", f"/home/{user}/.Xauthority")
        full_cmd = [
            "sudo",
            "-u",
            user,
            "env",
            f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
            f"XAUTHORITY={xauth}",
            f"DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
            *cmd,
        ]
    else:
        full_cmd = cmd

    subprocess.Popen(
        full_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
