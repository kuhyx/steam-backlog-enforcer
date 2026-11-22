"""Hand-finish the appmanifest, but only when every precondition really holds.

Split out of cli.py so the entry point stays under the repo's 250-line cap.
It patches the manifest Steam (or the backlog enforcer) already wrote, and
writes one from scratch when none exists -- steamcmd, which used to create
it, is no longer run. Either way every precondition is checked first.
"""

from __future__ import annotations

import time
from pathlib import Path

from steam_installer import appinfo, finish_check, manifest_write, recognize, runlog
from steam_installer.library import SteamLibrary


def finish(
    log: runlog.RunLog,
    library: SteamLibrary,
    metadata: appinfo.AppMetadata,
    target: Path,
    depot_plan: appinfo.DepotPlan,
    expected_build_id: str | None,
) -> int:
    logger = log.logger
    manifest_path = library.steamapps / f"appmanifest_{metadata.appid}.acf"

    seed = None
    if manifest_path.is_file():
        app_state = recognize.read_app_state(manifest_path)
    else:
        # Nothing on disk to patch. Build the manifest in memory and write it
        # only once every check below has passed: a StateFlags=4 file left
        # behind by a refused run would make Steam fetch the whole game.
        logger.info("No %s yet -- writing one from scratch.", manifest_path.name)
        seed = manifest_write.seed_app_state(
            metadata.appid, metadata.name, target.name, depot_plan.shared_owner
        )
        app_state = seed
    problems = finish_check.check_ready_to_finish(
        install_dir=target,
        app_state=app_state,
        required_depots=depot_plan.required,
        expected_build_id=expected_build_id,
        expected_manifests=depot_plan.manifests,
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
    # Steam resume the download last time. By this point depotdownloader has
    # already filled common/, so the staged copies are genuinely redundant.
    freed = recognize.clear_steam_staging(library, metadata.appid)
    if freed:
        logger.info("Cleared %.1f GB of now-redundant Steam staging data.", freed / 1e9)

    written = manifest_write.finish_manifest_manually(
        library=library,
        appid=metadata.appid,
        install_dir=target,
        now_unix=int(time.time()),
        dlc_depots=depot_plan.dlc,
        seed=seed,
        # Proven depot by depot, so it outranks whatever the manifest says.
        build_id=(
            expected_build_id
            if finish_check.build_proven(
                recognize.discover_cached_depot_manifests(target),
                depot_plan.required,
                depot_plan.manifests,
            )
            else None
        ),
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
