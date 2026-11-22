"""The fail-closed preconditions for hand-finishing a manifest.

Split out of recognize.py (250-line cap). Everything here only *reads*; the
write it gates lives in :mod:`manifest_write`.
"""

from __future__ import annotations

from pathlib import Path

from steam_installer import manifest_write, recognize


def check_ready_to_finish(
    install_dir: Path,
    app_state: dict,
    required_depots: set[str],
    expected_build_id: str | None,
    expected_manifests: dict[str, str] | None = None,
) -> list[str]:
    """Reasons the manifest must NOT be hand-finished. Empty list means go ahead.

    Every one of these was a real failure mode: writing StateFlags=4 after a
    steamcmd run that did nothing turned a dead run into a reported success.
    """
    problems: list[str] = []

    # An empty required set would make the depot check below vacuously true and
    # wave through a download that fetched nothing. It means the depot filter
    # matched no depot at all (wrong language or OS for this app), not that
    # there is nothing to install.
    if not required_depots:
        problems.append(
            "no depots match this app for the chosen language/OS -- refusing to "
            "guess that the install is complete"
        )

    cached = recognize.discover_cached_depot_manifests(install_dir)

    # `finish_manifest_manually` drops depots the on-disk manifest lists under
    # SharedDepots, which is a different source of truth from app_info's
    # depotfromapp/sharedinstall. If they disagree it can end up with nothing to
    # install and raise -- and by then clear_steam_staging has already deleted
    # Steam's resumable staging tree. Catch the disagreement here, while
    # refusing is still free.
    shared = app_state.get("SharedDepots")
    shared_ids = set(shared) if isinstance(shared, dict) else set()
    if cached and not (set(cached) - shared_ids):
        problems.append(
            "every cached depot is listed under SharedDepots in the existing "
            "manifest, so there would be nothing to record as installed"
        )

    missing = sorted(required_depots - set(cached))
    if missing:
        problems.append(
            f"depot(s) {', '.join(missing)} have no cached manifest under "
            f"{install_dir}/{recognize.DEPOTDOWNLOADER_DIR} -- the download did not finish"
        )

    expected_manifests = expected_manifests or {}
    stale = sorted(
        depot
        for depot in required_depots & set(cached) & set(expected_manifests)
        if cached[depot] != expected_manifests[depot]
    )
    if stale:
        problems.append(
            f"depot(s) {', '.join(stale)} hold a manifest other than the public "
            "gid in Steam's local app cache -- stale content. depotdownloader "
            "always fetches the current build, so the cache is the stale side: "
            "start Steam once, let it sync, rerun"
        )
    if build_proven(cached, required_depots, expected_manifests):
        # The manifest's buildid only ever stood in for this proof. A stub
        # (StateFlags 1026, buildid 0) that Steam never got to fill in is no
        # reason to refuse content that matches the current build depot by depot.
        if expected_build_id is None:
            problems.append(
                "could not determine the current public build from app info, "
                "so there is no buildid to record"
            )
        return problems + _content_and_steam_problems(install_dir)

    buildid = app_state.get("buildid")
    target = app_state.get("TargetBuildID")
    if not (buildid and buildid != "0") and not (target and target != "0"):
        problems.append(
            "manifest has no usable buildid (both buildid and TargetBuildID are 0) "
            "-- no real build was ever recorded"
        )
    resolved = buildid if buildid and buildid != "0" else target
    if expected_build_id is None:
        # Don't silently skip the comparison: a None here means app_info had no
        # branches.public, so we cannot tell a current build from a stale one.
        problems.append(
            "could not determine the current public build from app info, so the "
            "manifest's buildid cannot be checked"
        )
    elif resolved and resolved != expected_build_id:
        problems.append(
            f"manifest buildid {resolved} != current public build "
            f"{expected_build_id} -- content is for a different build"
        )

    return problems + _content_and_steam_problems(install_dir)


def build_proven(
    cached: dict[str, str], required_depots: set[str], expected: dict[str, str]
) -> bool:
    """Whether every required depot holds the manifest the public branch ships."""
    return bool(required_depots) and all(
        depot in expected and cached.get(depot) == expected[depot]
        for depot in required_depots
    )


def _content_and_steam_problems(install_dir: Path) -> list[str]:
    """The checks that hold however the build was established."""
    problems: list[str] = []
    # Cache *filenames* are not content. Without this, an install dir holding
    # only `.DepotDownloader/<id>_<id>.manifest` and no game files passes every
    # other check and gets written as StateFlags=4 with SizeOnDisk=0.
    if not manifest_write.measure_content_size(install_dir):
        problems.append(
            f"no game content found under {install_dir} (only depotdownloader "
            "cache files) -- nothing was actually installed"
        )

    pids = recognize.steam_client_pids()
    if pids:
        problems.append(
            f"the Steam client is running (pid {', '.join(str(p) for p in pids)}) "
            "and will overwrite the manifest -- close Steam and re-run"
        )

    return problems
