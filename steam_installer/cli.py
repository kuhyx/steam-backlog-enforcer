"""Entry point: resolve, confirm, adopt what exists, download, recognize."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from steam_installer import (
    cli_args,
    config,
    deps,
    errors,
    flow,
    ghost,
    map_installed,
    resolve,
    runlog,
    takeover,
    target,
)
from steam_installer.job import Job
from steam_installer.library import find_steam_root, list_libraries, pick_install_target

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Run the installer; return the process exit code."""
    parser = cli_args.build_parser()
    args = parser.parse_args(argv)

    if not (args.repair_ghosts or args.map_installed) and not (
        args.appid or args.target
    ):
        parser.error(
            "provide an AppID, a Steam URL, a game name, "
            "--repair-ghosts or --map-installed"
        )
    map_installed.check_arguments(parser, args)

    literal = target.parse_literal(args.target) if args.target else None
    log = runlog.setup(
        args.appid or (literal[0] if literal else None), verbose=args.verbose
    )
    logger = log.logger
    # Printed up front as well as at the end: if the run dies badly, the path
    # still has to be on screen to copy-paste.
    logger.info("Run log: %s", log.path)
    logger.debug("argv: %s", sys.argv)

    # Any Exception ends in "log it, exit 1" plus the run-log path, as before.
    with errors.CrashGuard(logger, log.path):
        return _run(args, log)
    return 1


def _is_interactive(args: argparse.Namespace) -> bool:
    return sys.stdin.isatty() and not args.yes


def _ask(args: argparse.Namespace, question: str, *, interactive: bool) -> bool:
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


def _describe(
    logger: logging.Logger,
    install_target: Path,
    report: ghost.GhostReport,
    staged: takeover.Staged | None,
) -> int:
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


def _log_error(logger: logging.Logger, exc: Exception) -> None:
    """Log the message alone, with no traceback: these are user errors."""
    logger.log(logging.ERROR, "%s", exc)


def _resolve(
    args: argparse.Namespace, logger: logging.Logger, *, interactive: bool
) -> target.Resolved | int:
    """Resolve the target, or return the exit code for a failure already logged."""
    try:
        deps.require()
        return target.resolve_target(args.target, args.appid, interactive=interactive)
    except deps.DependencyError as exc:
        _log_error(logger, exc)
        return 1
    except (target.TargetError, resolve.ResolveError) as exc:
        _log_error(logger, exc)
        return 2


def _pick_username(
    args: argparse.Namespace, logger: logging.Logger, *, interactive: bool
) -> str | None:
    """Return the Steam username, or None after logging why there is none."""
    try:
        return config.resolve_username(args.username, interactive=interactive)
    except config.ConfigError as exc:
        _log_error(logger, exc)
        return None


def _run(args: argparse.Namespace, log: runlog.RunLog) -> int:
    if args.repair_ghosts:
        return _repair_ghosts(log)
    if args.map_installed:
        return map_installed.run(args, log, find_steam_root())
    return _run_install(args, log)


def _run_install(args: argparse.Namespace, log: runlog.RunLog) -> int:
    logger = log.logger
    interactive = _is_interactive(args)
    resolved = _resolve(args, logger, interactive=interactive)
    if isinstance(resolved, int):
        return resolved

    metadata = resolved.metadata
    logger.info(
        "Confirmed: %s (appid %s, matched by %s)",
        metadata.name,
        metadata.appid,
        resolved.source,
    )

    steam_root = find_steam_root()
    libraries = list_libraries(steam_root)
    install_target = pick_install_target(libraries, metadata.installdir)
    library = next(lib for lib in libraries if lib.common == install_target.parent)
    report = ghost.inspect(library, metadata.appid)
    staged = takeover.find_staged(library, metadata.appid, install_target)

    if args.dry_run:
        return _describe(logger, install_target, report, staged)

    if report.is_ghost and not report.is_warm:
        logger.error(
            "appid %s has a ghost manifest (a fake 'installed' state with nothing "
            "behind it). Clear it first: steam_installer/run.sh --repair-ghosts",
            metadata.appid,
        )
        return 1

    username = _pick_username(args, logger, interactive=interactive)
    if username is None:
        return 1

    logger.info("Install target: %s", install_target)
    if not _ask(args, "Proceed? [y/N]: ", interactive=interactive):
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
        steam_root=steam_root,
        job=Job(
            library=library,
            metadata=metadata,
            install_target=install_target,
            staged=staged,
            username=username,
            language=language,
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
