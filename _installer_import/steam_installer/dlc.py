"""Owned DLC that ships as an app of its own, fetched next to the base game.

depotdownloader's `-app <game>` run only walks the game's own depot list. DLC
such as Cyberpunk 2077's Phantom Liberty (app 2138330, ~25 GB) keeps its depot
under its own app id, so that run never touches it -- and the Steam client,
restarted onto a manifest without it, then downloaded all 24 GB at its own
pace. Each such DLC now gets a depotdownloader run of its own into the same
install dir, where the manifest step picks its depot up from the cache.

Ownership is left to depotdownloader's licence check. Its refusal is the one
failure that is expected (games list DLC nobody bought); anything else aborts
the install before the manifest is touched, like a failed base download.
"""

from __future__ import annotations

from pathlib import Path

from steam_installer import appinfo, depotdl, runlog


def download_owned(
    appid: int,
    install_dir: Path,
    username: str,
    language: str,
    max_downloads: int,
    log: runlog.RunLog,
) -> appinfo.DepotPlan | None:
    """Download every owned DLC of `appid` that has depots of its own.

    Returns:
        The DLC depots now downloaded -- each credited to its DLC app, with
        its public gid -- or None if a DLC download failed for a reason other
        than not owning it.
    """
    logger = log.logger
    plans = appinfo.get_dlc_plans(appid, language)
    downloaded = appinfo.DepotPlan(required=set(), shared=set())
    for dlc_appid, depots in sorted(plans.items()):
        log.section(f"depotdownloader DLC {dlc_appid}")
        outcome = depotdl.download_dlc(
            dlc_appid=dlc_appid,
            install_dir=install_dir,
            username=username,
            language=language,
            max_downloads=max_downloads,
            logger=logger,
        )
        if outcome is None:
            logger.info("DLC %d is not owned by this account -- skipped.", dlc_appid)
            continue
        if not outcome:
            logger.error(
                "depotdownloader failed for DLC %d -- not touching the manifest.",
                dlc_appid,
            )
            return None
        logger.info("Downloaded DLC %d (depots %s).", dlc_appid, sorted(depots))
        downloaded.required |= set(depots)
        downloaded.dlc.update(dict.fromkeys(depots, str(dlc_appid)))
        downloaded.manifests.update(depots)
    return downloaded
