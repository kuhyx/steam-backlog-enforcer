"""Entry point: resolve -> confirm -> adopt what exists -> fast download -> recognize."""

from __future__ import annotations

import argparse
import sys

from steam_installer import (
    config,
    depotdl,
    deps,
    flow,
    ghost,
    resolve,
    runlog,
    takeover,
    target,
)
from steam_installer.library import find_steam_root, list_libraries, pick_install_target


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download an owned Steam game fast, then make Steam recognize it."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        metavar="TARGET",
        help=(
            "AppID (284160), a Steam URL "
            "(https://steamcommunity.com/app/284160/guides/), or a game name "
            "(BeamNG.drive, or just BeamNG)"
        ),
    )
    parser.add_argument(
        "--appid", type=int, default=None, help="Steam AppID (skips detection)"
    )
    parser.add_argument(
        "--username",
        default=None,
        help="Steam account username (default: $STEAM_USERNAME, then the saved one)",
    )
    parser.add_argument(
        "--language", default=None, help="Language depot to fetch (default: prompts)"
    )
    parser.add_argument(
        "--max-downloads", type=int, default=depotdl.DEFAULT_MAX_DOWNLOADS
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Assume yes for every prompt. Ambiguous names still fail rather than guess.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the target and report what would happen. Changes nothing.",
    )
    parser.add_argument(
        "--repair-ghosts",
        action="store_true",
        help=(
            "Scan every library for the fake 'installed' manifests anonymous "
            "steamcmd leaves behind, and clear them away."
        ),
    )
    parser.add_argument(
        "--skip-steamcmd",
        action="store_true",
        help=(
            "Finish the manifest directly from depotdownloader's own cached data "
            "instead of running steamcmd's app_update. Steamcmd's install-script "
            "step has shown two separate failure modes (a confirmed segfault, "
            "and a silent no-op run); this is the same direct-write approach "
            "already confirmed to work."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show on the console everything that goes to the run log.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.repair_ghosts and args.appid is None and args.target is None:
        parser.error("provide an AppID, a Steam URL, a game name, or --repair-ghosts")

    literal = target.parse_literal(args.target) if args.target else None
    log = runlog.setup(args.appid or (literal[0] if literal else None), args.verbose)
    logger = log.logger
    # Printed up front as well as at the end: if the run dies badly, the path
    # still has to be on screen to copy-paste.
    logger.info("Run log: %s", log.path)
    logger.debug("argv: %s", sys.argv)

    try:
        return _run(args, log)
    except Exception:
        logger.exception("Run failed with an unhandled error")
        logger.info("Run log (send this): %s", log.path)
        return 1


def _is_interactive(args: argparse.Namespace) -> bool:
    return sys.stdin.isatty() and not args.yes


def _ask(args: argparse.Namespace, interactive: bool, question: str) -> bool:
    if args.yes:
        return True
    if not interactive:
        return False
    return input(question).strip().lower() == "y"


def _repair_ghosts(log: runlog.RunLog) -> int:
    """Report every ghost manifest; delete only the ones with nothing behind them."""
    logger = log.logger
    reports = ghost.scan(list_libraries(find_steam_root()))
    if not reports:
        logger.info("No ghost installs found.")
        return 0

    for report in reports:
        logger.info("Ghost: appid %s (%s)", report.appid, report.manifest_path.name)
        for reason in report.reasons:
            logger.info("  - %s", reason)
        if report.is_warm:
            logger.warning(
                "  Steam has %.2f GB staged for this app. Those bytes are a real "
                "partial download, so nothing is deleted -- install it normally "
                "(this tool adopts them) instead of repairing it.",
                report.staging_bytes / 1e9,
            )
            continue
        ghost.repair(report, logger)
    logger.info("Run log: %s", log.path)
    return 0


def _describe(logger, metadata, install_target, report, staged) -> int:
    """--dry-run output: everything the real run would act on, and nothing done."""
    logger.info("Install target: %s", install_target)
    if report.is_ghost:
        logger.warning("This app currently has a GHOST manifest:")
        for reason in report.reasons:
            logger.warning("  - %s", reason)
    if staged is not None:
        logger.info(
            "Steam has %.2f GB staged in %s (%d files) -- these would be adopted, "
            "not re-downloaded.",
            staged.bytes_staged / 1e9,
            staged.staging_dir,
            staged.file_count,
        )
    logger.info("Dry run: nothing was changed.")
    return 0


def _run(args: argparse.Namespace, log: runlog.RunLog) -> int:
    logger = log.logger
    interactive = _is_interactive(args)

    if args.repair_ghosts:
        return _repair_ghosts(log)

    try:
        deps.require(skip_steamcmd=args.skip_steamcmd)
        resolved = target.resolve_target(
            args.target, args.appid, interactive=interactive
        )
    except deps.DependencyError as exc:
        logger.error("%s", exc)
        return 1
    except (target.TargetError, resolve.ResolveError) as exc:
        logger.error("%s", exc)
        return 2

    metadata = resolved.metadata
    logger.info(
        "Confirmed: %s (appid %s, matched by %s)",
        metadata.name,
        metadata.appid,
        resolved.source,
    )

    libraries = list_libraries(find_steam_root())
    install_target = pick_install_target(libraries, metadata.installdir)
    library = next(lib for lib in libraries if lib.common == install_target.parent)
    report = ghost.inspect(library, metadata.appid)
    staged = takeover.find_staged(library, metadata.appid, install_target)

    if args.dry_run:
        return _describe(logger, metadata, install_target, report, staged)

    if report.is_ghost and not report.is_warm:
        logger.error(
            "appid %s has a ghost manifest (a fake 'installed' state with nothing "
            "behind it). Clear it first: ./run.sh --repair-ghosts",
            metadata.appid,
        )
        return 1

    try:
        username = config.resolve_username(args.username, interactive=interactive)
    except config.ConfigError as exc:
        logger.error("%s", exc)
        return 1

    logger.info("Install target: %s", install_target)
    if not _ask(args, interactive, "Proceed? [y/N]: "):
        logger.info("Cancelled (use --yes for a non-interactive run).")
        return 1

    language = args.language
    if language is None:
        language = (
            (input("Language [english]: ").strip() or "english")
            if interactive
            else "english"
        )

    return flow.install(
        args=args,
        log=log,
        library=library,
        metadata=metadata,
        install_target=install_target,
        staged=staged,
        username=username,
        language=language,
    )


if __name__ == "__main__":
    raise SystemExit(main())
