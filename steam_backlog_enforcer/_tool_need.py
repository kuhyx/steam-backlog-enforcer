"""Whether the three Steam tools Proton games lean on are still needed.

Steamworks Common Redistributables, Steam Linux Runtime 4.0 and Proton
Experimental stay in :data:`PROTECTED_APP_IDS`, so no sweep or guard ever
treats them as an unauthorized game. This module names the one case where they
may still go (kuhy's rule): Steam is closed, no steam-game-installer run is
live, ``proton-cachyos-native`` is installed, and every installed game in
every library either is mapped to it or is one Valve runs natively. Native
means no mapping entry (or an empty one), ``linux`` in the app cache's OS list
and no Valve tool pick for the game; DUSK (519860) is one.

An earlier version removed Steam Linux Runtime 4.0 while a game needed it, so
every doubt (a read error, a malformed file, a missing key, an exception)
means "needed". Reads only; config.vdf holds private values, so a reason names
the file or an AppID, never a line of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer import _steam_state
from steam_backlog_enforcer._appinfo_cache import (
    STEAM_PLAY_APP,
    default_path,
    read_apps,
)
from steam_backlog_enforcer._fail_safe import FAIL_SAFE_ERRORS
from steam_backlog_enforcer._protected_apps import PROTECTED_APP_IDS
from steam_backlog_enforcer._steam_client import steam_client_running
from steam_backlog_enforcer._steam_restart_guard import fast_install_running
from steam_backlog_enforcer._vdf_text import VdfNode, lookup, parse_vdf

if TYPE_CHECKING:
    from collections.abc import Iterable

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


def _libraries(steamapps: Path) -> list[tuple[str, Path]] | ToolNeed:
    """Every library's steamapps, keyed as libraryfolders.vdf names them.

    The default library always comes first. A missing libraryfolders.vdf means
    it is the only one; one that exists but cannot be used keeps the tools.
    """
    libraries = [("default", steamapps)]
    folders = steamapps / "libraryfolders.vdf"
    if not folders.exists():
        return libraries
    try:
        text = folders.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return _keep("libraryfolders.vdf unreadable")
    try:
        block = lookup(parse_vdf(text), "libraryfolders")
    except ValueError:
        return _keep("libraryfolders.vdf malformed")
    if not isinstance(block, dict):
        return _keep("libraryfolders.vdf has no libraryfolders block")
    for key, entry in block.items():
        if not key.isdigit():
            continue  # e.g. the old format's "TimeNextStatsReport"
        # Old Steam wrote "1" "<path>"; current Steam a block with "path".
        path = entry if isinstance(entry, str) else lookup(entry, "path")
        if not isinstance(path, str) or not path:
            return _keep(f"library {key} has no path")
        libraries.append((key, Path(path) / "steamapps"))
    return libraries


def _manifests(libraries: Iterable[tuple[str, Path]]) -> list[Path] | ToolNeed:
    """Every appmanifest in *libraries*, or the reason to keep the tools."""
    found: list[Path] = []
    for key, steamapps in libraries:
        # iterdir, not glob: glob reads an unlistable directory as empty,
        # which would read as "no game installed".
        try:
            entries = sorted(steamapps.iterdir())
        except OSError:
            return _keep(f"library {key} steamapps unlistable")
        found += [e for e in entries if _MANIFEST.fullmatch(e.name)]
    return found


@dataclass(frozen=True)
class _Games:
    """How many installed games are covered, and which of them by Valve."""

    count: int
    native: set[int]


def _unmapped(steamapps: Path, mapping: dict[str, VdfNode]) -> ToolNeed | _Games:
    """The reason to keep the tools, or the installed games they may go for."""
    libraries = _libraries(steamapps)
    if isinstance(libraries, ToolNeed):
        return libraries
    manifests = _manifests(libraries)
    if isinstance(manifests, ToolNeed):
        return manifests
    # A library listed twice (the default is usually key "0") counts once.
    games: set[str] = set()
    native: set[int] = set()
    for manifest in manifests:
        try:
            tree = parse_vdf(manifest.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return _keep(f"{manifest.name} unreadable")
        app_id = lookup(tree, "AppState", "appid")
        if not isinstance(app_id, str) or not app_id.isdigit():
            return _keep(f"{manifest.name} has no appid")
        if int(app_id) in PROTECTED_APP_IDS:
            continue
        entry = lookup(mapping, app_id)
        if entry is None or lookup(entry, "name") == "":
            native.add(int(app_id))  # no pick of kuhy's: Valve's default runs it
        elif lookup(entry, "name") != NATIVE_TOOL:
            return _keep(f"AppID={app_id} has no {NATIVE_TOOL} mapping")
        games.add(app_id)
    return _Games(count=len(games), native=native)


def _cache(
    steam_root: Path, app_ids: set[int]
) -> tuple[dict[int, dict[str, VdfNode]], dict[str, VdfNode]] | ToolNeed:
    """The games' appinfo blocks and Valve's pick list, or why they are unusable."""
    try:
        apps = read_apps(default_path(steam_root), {STEAM_PLAY_APP, *app_ids})
    except OSError:
        return _keep("appinfo.vdf unreadable")
    except ValueError:
        return _keep("appinfo.vdf malformed")
    picks = lookup(apps.get(STEAM_PLAY_APP), "extended", "app_mappings")
    if not isinstance(picks, dict):
        return _keep(f"app {STEAM_PLAY_APP} has no app_mappings")
    return apps, picks


def _not_native(steam_root: Path, app_ids: set[int]) -> ToolNeed | None:
    """None when Valve runs each of *app_ids* natively, else why it may not."""
    cache = _cache(steam_root, app_ids)
    if isinstance(cache, ToolNeed):
        return cache
    apps, picks = cache
    for app_id in sorted(app_ids):
        block = apps.get(app_id)
        if block is None:
            return _keep(f"AppID={app_id} not in appinfo.vdf")
        oslist = lookup(block, "common", "oslist")
        if not isinstance(oslist, str) or "linux" not in oslist.split(","):
            return _keep(f"AppID={app_id} has no {NATIVE_TOOL} mapping")
        # A tool pick (a runtime such as Steam Linux Runtime 4.0, or Proton
        # for a broken port) may need the very tools this would remove.
        if str(app_id) in picks or lookup(block, "config", "app_mappings"):
            return _keep(f"AppID={app_id} has a Valve tool mapping")
    return None


def _busy() -> ToolNeed | None:
    """Why Steam's state is not ours to judge right now, if it is not."""
    running = steam_client_running()
    if running is None:
        return _keep("cannot tell whether Steam runs")
    if running:
        return ToolNeed(needed=True, reason="Steam running", deferred=True)
    # The installer closes Steam while it works, and the game it is landing
    # may have no manifest yet. Its /proc scan raising means "cannot tell".
    if fast_install_running():
        return _keep("fast install running")
    return None


def _decide(steamapps: Path) -> ToolNeed:
    busy = _busy()
    if busy is not None:
        return busy
    steam_root = steamapps.parent
    mapping = _compat_mapping(steam_root)
    if isinstance(mapping, ToolNeed):
        return mapping
    games = _unmapped(steamapps, mapping)
    if isinstance(games, ToolNeed):
        return games
    if games.native and (not_native := _not_native(steam_root, games.native)):
        return not_native
    toolmanifest = steam_root / "compatibilitytools.d" / NATIVE_TOOL
    if not (toolmanifest / "toolmanifest.vdf").is_file():
        return _keep(f"{NATIVE_TOOL} toolmanifest.vdf missing")
    # No game installed means no game needs them; the reason says so in the log.
    reason = f"every installed game runs on {NATIVE_TOOL}"
    if games.native:
        reason += " or natively"
    return ToolNeed(needed=False, reason=reason if games.count else "no game installed")


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
