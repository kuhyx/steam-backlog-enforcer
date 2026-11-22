"""What ``--map-installed --apply`` would do, one structured row per game.

``map_installed.run`` logs from these rows and the enforcer's web view serves
them (``GET /api/compat``), so the two can never disagree and nothing ever
parses the log. ``changes`` uses the same :func:`compat_map.keep_reason` that
:func:`compat_map.map_app` uses, so a row says "changes" exactly when apply
would rewrite that game's entry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from steam_installer import appinfo, compat_apply, compat_map, recognize
from steam_installer.library import SteamLibrary, list_libraries

if TYPE_CHECKING:
    from pathlib import Path

# Steam's own compat tools and runtimes are apps too, but not games.
TOOL_TYPES = {"tool", "config"}
NOT_CACHED = "not in Steam's app cache"


@dataclass(frozen=True)
class Row:
    """One game's compat decision.

    Attributes:
        current: The tool config.vdf maps it to; None = unmapped (Valve's default).
        priority: That mapping's priority, None when unmapped.
        decided: The tool after apply; None = Valve's default.
        reasons: Why the decision keeps Valve's default (empty = map it).
        note: Why apply leaves an entry the decision would map ("already
            mapped", or kuhy's own tool "kept: ...").
        map: The decision's verdict.
        changes: Whether apply would rewrite this game's entry.
        cached: Whether Steam's app cache knows the game at all.
    """

    appid: int
    name: str
    current: str | None
    priority: str | None
    decided: str | None
    reasons: tuple[str, ...]
    note: str | None
    map: bool
    changes: bool
    cached: bool

    def to_json(self) -> dict[str, object]:
        """The web contract's ``CompatRow``."""
        data = asdict(self)
        data["app_id"] = data.pop("appid")
        data["reasons"] = list(self.reasons)
        return data


def installed(libraries: list[SteamLibrary]) -> dict[int, dict[str, Any]]:
    """Appid -> AppState for every manifest in every library."""
    found: dict[int, dict[str, Any]] = {}
    for library in libraries:
        for manifest in sorted(library.steamapps.glob("appmanifest_*.acf")):
            appid = manifest.stem.removeprefix("appmanifest_")
            if appid.isdigit():
                found[int(appid)] = recognize.read_app_state(manifest)
    return found


def owned_dlc(app_state: dict[str, Any]) -> bool:
    """Whether the manifest lists an owned DLC depot."""
    depots = app_state.get("InstalledDepots")
    entries = depots.values() if isinstance(depots, dict) else []
    return any(isinstance(entry, dict) and "dlcappid" in entry for entry in entries)


def is_tool(block: dict[str, Any]) -> bool:
    """Whether the app is one of Steam's tools or runtimes, not a game."""
    common = block.get("common")
    kind = common.get("type", "") if isinstance(common, dict) else ""
    return isinstance(kind, str) and kind.lower() in TOOL_TYPES


def _row(
    context: compat_apply.Context,
    appid: int,
    block: dict[str, Any] | None,
    app_state: dict[str, Any],
) -> Row:
    entry = compat_map.current(context.config, appid)
    current = (entry[0] or None) if entry else None
    priority = (entry[1] or None) if entry else None
    if block is None:
        name = app_state.get("name", "")
        return Row(
            appid=appid,
            name=name if isinstance(name, str) else "",
            current=current,
            priority=priority,
            decided=current,
            reasons=(NOT_CACHED,),
            note=None,
            map=False,
            changes=False,
            cached=False,
        )
    decision = context.decide(appid, block, owned_dlc=owned_dlc(app_state))
    held = compat_map.keep_reason(entry) if decision.map else None
    changes = decision.map and held is None
    note = None
    if held is not None:
        note = "already mapped" if held.action == "already" else f"kept: {held.detail}"
    common = block.get("common")
    name = common.get("name", "?") if isinstance(common, dict) else "?"
    return Row(
        appid=appid,
        name=str(name),
        current=current,
        priority=priority,
        decided=compat_map.TOOL if changes else current,
        reasons=tuple(decision.reasons),
        note=note,
        map=decision.map,
        changes=changes,
        cached=True,
    )


def rows(
    steam_root: Path,
    appids: list[int] | None = None,
    context: compat_apply.Context | None = None,
) -> list[Row]:
    """Rows for every installed game, or for exactly *appids* (tools included).

    Raises:
        appinfo.AppInfoError: Steam's app cache cannot be read.
    """
    context = context or compat_apply.Context(steam_root)
    states = installed(list_libraries(steam_root))
    ids = appids if appids is not None else sorted(states)
    blocks = appinfo.cached_blocks(ids)
    return [
        _row(context, appid, blocks.get(appid), states.get(appid, {}))
        for appid in ids
        if appids is not None or appid not in blocks or not is_tool(blocks[appid])
    ]
