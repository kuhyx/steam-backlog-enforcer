"""Orchestrate one install: close Steam, adopt staged bytes, download, recognize.

Split out of cli.py so the entry point stays under the repo's 250-line cap.
The manifest-finishing half lives in `finalize.py`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_installer import (
    appinfo,
    compat_apply,
    depotdl,
    dlc,
    manifest_write,
    recognize,
    runlog,
    steamctl,
    takeover,
)
from steam_installer.finalize import finish

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from steam_installer.job import Job


def prepare_steam(args: argparse.Namespace, logger: logging.Logger) -> bool | None:
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
    except steamctl.SteamStillRunningError as exc:
        logger.log(logging.ERROR, "%s", exc)
        return None


def install(
    *,
    args: argparse.Namespace,
    log: runlog.RunLog,
    steam_root: Path,
    job: Job,
) -> int:
    """Adopt anything Steam already fetched, download the rest, make it count."""
    logger = log.logger
    metadata = job.metadata

    steam_was_running = prepare_steam(args, logger)
    if steam_was_running is None:
        return 1
    try:
        returncode = _download_and_recognize(args, log, job)
        if returncode == 0:
            # Still inside the window where Steam is closed: config.vdf written
            # under a running client is lost when it exits.
            cached = recognize.discover_cached_depot_manifests(job.install_target)
            dlc_depots = appinfo.get_depot_plan(metadata.appid, job.language).dlc
            compat_apply.after_install(
                steam_root,
                metadata.appid,
                owned_dlc=bool(set(dlc_depots) & set(cached)),
                valve_proton=args.valve_proton,
                logger=logger,
            )
        return returncode
    finally:
        if steam_was_running:
            steamctl.start(logger)


def _adopt_staged(log: runlog.RunLog, job: Job) -> None:
    """Hardlink whatever Steam already staged into the install dir."""
    staged = job.staged
    if staged is None:
        return
    logger = log.logger
    log.section("Adopting Steam's staged download")
    logger.info(
        "Steam already staged %.2f GB for this app (%d files). Hardlinking it "
        "into place so depotdownloader verifies instead of refetching.",
        staged.bytes_staged / 1e9,
        staged.file_count,
    )
    job.install_target.mkdir(parents=True, exist_ok=True)
    takeover.adopt(staged, logger)


def _log_plan(
    log: runlog.RunLog, job: Job, depot_plan: appinfo.DepotPlan, max_downloads: int
) -> None:
    """Record what this run is about to fetch, for the run log."""
    logger = log.logger
    log.section("Plan")
    logger.debug("language=%s max_downloads=%s", job.language, max_downloads)
    logger.debug("required depots: %s", sorted(depot_plan.required))
    logger.debug("shared depots:   %s", sorted(depot_plan.shared))
    logger.debug("expected buildid: %s", appinfo.get_build_id(job.metadata.appid))
    manifest_path = job.library.steamapps / f"appmanifest_{job.metadata.appid}.acf"
    log.file_contents("Manifest before run", manifest_path)


def _download_and_recognize(
    args: argparse.Namespace, log: runlog.RunLog, job: Job
) -> int:
    logger = log.logger
    metadata, install_target = job.metadata, job.install_target

    # First thing with Steam closed: whatever happens next, Steam resumes onto
    # this field, and a stub written from the display name ("Baldur's Gate 3")
    # would point it at a folder the download never fills.
    manifest_write.ensure_installdir_correct(
        job.library, metadata.appid, install_target
    )
    _adopt_staged(log, job)
    depot_plan = appinfo.get_depot_plan(metadata.appid, job.language)
    _log_plan(log, job, depot_plan, args.max_downloads)

    logger.info("Downloading via depotdownloader (fast path)...")
    log.section("depotdownloader")
    pull = depotdl.Pull(
        install_dir=install_target,
        username=job.username,
        language=job.language,
        max_downloads=args.max_downloads,
    )
    returncode = depotdl.download(metadata.appid, pull, logger)
    if returncode != 0:
        logger.error(
            "depotdownloader failed (exit %d) -- not touching the manifest.", returncode
        )
        logger.info("Run log (send this): %s", log.path)
        return 1

    logger.info("Checking for owned DLC with depots of its own...")
    dlc_plan = dlc.download_owned(metadata.appid, pull, log)
    if dlc_plan is None:
        logger.info("Run log (send this): %s", log.path)
        return 1
    # Downloaded DLC is part of this install now: the finish gate must find its
    # depot cached at its public gid, and the manifest must credit it to its
    # DLC app.
    depot_plan.required |= dlc_plan.required
    depot_plan.dlc.update(dlc_plan.dlc)
    depot_plan.manifests.update(dlc_plan.manifests)

    log.section("depotdownloader cache")
    for depot_id, mid in sorted(
        recognize.discover_cached_depot_manifests(install_target).items()
    ):
        logger.debug("depot %s -> manifest %s", depot_id, mid)

    return finish(log, job.library, metadata, install_target, depot_plan)
