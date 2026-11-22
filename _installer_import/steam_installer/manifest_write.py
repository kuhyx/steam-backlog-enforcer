"""Every write this tool makes to an appmanifest, and only from verified values.

Split out of recognize.py (250-line cap). The manifest is finished by hand
using ONLY values already verified: the exact manifest IDs from
depotdownloader's own local cache (never guessed), the build those prove, and
the real on-disk size measured directly. When no manifest exists it is
written from scratch with the 15 keys Steam accepted on 2026-11-22.

Do NOT leave the download bookkeeping for Steam to tidy up on its next launch.
An earlier version did, on the belief that Steam self-corrects; it does not. A
manifest that says StateFlags=4 while `BytesDownloaded` still differs from
`BytesToDownload` is self-contradictory, and Steam resolves the contradiction
by discarding the "installed" claim and resuming the download -- 90 GB of it,
in the run that prompted this comment.
"""

from __future__ import annotations

import os
from pathlib import Path

from steam_installer import recognize, vdf
from steam_installer.library import SteamLibrary


def ensure_installdir_correct(
    library: SteamLibrary, appid: int, install_dir: Path
) -> None:
    """Patch a stale `installdir` field before anything else, not just after.

    Confirmed necessary: a prior, unrelated Steam GUI glitch left this app's
    manifest pointing at a different folder name, and relaunching the Steam
    client read that stale field and wiped the correctly-downloaded folder as
    "orphaned" while starting a fresh download into the wrong one. Fixing it
    first, as soon as Steam is closed, closes that window entirely. Does
    nothing if no manifest exists yet: the one written from scratch takes
    installdir from the real install folder.
    """
    manifest_path = library.steamapps / f"appmanifest_{appid}.acf"
    if not manifest_path.is_file():
        return
    data = vdf.parse(manifest_path.read_text())
    app_state = data.get("AppState", {})
    if not isinstance(app_state, dict):
        return
    if app_state.get("installdir") == install_dir.name:
        return
    app_state["installdir"] = install_dir.name
    backup_once(manifest_path)
    write_atomic(manifest_path, vdf.dumps("AppState", app_state))


def measure_content_size(install_dir: Path) -> int:
    """Bytes of real game content, excluding depotdownloader's own cache/staging.

    `.DepotDownloader/` holds manifests and a staging tree that Steam knows
    nothing about; counting them overstates SizeOnDisk by gigabytes.
    """
    total = 0
    for entry in install_dir.rglob("*"):
        if recognize.DEPOTDOWNLOADER_DIR in entry.parts:
            continue
        if entry.is_file() and not entry.is_symlink():
            total += entry.stat().st_size
    return total


def seed_app_state(
    appid: int, name: str, installdir: str, shared_owner: dict[str, str]
) -> dict:
    """The skeleton of a from-scratch manifest, in the key order Steam writes.

    These 15 keys are the proven minimum: Steam logged "Fully Installed,App
    Running", queued no download and added LastOwner, UserConfig and the rest
    itself. Placeholders here are overwritten by `finish_manifest_manually`.
    SharedDepots is only added for a game that has some (fixture-tested only).
    """
    state: dict = {
        "appid": str(appid),
        "universe": "1",
        "name": name,
        "StateFlags": "4",
        "installdir": installdir,
        "LastUpdated": "0",
        "SizeOnDisk": "0",
        "StagingSize": "0",
        "buildid": "0",
        "UpdateResult": "0",
        # All four at 0: counters that disagree made Steam download a game again.
        "BytesToDownload": "0",
        "BytesDownloaded": "0",
        "BytesToStage": "0",
        "BytesStaged": "0",
        "InstalledDepots": {},
    }
    if shared_owner:
        state["SharedDepots"] = dict(shared_owner)
    return state


def finish_manifest_manually(
    library: SteamLibrary,
    appid: int,
    install_dir: Path,
    now_unix: int,
    dlc_depots: dict[str, str] | None = None,
    build_id: str | None = None,
    seed: dict | None = None,
) -> Path:
    """Patch appmanifest_<appid>.acf to StateFlags=4 using only verified-known values.

    Patches the manifest on disk, or -- when there is none -- writes `seed`
    (from :func:`seed_app_state`) instead. With neither it refuses.

    `dlc_depots` maps a DLC depot to its DLC app id. Steam's own manifests
    record each DLC depot with that `dlcappid`, so it is written the same way.
    `build_id`, when given, is a build the caller proved from the cached depot
    manifests; it replaces the one Steam recorded.
    """
    manifest_path = library.steamapps / f"appmanifest_{appid}.acf"
    existed = manifest_path.is_file()
    if not existed and seed is None:
        raise recognize.RecognizeError(
            f"No existing {manifest_path.name} to finish and no seed to write"
        )
    app_state = (
        vdf.parse(manifest_path.read_text()).get("AppState", {}) if existed else seed
    )
    if not isinstance(app_state, dict):
        raise recognize.RecognizeError(
            f"{manifest_path} is not a valid AppState manifest"
        )

    depot_manifests = recognize.discover_cached_depot_manifests(install_dir)
    if not depot_manifests:
        raise recognize.RecognizeError(
            f"No cached depot manifests found under {install_dir}/{recognize.DEPOTDOWNLOADER_DIR}"
        )

    size_on_disk = measure_content_size(install_dir)
    # "0" means "no real build installed yet" (Steam uses it as a
    # sentinel) -- a bare `or` treats that non-empty string as truthy and
    # never falls through to TargetBuildID, leaving a stale/wrong buildid.
    existing_buildid = app_state.get("buildid")
    buildid = existing_buildid if existing_buildid and existing_buildid != "0" else None
    buildid = build_id or buildid or app_state.get("TargetBuildID") or "0"

    # A shared depot (e.g. Steamworks Common Redistributables) is installed once
    # under its owning app and only referenced here. Listing it in
    # InstalledDepots as though this app owned a copy contradicts SharedDepots.
    shared = app_state.get("SharedDepots")
    shared_ids = set(shared) if isinstance(shared, dict) else set()
    dlc_depots = dlc_depots or {}
    installed_depots: dict = {}
    for depot_id, manifest_id in depot_manifests.items():
        if depot_id in shared_ids:
            continue
        entry = {"manifest": manifest_id, "size": "0"}
        if depot_id in dlc_depots:
            entry["dlcappid"] = dlc_depots[depot_id]
        installed_depots[depot_id] = entry
    if not installed_depots:
        raise recognize.RecognizeError(
            f"Every cached depot for {appid} is a shared depot -- nothing to install"
        )

    app_state["StateFlags"] = "4"
    app_state["installdir"] = install_dir.name
    app_state["LastUpdated"] = str(now_unix)
    app_state["SizeOnDisk"] = str(size_on_disk)
    app_state["StagingSize"] = "0"
    app_state["buildid"] = buildid
    app_state["UpdateResult"] = "0"
    app_state["InstalledDepots"] = installed_depots
    app_state.pop("StagedDepots", None)
    # Steam's own per-DLC progress for a download it started: left in place it
    # contradicts the settled counters and Steam resumes fetching the DLC.
    app_state.pop("DlcDownloads", None)
    settle_download_counters(app_state)

    if existed:
        backup_once(manifest_path)
    write_atomic(manifest_path, vdf.dumps("AppState", app_state))
    return manifest_path


def backup_once(manifest_path: Path) -> None:
    """Keep the *pristine* manifest, not the previous run's output.

    An unconditional backup means a second run overwrites the original with
    run 1's already-patched file, so the recovery artifact for a 90+ GB install
    is one re-run away from being useless. Only write it if absent.
    """
    backup_path = manifest_path.with_suffix(".acf.bak")
    if not backup_path.exists():
        backup_path.write_text(manifest_path.read_text())


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash can't truncate the manifest.

    A partial write leaves an unparseable manifest, which Steam and this tool
    both then choke on. `os.replace` is atomic within a filesystem, and the
    temp file is created alongside the target to stay on the same one.
    """
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def settle_download_counters(app_state: dict) -> None:
    """Mark the download bookkeeping complete: `<X>Downloaded` == `<X>ToDownload`.

    Leaving these at their mid-download values is what made Steam discard a
    StateFlags=4 manifest and resume fetching. Real installed manifests keep
    these fields (they are not dropped) with the pair values equal.
    """
    for total_key, done_key in (
        ("BytesToDownload", "BytesDownloaded"),
        ("BytesToStage", "BytesStaged"),
    ):
        total = app_state.get(total_key)
        if total is not None:
            app_state[done_key] = total
