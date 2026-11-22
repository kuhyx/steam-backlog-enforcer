"""`--map-installed`: run the compat decision over every installed game.

    steam_installer/run.sh --map-installed             # dry run: write nothing
    steam_installer/run.sh --map-installed --apply     # close Steam, map the safe ones
    steam_installer/run.sh --map-installed --appids 730,10   # any cached app, read-only

The dry run only reads, so it works with Steam open. `--apply` closes Steam
first (it rewrites config.vdf on exit) and restarts it afterwards.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_installer import (
    compat_apply,
    compat_map,
    compat_rows,
    flow,
    runlog,
    steamctl,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


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


def _line(row: compat_rows.Row) -> str:
    """The log line for one decided row (the dry run's report)."""
    verdict = "map" if row.map else f"Valve default: {', '.join(row.reasons)}"
    line = f"{row.appid} {row.name}: {verdict}"
    already = row.map and row.current == compat_map.TOOL
    return line + " -- already mapped" if already else line


def run(args: argparse.Namespace, log: runlog.RunLog, steam_root: Path) -> int:
    """Decide, and with ``--apply`` write, mappings for installed games."""
    logger = log.logger
    appids = None
    if args.appids:
        appids = [int(x) for x in args.appids.split(",") if x.strip().isdigit()]
    context = compat_apply.Context(steam_root)
    decided = compat_rows.rows(steam_root, appids, context)
    for row in decided:
        if row.cached:
            logger.info("%s", _line(row))
        else:
            logger.info("%s: not in Steam's app cache -- skipped", row.appid)
    if not args.apply:
        logger.info("Dry run: nothing written. Rerun with --apply to write.")
        return 0
    to_map = [row.appid for row in decided if row.map]
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
