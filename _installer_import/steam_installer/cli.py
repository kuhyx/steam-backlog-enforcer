"""Entry point: resolve -> confirm -> fast download -> make Steam recognize it."""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from steam_installer import appinfo, depotdl, recognize, resolve, runlog
from steam_installer.library import (
    SteamLibrary,
    find_steam_root,
    list_libraries,
    pick_install_target,
)


def _require_tool(name: str, install_hint: str) -> None:
    if shutil.which(name) is None:
        print(f"error: `{name}` not found on PATH. {install_hint}", file=sys.stderr)
        sys.exit(1)


def _resolve_appid(args: argparse.Namespace) -> int:
    """Prefer an explicit --appid; fall back to search, which is best-effort
    (store.steampowered.com is known to reject scripted clients on some
    networks -- see resolve.py). Either way, the final confirmation uses the
    real name from steamcmd's own app info, not whatever the search returned.
    """
    if args.appid is not None:
        return args.appid

    try:
        results = resolve.search(args.name)
    except resolve.SearchUnavailable as exc:
        print(f"Store search unavailable ({exc}).", file=sys.stderr)
        print(
            "Find the numeric AppID yourself (e.g. from the store URL) and pass --appid.",
            file=sys.stderr,
        )
        sys.exit(1)

    chosen = resolve.prompt_confirm(results)
    return chosen.appid


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download an owned Steam game fast, then make Steam recognize it."
    )
    parser.add_argument("name", nargs="?", default=None, help="Game name to search for")
    parser.add_argument(
        "--appid", type=int, default=None, help="Steam AppID (skips search)"
    )
    parser.add_argument("--username", required=True, help="Steam account username")
    parser.add_argument(
        "--language", default=None, help="Language depot to fetch (default: prompts)"
    )
    parser.add_argument(
        "--max-downloads", type=int, default=depotdl.DEFAULT_MAX_DOWNLOADS
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

    if args.appid is None and args.name is None:
        parser.error("provide a game name to search for, or --appid directly")

    log = runlog.setup(args.appid, verbose=args.verbose)
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


def _run(args: argparse.Namespace, log: runlog.RunLog) -> int:
    logger = log.logger

    _require_tool("depotdownloader", "See ~/depotdownloader.")
    if not args.skip_steamcmd:
        _require_tool("steamcmd", "Run: yay -S steamcmd")

    appid = _resolve_appid(args)
    metadata = appinfo.get_metadata(appid)
    logger.info("Confirmed: %s (appid %s)", metadata.name, metadata.appid)
    answer = input("Proceed? [y/N]: ").strip().lower()
    if answer != "y":
        logger.info("Cancelled.")
        return 1

    steam_root = find_steam_root()
    libraries = list_libraries(steam_root)
    target = pick_install_target(libraries, metadata.installdir)
    logger.info("Install target: %s", target)

    language = args.language
    if language is None:
        language = input("Language [english]: ").strip() or "english"

    # Refuse early rather than after an hour of downloading: a live Steam client
    # rewrites the manifest from its own state and discards whatever we write.
    running = recognize.steam_client_pids()
    if running:
        logger.error(
            "The Steam client is running (pid %s). It owns appmanifest_%s.acf and "
            "will overwrite anything this tool writes. Close Steam, then re-run.",
            ", ".join(str(p) for p in running),
            metadata.appid,
        )
        logger.info("Run log (send this): %s", log.path)
        return 1

    depot_plan = appinfo.get_depot_plan(metadata.appid, language)
    expected_build_id = appinfo.get_build_id(metadata.appid)
    log.section("Plan")
    logger.debug("language=%s max_downloads=%s", language, args.max_downloads)
    logger.debug("required depots: %s", sorted(depot_plan.required))
    logger.debug("shared depots:   %s", sorted(depot_plan.shared))
    logger.debug("expected buildid: %s", expected_build_id)

    library = next(lib for lib in libraries if lib.common == target.parent)
    manifest_path = library.steamapps / f"appmanifest_{metadata.appid}.acf"
    log.file_contents("Manifest before run", manifest_path)

    logger.info("Downloading via depotdownloader (fast path)...")
    log.section("depotdownloader")
    returncode = depotdl.download(
        appid=metadata.appid,
        install_dir=target,
        username=args.username,
        language=language,
        max_downloads=args.max_downloads,
        logger=logger,
    )
    if returncode != 0:
        logger.error(
            "depotdownloader failed (exit %d) -- not touching the manifest.", returncode
        )
        logger.info("Run log (send this): %s", log.path)
        return 1

    log.section("depotdownloader cache")
    for depot_id, mid in sorted(
        recognize.discover_cached_depot_manifests(target).items()
    ):
        logger.debug("depot %s -> manifest %s", depot_id, mid)

    recognize.ensure_installdir_correct(library, metadata.appid, target)

    if not args.skip_steamcmd:
        logger.info("Reconciling with steamcmd (validate)...")
        log.section("steamcmd app_update validate")
        result = recognize.run_steamcmd_validate(metadata.appid, args.username, logger)
        log.file_contents("Manifest after steamcmd", manifest_path)

        # Never trust steamcmd's exit code alone -- verify the manifest actually
        # reflects a real install before believing it. A "clean" exit has
        # produced a manifest steamcmd itself hadn't finished updating before.
        if (
            not result.crashed_on_install_script
            and recognize.manifest_reflects_real_install(
                library, metadata.appid, target
            )
        ):
            logger.info("steamcmd finished cleanly -- Steam should show Play.")
            logger.info("Run log: %s", log.path)
            return 0

        if result.crashed_on_install_script:
            logger.info(
                "steamcmd hit the known install-script crash; finishing the manifest manually..."
            )
        else:
            logger.info(
                "steamcmd exited %d but the manifest doesn't reflect a real install; "
                "checking whether it is safe to finish it manually...",
                result.returncode,
            )

    return _finish(
        log,
        library,
        metadata,
        target,
        depot_plan,
        expected_build_id,
        skipped_steamcmd=args.skip_steamcmd,
    )


def _finish(
    log: runlog.RunLog,
    library: SteamLibrary,
    metadata: appinfo.AppMetadata,
    target: Path,
    depot_plan: appinfo.DepotPlan,
    expected_build_id: str | None,
    skipped_steamcmd: bool,
) -> int:
    """Hand-finish the manifest, but only if every precondition really holds."""
    logger = log.logger
    manifest_path = library.steamapps / f"appmanifest_{metadata.appid}.acf"

    if not manifest_path.is_file():
        # Reachable two ways, so don't blame steamcmd unconditionally: under
        # --skip-steamcmd it never runs at all, and nothing else in this tool
        # creates a manifest from scratch.
        logger.error(
            "No %s exists, so there is nothing to finish. This tool only ever "
            "patches a manifest Steam or steamcmd already wrote; it never "
            "fabricates one. %s",
            manifest_path,
            (
                "Re-run without --skip-steamcmd so steamcmd creates it (it writes "
                "one even when it crashes)."
                if skipped_steamcmd
                else "steamcmd writes one even when it crashes, so its absence "
                "means steamcmd never ran far enough."
            ),
        )
        logger.info("Run log (send this): %s", log.path)
        return 1

    app_state = recognize.read_app_state(manifest_path)
    problems = recognize.check_ready_to_finish(
        install_dir=target,
        app_state=app_state,
        required_depots=depot_plan.required,
        expected_build_id=expected_build_id,
    )
    if problems:
        # Fail closed. Writing StateFlags=4 here is what previously turned a
        # steamcmd run that did nothing at all into a reported success.
        logger.error("Refusing to mark %s as installed:", metadata.name)
        for problem in problems:
            logger.error("  - %s", problem)
        logger.info("Run log (send this): %s", log.path)
        return 1

    # Do this before writing the manifest: a StateFlags=4 manifest alongside a
    # staging tree full of pending chunks is the same contradiction that made
    # Steam resume the download last time.
    freed = recognize.clear_steam_staging(library, metadata.appid)
    if freed:
        logger.info("Cleared %.1f GB of stale Steam staging data.", freed / 1e9)

    written = recognize.finish_manifest_manually(
        library=library,
        appid=metadata.appid,
        install_dir=target,
        now_unix=int(time.time()),
    )
    log.file_contents("Manifest after manual finish", written)

    # Re-read from disk: claiming success without checking the write landed is
    # the same fail-open mistake in a different place.
    if not recognize.manifest_reflects_real_install(library, metadata.appid, target):
        logger.error(
            "Wrote %s but it still does not read back as a real install.", written
        )
        logger.info("Run log (send this): %s", log.path)
        return 1

    logger.info("Wrote %s -- launch Steam and confirm Play works.", written)
    logger.info("Run log: %s", log.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
