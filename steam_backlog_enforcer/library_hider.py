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
from pathlib import Path
import pwd
import shutil
import subprocess
import time

import requests
import websockets

from steam_backlog_enforcer._steam_state import steam_update_in_progress

logger = logging.getLogger(__name__)

_CDP_PORT = 9222
# NOTE: was 8080, which collided with a different local service (Open WebUI)
# already bound to 0.0.0.0:8080. requests to 127.0.0.1:8080 resolved to that
# service instead of steamwebhelper's CDP endpoint (which only bound
# [::1]:8080), so CDP detection silently never worked. 9222 is the
# conventional Chrome DevTools debug port and was confirmed free.
_CDP_TIMEOUT = 120
_STEAM_STARTUP_WAIT = 45

# Real Steam client binary, as shipped by the distro's `steam` package.
#
# Deliberately NOT probed with shutil.which("steam"): a launcher wrapper on
# $PATH (e.g. /usr/local/bin/steam adding -cef-* flags) keeps `which` truthy
# long after the package itself is gone - as happens when a total block
# uninstalls Steam. Checking the real binary is what actually answers
# "can we launch Steam at all?".
_STEAM_BINARY = "/usr/bin/steam"

# Handles for fire-and-forget launches, kept only so they can be reaped.
_SPAWNED: list[subprocess.Popen[bytes]] = []


class SteamUnavailableError(RuntimeError):
    """Raised when Steam cannot be driven over CDP.

    Covers both "Steam is not installed" and "Steam is installed but never
    opened its debug port". Callers are expected to degrade gracefully rather
    than abort: an unreachable Steam means there is no library to hide, which
    is not a fatal condition for the enforcer.
    """


class SteamUpdateInProgressError(SteamUnavailableError):
    """Raised to defer a Steam restart while a game update is in flight.

    Subclasses :class:`SteamUnavailableError` so existing callers already
    degrade gracefully (skip this pass, retry next loop). Restarting Steam
    mid-update suspends and can corrupt the transfer, so the enforcer waits
    for updates to finish before bouncing Steam to open the CDP port.
    """


def steam_is_installed() -> bool:
    """Return True if the real Steam client binary is present."""
    return Path(_STEAM_BINARY).exists()


# ──────────────────────────────────────────────────────────────
# CDP (Chrome DevTools Protocol) helpers
# ──────────────────────────────────────────────────────────────


def _get_shared_js_ws_url() -> str | None:
    """Query the CDP HTTP endpoint and return the SharedJSContext WS URL."""
    try:
        resp = requests.get(f"http://127.0.0.1:{_CDP_PORT}/json", timeout=5)
        targets = resp.json()
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


def _resolve_desktop_user() -> str | None:
    """Resolve which desktop user owns the Steam/X11 session.

    Prefers the explicit STEAM_ENFORCER_DESKTOP_USER (set by the systemd
    unit, which has no SUDO_USER/USER of its own since it is started
    directly by systemd rather than via `sudo`), then falls back to
    SUDO_USER/USER for interactive `sudo` invocations.
    """
    return (
        os.environ.get("STEAM_ENFORCER_DESKTOP_USER")
        or os.environ.get("SUDO_USER")
        or os.environ.get("USER")
    )


def _shutdown_steam() -> None:
    """Send ``steam -shutdown`` and wait for the process to exit."""
    real_user = _resolve_desktop_user()
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
    real_user = _resolve_desktop_user()
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

    Raises:
        SteamUnavailableError: If Steam is not installed, or is installed but
            never opens its debug port.
    """
    if _steam_has_debug_port():
        logger.debug("Steam CDP port already available.")
        return

    # Bail out before the ~45s launch-and-wait: with no binary to exec there
    # is nothing to wait for, and retrying every pass only burns time and
    # leaves dead processes behind.
    if not steam_is_installed():
        msg = f"Steam is not installed ({_STEAM_BINARY} does not exist)"
        raise SteamUnavailableError(msg)

    logger.info("Steam CDP port not available — (re)starting Steam...")
    if _is_steam_running():
        # Never bounce a running Steam while a game update is downloading or
        # committing: the shutdown suspends it and can leave a partially
        # written install (the root cause of the AoE2 launch crash). Defer and
        # retry on the next enforce pass.
        if steam_update_in_progress():
            msg = (
                "Deferring Steam restart: a game update is in progress. "
                "Restarting now would interrupt and can corrupt it; will "
                "retry once the update settles."
            )
            logger.info(msg)
            raise SteamUpdateInProgressError(msg)
        _shutdown_steam()

    _launch_steam_with_debug()

    if not _wait_for_cdp_ready():
        msg = "Timed out waiting for Steam CDP port to become ready"
        raise SteamUnavailableError(msg)
    logger.info("Steam CDP port ready.")

    if not _wait_for_collections_ready():
        msg = "Timed out waiting for Steam collections to initialise"
        raise SteamUnavailableError(msg)
    logger.info("Steam collection store ready.")


# ──────────────────────────────────────────────────────────────
# Hide / unhide logic
# ──────────────────────────────────────────────────────────────


_HIDE_BATCH_SIZE = 50
_MAX_HIDE_PASSES = 30
_SETTLE_DELAY_MS = 200


def hide_other_games(
    owned_app_ids: list[int],
    allowed_app_id: int | None,
) -> int:
    """Hide every game except *allowed_app_id* in the Steam library.

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

    allowed_js = str(allowed_app_id) if allowed_app_id is not None else "null"
    extra_ids = sorted(aid for aid in owned_app_ids if aid != allowed_app_id)
    extra_json = json.dumps(extra_ids)
    js = f"""
    (async () => {{
        const allowed = {allowed_js};
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
                ? coll.visibleApps.map(a => a.appid).filter(id => id !== allowed)
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

        if (allowed !== null) {{
            await collectionStore.SetAppsAsHidden([allowed], false);
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


# ──────────────────────────────────────────────────────────────
# Steam restart helper
# ──────────────────────────────────────────────────────────────


def restart_steam() -> None:
    """Gracefully restart the Steam client with CEF debugging enabled.

    Skips the restart if a game update is downloading or committing, so the
    update is not interrupted (interrupting it can corrupt the install).
    """
    if steam_update_in_progress():
        logger.warning(
            "Skipping Steam restart — a game update is in progress; "
            "restarting now could corrupt it.",
        )
        return

    logger.info("Restarting Steam client with debug port...")
    _shutdown_steam()
    _launch_steam_with_debug()

    if not _wait_for_cdp_ready():
        logger.warning("Steam restarted but CDP port not ready.")
    else:
        logger.info("Steam restarted with CDP port ready.")


def _reap_spawned() -> None:
    """Clear out previously launched processes that have since exited.

    Launches here are fire-and-forget: Steam is meant to outlive the call, so
    it is never waited on. That leaves any launch which dies immediately - a
    missing binary, a broken wrapper - sitting as a zombie that still carries
    the name ``steam``, which anything scanning /proc reads as "Steam is
    running". Polling the old handles reaps them and retires the name.
    """
    _SPAWNED[:] = [proc for proc in _SPAWNED if proc.poll() is None]


def _run_as_user(cmd: list[str], user: str | None) -> None:
    """Run a command, dropping to *user* if currently root."""
    _reap_spawned()
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

    _SPAWNED.append(
        subprocess.Popen(
            full_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )
