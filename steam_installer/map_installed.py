"""`--map-installed`: run the compat decision over every installed game.

    steam_installer/run.sh --map-installed             # dry run: write nothing
    steam_installer/run.sh --map-installed --apply     # close Steam, map the safe ones
    steam_installer/run.sh --map-installed --appids 730,10   # any cached app, read-only

The dry run only reads, so it works with Steam open. `--apply` closes Steam
first (it rewrites config.vdf on exit) and restarts it afterwards.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from steam_installer import (
    appinfo,
    compat_apply,
    compat_map,
    flow,
    recognize,
    runlog,
    steamctl,
)
from steam_installer.library import SteamLibrary, list_libraries

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

# Steam's own compat tools and runtimes are apps too, but not games.
TOOL_TYPES = {"tool", "config"}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``--map-installed`` options on *parser*."""
    parser.add_argument(
        "--valve-proton",
        action="store_true",
        help="Keep this game on Valve's default Proton for this run.",
    )
    parser.add_argument(
        "--map-installed",
        action="store_true",
        help="Decide every installed game's compat tool. Dry run unless --apply.",
    )
    parser.add_argument(
        "--apply", action="store_true", help="With --map-installed: write the mappings."
    )
    parser.add_argument(
        "--appids",
        default=None,
        help="With --map-installed: comma-separated app ids to decide instead.",
    )


def check_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Reject option combinations that make no sense."""
    if args.map_installed and args.valve_proton:
        parser.error("--valve-proton goes with an install, not --map-installed")


def _installed(libraries: list[SteamLibrary]) -> dict[int, dict[str, Any]]:
    """Appid -> AppState for every manifest in every library."""
    found: dict[int, dict[str, Any]] = {}
    for library in libraries:
        for manifest in sorted(library.steamapps.glob("appmanifest_*.acf")):
            appid = manifest.stem.removeprefix("appmanifest_")
            if appid.isdigit():
                found[int(appid)] = recognize.read_app_state(manifest)
    return found


def _owned_dlc(app_state: dict[str, Any]) -> bool:
    depots = app_state.get("InstalledDepots")
    entries = depots.values() if isinstance(depots, dict) else []
    return any(isinstance(entry, dict) and "dlcappid" in entry for entry in entries)


def _is_tool(block: dict[str, Any]) -> bool:
    common = block.get("common")
    kind = common.get("type", "") if isinstance(common, dict) else ""
    return isinstance(kind, str) and kind.lower() in TOOL_TYPES


def run(args: argparse.Namespace, log: runlog.RunLog, steam_root: Path) -> int:
    """Decide, and with ``--apply`` write, mappings for installed games."""
    logger = log.logger
    installed = _installed(list_libraries(steam_root))
    if args.appids:
        appids = [int(x) for x in args.appids.split(",") if x.strip().isdigit()]
    else:
        appids = sorted(installed)
    context = compat_apply.Context(steam_root)
    blocks = appinfo.cached_blocks(appids)
    to_map: list[int] = []
    for appid in appids:
        block = blocks.get(appid)
        if block is None:
            logger.info("%s: not in Steam's app cache -- skipped", appid)
            continue
        if _is_tool(block) and not args.appids:
            continue
        name = block.get("common", {}).get("name", "?")
        decision = context.decide(
            appid, block, owned_dlc=_owned_dlc(installed.get(appid, {}))
        )
        line = f"{appid} {name}: {decision.describe()}"
        if decision.map:
            to_map.append(appid)
            current = compat_map.current(context.config, appid)
            if current and current[0] == compat_map.TOOL:
                line += " -- already mapped"
        logger.info("%s", line)
    if not args.apply:
        logger.info("Dry run: nothing written. Rerun with --apply to write.")
        return 0
    return _apply(args, logger, context.config, to_map)


def _apply(
    args: argparse.Namespace, logger: logging.Logger, config: Path, to_map: list[int]
) -> int:
    was_running = flow.prepare_steam(args, logger)
    if was_running is None:
        return 1
    try:
        for appid in to_map:
            compat_apply.report(logger, appid, compat_map.map_app(config, appid))
    except compat_map.CompatMapError as exc:
        logger.log(logging.ERROR, "Mapping stopped: %s", exc)
        return 1
    finally:
        if was_running:
            steamctl.start(logger)
    return 0
