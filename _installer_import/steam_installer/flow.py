"""Orchestrate one install: close Steam, adopt staged bytes, download, recognize.

Split out of cli.py so the entry point stays under the repo's 250-line cap.
The manifest-finishing half lives in `finalize.py`.
"""

from __future__ import annotations

from pathlib import Path

from steam_installer import (
    appinfo,
    depotdl,
    recognize,
    runlog,
    steamctl,
    takeover,
)
from steam_installer.finalize import finish
from steam_installer.library import SteamLibrary


def _prepare_steam(args, logger) -> bool | None:
    """Close Steam if it's running. Returns whether it was, or None to abort.

    Steam owns the manifest and is actively writing the staging tree, so it has
    to be out of the way. Closing someone's Steam is not something to do
    silently, so it is confirmed unless --yes was passed.

    The caller's own confirmation gate means we only get here with --yes or on
    a tty, so prompting is always safe at this point.
    """
    if not recognize.steam_client_pids():
        return False
    if not args.yes:
        answer = input("Steam is running and must be closed. Close it now? [y/N]: ")
        if answer.strip().lower() != "y":
            logger.info("Cancelled.")
            return None
    try:
        return steamctl.stop(logger)
    except steamctl.SteamStillRunning as exc:
        logger.error("%s", exc)
        return None


def install(
    *,
    args,
    log: runlog.RunLog,
    library: SteamLibrary,
    metadata: appinfo.AppMetadata,
    install_target: Path,
    staged: takeover.Staged | None,
    username: str,
    language: str,
) -> int:
    """Adopt anything Steam already fetched, download the rest, make it count."""
    logger = log.logger

    steam_was_running = _prepare_steam(args, logger)
    if steam_was_running is None:
        return 1
    try:
        return _download_and_recognize(
            args, log, library, metadata, install_target, staged, username, language
        )
    finally:
        if steam_was_running:
            steamctl.start(logger)


def _download_and_recognize(
    args,
    log: runlog.RunLog,
    library: SteamLibrary,
    metadata: appinfo.AppMetadata,
    install_target: Path,
    staged: takeover.Staged | None,
    username: str,
    language: str,
) -> int:
    logger = log.logger

    if staged is not None:
        log.section("Adopting Steam's staged download")
        logger.info(
            "Steam already staged %.2f GB for this app (%d files). Hardlinking it "
            "into place so depotdownloader verifies instead of refetching.",
            staged.bytes_staged / 1e9,
            staged.file_count,
        )
        install_target.mkdir(parents=True, exist_ok=True)
        takeover.adopt(staged, logger)

    depot_plan = appinfo.get_depot_plan(metadata.appid, language)
    expected_build_id = appinfo.get_build_id(metadata.appid)
    log.section("Plan")
    logger.debug("language=%s max_downloads=%s", language, args.max_downloads)
    logger.debug("required depots: %s", sorted(depot_plan.required))
    logger.debug("shared depots:   %s", sorted(depot_plan.shared))
    logger.debug("expected buildid: %s", expected_build_id)

    manifest_path = library.steamapps / f"appmanifest_{metadata.appid}.acf"
    log.file_contents("Manifest before run", manifest_path)

    logger.info("Downloading via depotdownloader (fast path)...")
    log.section("depotdownloader")
    returncode = depotdl.download(
        appid=metadata.appid,
        install_dir=install_target,
        username=username,
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
        recognize.discover_cached_depot_manifests(install_target).items()
    ):
        logger.debug("depot %s -> manifest %s", depot_id, mid)

    recognize.ensure_installdir_correct(library, metadata.appid, install_target)

    if not args.skip_steamcmd:
        logger.info("Reconciling with steamcmd (validate)...")
        log.section("steamcmd app_update validate")
        result = recognize.run_steamcmd_validate(metadata.appid, username, logger)
        log.file_contents("Manifest after steamcmd", manifest_path)

        # Never trust steamcmd's exit code alone -- verify the manifest actually
        # reflects a real install before believing it. A "clean" exit has
        # produced a manifest steamcmd itself hadn't finished updating before.
        if (
            not result.crashed_on_install_script
            and recognize.manifest_reflects_real_install(
                library, metadata.appid, install_target
            )
        ):
            # The manifest being valid does not mean steamcmd is why. It can
            # already have been correct on arrival while steamcmd failed to even
            # log in -- reporting that as "steamcmd finished cleanly" credits a
            # step that did nothing and hides a real authentication failure.
            if result.returncode == 0:
                logger.info("steamcmd finished cleanly -- Steam should show Play.")
            else:
                logger.warning(
                    "steamcmd exited %d, but %s is already a complete install "
                    "-- leaving it as is. Steam should show Play.",
                    result.returncode,
                    manifest_path.name,
                )
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

    return finish(
        log,
        library,
        metadata,
        install_target,
        depot_plan,
        expected_build_id,
        skipped_steamcmd=args.skip_steamcmd,
    )
