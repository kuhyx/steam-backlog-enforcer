"""Whether the three Steam tools Proton games lean on are still needed.

Steamworks Common Redistributables, Steam Linux Runtime 4.0 and Proton
Experimental stay in :data:`PROTECTED_APP_IDS`, so no sweep or guard ever
treats them as an unauthorized game. This module names the one case where they
may still go (kuhy's rule): Steam is closed, and every installed game is mapped
to ``proton-cachyos-native``, which is itself installed.

An earlier version removed Steam Linux Runtime 4.0 while a game needed it, so
every doubt (a read error, a malformed file, a missing key, an exception)
means "needed". Reads only; config.vdf holds private values, so a reason names
the file or an AppID, never a line of it.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer import _steam_state
from steam_backlog_enforcer._fail_safe import FAIL_SAFE_ERRORS
from steam_backlog_enforcer._protected_apps import PROTECTED_APP_IDS
from steam_backlog_enforcer._steam_client import steam_client_running
from steam_backlog_enforcer._vdf_text import VdfNode, lookup, parse_vdf

if TYPE_CHECKING:
    from pathlib import Path

STEAM_TOOLS: Final = {
    228980: "Steamworks Common Redistributables",
    4183110: "Steam Linux Runtime 4.0",
    1493710: "Proton Experimental",
}
NATIVE_TOOL: Final = "proton-cachyos-native"
_MAPPING: Final = ("InstallConfigStore", "Software", "Valve", "Steam")
_MANIFEST: Final = re.compile(r"appmanifest_\d+\.acf")


@dataclass(frozen=True)
class ToolNeed:
    """The verdict and its one-line reason; ``deferred`` means Steam runs."""

    needed: bool
    reason: str
    deferred: bool = False


def _keep(reason: str) -> ToolNeed:
    return ToolNeed(needed=True, reason=reason)


def _compat_mapping(steam_root: Path) -> dict[str, VdfNode] | ToolNeed:
    """config.vdf's CompatToolMapping block, or the reason to keep the tools."""
    try:
        text = (steam_root / "config" / "config.vdf").read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return _keep("config.vdf unreadable")
    try:
        tree = parse_vdf(text)
    except ValueError:
        return _keep("config.vdf malformed")
    mapping = lookup(tree, *_MAPPING, "CompatToolMapping")
    if not isinstance(mapping, dict):
        return _keep("config.vdf has no CompatToolMapping")
    return mapping


def _unmapped(steamapps: Path, mapping: dict[str, VdfNode]) -> ToolNeed | int:
    """The reason to keep the tools, or how many installed games are mapped."""
    games = 0
    # iterdir, not glob: glob reads an unlistable directory as empty, which
    # would read as "no game installed".
    for manifest in sorted(steamapps.iterdir()):
        if not _MANIFEST.fullmatch(manifest.name):
            continue
        try:
            tree = parse_vdf(manifest.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return _keep(f"{manifest.name} unreadable")
        app_id = lookup(tree, "AppState", "appid")
        if not isinstance(app_id, str) or not app_id.isdigit():
            return _keep(f"{manifest.name} has no appid")
        if int(app_id) in PROTECTED_APP_IDS:
            continue
        if lookup(mapping, app_id, "name") != NATIVE_TOOL:
            return _keep(f"AppID={app_id} has no {NATIVE_TOOL} mapping")
        games += 1
    return games


def _decide(steamapps: Path) -> ToolNeed:
    running = steam_client_running()
    if running is None:
        return _keep("cannot tell whether Steam runs")
    if running:
        return ToolNeed(needed=True, reason="Steam running", deferred=True)
    steam_root = steamapps.parent
    mapping = _compat_mapping(steam_root)
    if isinstance(mapping, ToolNeed):
        return mapping
    games = _unmapped(steamapps, mapping)
    if isinstance(games, ToolNeed):
        return games
    toolmanifest = steam_root / "compatibilitytools.d" / NATIVE_TOOL
    if not (toolmanifest / "toolmanifest.vdf").is_file():
        return _keep(f"{NATIVE_TOOL} toolmanifest.vdf missing")
    # No game installed means no game needs them; the reason says so in the log.
    reason = (
        f"every installed game runs on {NATIVE_TOOL}" if games else "no game installed"
    )
    return ToolNeed(needed=False, reason=reason)


def tool_need(steamapps: Path | None = None) -> ToolNeed:
    """Decide whether :data:`STEAM_TOOLS` must stay installed.

    Args:
        steamapps: The library to judge; defaults to the canonical
            ``_steam_state.STEAMAPPS_PATH`` (read at call time, so a test
            fixture's redirect holds). Its parent is the Steam root.

    Returns:
        ``needed=False`` only when every condition holds; anything else,
        including an exception, keeps them.
    """
    try:
        return _decide(_steam_state.STEAMAPPS_PATH if steamapps is None else steamapps)
    except FAIL_SAFE_ERRORS as exc:
        return _keep(f"check failed ({type(exc).__name__})")
