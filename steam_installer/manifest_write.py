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
from typing import TYPE_CHECKING

from steam_installer import recognize, vdf
from steam_installer.manifest_depots import Proven, installed_depots, pick_buildid

if TYPE_CHECKING:
    from pathlib import Path

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
    proven: Proven | None = None,
) -> Path:
    """Patch appmanifest_<appid>.acf to StateFlags=4 using only verified-known values.

    Patches the manifest on disk, or -- when there is none -- writes
    ``proven.seed`` instead. With neither it refuses.
    """
    proven = proven or Proven()
    manifest_path = library.steamapps / f"appmanifest_{appid}.acf"
    existed = manifest_path.is_file()
    if not existed and proven.seed is None:
        msg = f"No existing {manifest_path.name} to finish and no seed to write"
        raise recognize.RecognizeError(msg)
    app_state = (
        vdf.parse(manifest_path.read_text()).get("AppState", {})
        if existed
        else proven.seed
    )
    if not isinstance(app_state, dict):
        msg = f"{manifest_path} is not a valid AppState manifest"
        raise recognize.RecognizeError(msg)

    depot_manifests = recognize.discover_cached_depot_manifests(install_dir)
    if not depot_manifests:
        msg = (
            "No cached depot manifests found under "
            f"{install_dir}/{recognize.DEPOTDOWNLOADER_DIR}"
        )
        raise recognize.RecognizeError(msg)
    depots = installed_depots(app_state, depot_manifests, proven.dlc_depots)
    if not depots:
        msg = f"Every cached depot for {appid} is a shared depot -- nothing to install"
        raise recognize.RecognizeError(msg)

    app_state["StateFlags"] = "4"
    app_state["installdir"] = install_dir.name
    app_state["LastUpdated"] = str(now_unix)
    app_state["SizeOnDisk"] = str(measure_content_size(install_dir))
    app_state["StagingSize"] = "0"
    app_state["buildid"] = pick_buildid(app_state, proven.build_id)
    app_state["UpdateResult"] = "0"
    app_state["InstalledDepots"] = depots
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

    A partial write leaves an unparsable manifest, which Steam and this tool
    both then choke on. `Path.replace` is atomic within a filesystem, and the
    temp file is created alongside the target to stay on the same one.
    """
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    try:
        tmp.write_text(text)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def settle_download_counters(app_state: dict) -> None:
    """Zero the download bookkeeping: nothing is queued, nothing is staged.

    Leaving these at their mid-download values is what made Steam discard a
    StateFlags=4 manifest and resume fetching. All four go to "0", the same as
    the from-scratch skeleton Steam accepted, rather than merely equal: the
    older equal-pair form wrote `1000`/`1000` from a broken manifest, a value
    no real install ever had.
    """
    for key in ("BytesToDownload", "BytesDownloaded", "BytesToStage", "BytesStaged"):
        app_state[key] = "0"
