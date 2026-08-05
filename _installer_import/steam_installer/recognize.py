"""Make the Steam client recognize downloaded content as installed.

Primary path: `steamcmd ... app_update <id> validate`. It hash-checks
existing files against the depot manifest and only fetches real deltas --
confirmed live against a real 90+ GB install, going from ~24% to ~41%
credited in one pass without redownloading from scratch.

Fallback: some titles ship a post-install script (installscript.vdf) that
steamcmd tries to run through a private, headless Proton setup. On at least
one real title this hit a confirmed steamcmd bug -- a stack-overflow segfault
in the closed-source steamclient.so error-handling path after the script
evaluator reports failure (crash backtrace: the same stack frame repeating
dozens of times). There's no known fix. When that specific crash is
detected, we finish the appmanifest by hand using ONLY values we already
verified ourselves: the exact manifest IDs from depotdownloader's own local
cache (never guessed), and the real on-disk size measured directly.

Do NOT leave the download bookkeeping for Steam to tidy up on its next
launch. An earlier version of this module did, on the belief that Steam
self-corrects; it does not. A manifest that says StateFlags=4 while
`BytesDownloaded` still differs from `BytesToDownload` is self-contradictory,
and Steam resolves the contradiction by discarding the "installed" claim and
resuming the download -- 90 GB of it, in the run that prompted this comment.
The byte counters (`_settle_download_counters`) and the staging tree
(`clear_steam_staging`) must both be settled here, and
`manifest_reflects_real_install` refuses to call an install real until they
are.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path

from steam_installer import runlog, vdf
from steam_installer.library import SteamLibrary

MANIFEST_CACHE_RE = re.compile(r"^(\d+)_(\d+)\.manifest$")

# depotdownloader's own cache/staging area lives inside the install dir but is
# not game content -- Steam's SizeOnDisk must not count it.
DEPOTDOWNLOADER_DIR = ".DepotDownloader"

# Module-level so tests can point it at a fake /proc tree.
PROC_DIR = Path("/proc")


class RecognizeError(Exception):
    pass


@dataclass
class ValidateResult:
    completed: bool
    crashed_on_install_script: bool
    returncode: int
    output: str = ""


def run_steamcmd_validate(
    appid: int,
    username: str,
    logger: logging.Logger,
) -> ValidateResult:
    """Run steamcmd's app_update ... validate.

    Takes no install dir on purpose. `force_install_dir` sets a Steam *library
    root*, not an install directory: pointing it at the game folder made
    steamcmd look for manifests in `<game>/steamapps/`, find none ("Loaded 0
    apps from install folder"), create that stray directory, and then fail the
    app with "Invalid platform" because it had no depot context for it. The app
    already lives in a registered library, so letting steamcmd use the real one
    is both correct and sufficient.

    Output is teed through a pty (see runlog) rather than captured: steamcmd
    prompts for a password and possibly a Steam Guard code on stdin, and prompt
    text written to a captured/buffered pipe never reaches the terminal -- the
    process looks hung with no visible request for input.

    The confirmed steamcmd install-script bug (see module docstring) kills
    the process with SIGSEGV -- Python reports that as returncode -11 on
    POSIX. Checking the signal directly is more reliable than grepping
    captured text for a message string.
    """
    cmd = [
        "steamcmd",
        # A Linux steamcmd refuses a Windows-only app with "Invalid platform"
        # unless told which platform to resolve depots for. Must precede +login.
        "+@sSteamCmdForcePlatformType",
        "windows",
        "+login",
        username,
        "+app_update",
        str(appid),
        "validate",
        "+quit",
    ]
    returncode, output = runlog.run_logged(cmd, logger, timeout=3600)
    crashed = returncode == -signal.SIGSEGV
    return ValidateResult(
        completed=returncode == 0,
        crashed_on_install_script=crashed,
        returncode=returncode,
        output=output,
    )


def ensure_installdir_correct(
    library: SteamLibrary, appid: int, install_dir: Path
) -> None:
    """Patch a stale `installdir` field BEFORE running steamcmd, not just after.

    Confirmed necessary: a prior, unrelated Steam GUI glitch left this app's
    manifest pointing at a different folder name. steamcmd's own validate run
    didn't correct it despite a clean exit, and relaunching the Steam client
    read that same stale field and wiped the correctly-downloaded folder as
    "orphaned" while starting a fresh download into the wrong one. Fixing it
    proactively, before steamcmd ever runs, closes that window entirely.
    Does nothing if no manifest exists yet -- steamcmd's own app_update writes
    one in that case, and it derives installdir from the app's metadata.
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
    _backup_once(manifest_path)
    _write_atomic(manifest_path, vdf.dumps("AppState", app_state))


def manifest_reflects_real_install(
    library: SteamLibrary, appid: int, install_dir: Path
) -> bool:
    """Don't trust steamcmd's exit code alone -- verify the manifest actually matches
    reality. Confirmed necessary the hard way: steamcmd exited 0 while leaving
    `installdir` pointed at a stale, unrelated folder name from an earlier corrupted
    manifest state, `InstalledDepots` empty, and `StateFlags` still "update needed" --
    a "clean" exit that hadn't actually recognized anything. Relaunching the Steam
    client then treated the real, correctly-downloaded folder as orphaned and wiped
    it while starting a fresh (slow, wrong-folder) download.
    """
    manifest_path = library.steamapps / f"appmanifest_{appid}.acf"
    if not manifest_path.is_file():
        return False
    data = vdf.parse(manifest_path.read_text())
    app_state = data.get("AppState", {})
    if not isinstance(app_state, dict):
        return False
    return (
        app_state.get("StateFlags") == "4"
        and app_state.get("installdir") == install_dir.name
        and bool(app_state.get("InstalledDepots"))
        and download_counters_settled(app_state)
    )


def download_counters_settled(app_state: dict) -> bool:
    """Whether the download bookkeeping agrees that nothing is left to fetch.

    This is the check that was missing when Steam threw away a StateFlags=4
    manifest and resumed a 90 GB download: the file simultaneously claimed
    "fully installed" and "22 GB of 92 GB downloaded". Across every genuine
    installed manifest on this machine the counters are equal in pairs and
    StagingSize is "0", so treat any inequality as "still downloading".
    """
    pairs = (("BytesToDownload", "BytesDownloaded"), ("BytesToStage", "BytesStaged"))
    for total_key, done_key in pairs:
        total = app_state.get(total_key)
        done = app_state.get(done_key)
        # Absent counters are fine (Steam omits them on some apps); mismatched
        # ones are not.
        if total is not None and done is not None and total != done:
            return False
    return app_state.get("StagingSize", "0") == "0"


def discover_cached_depot_manifests(install_dir: Path) -> dict[str, str]:
    """Depot ID -> manifest ID, read from depotdownloader's own local cache filenames."""
    cache_dir = install_dir / DEPOTDOWNLOADER_DIR
    found: dict[str, str] = {}
    if not cache_dir.is_dir():
        return found
    for entry in cache_dir.iterdir():
        match = MANIFEST_CACHE_RE.match(entry.name)
        if match:
            depot_id, manifest_id = match.groups()
            found[depot_id] = manifest_id
    return found


def clear_steam_staging(library: SteamLibrary, appid: int) -> int:
    """Drop Steam's half-finished staging tree for `appid`. Returns bytes freed.

    Steam stages downloaded chunks in `steamapps/downloading/<appid>/` and
    commits them into `common/` afterwards. If we declare the app installed
    while that tree still holds tens of GB plus its `state_*.patch` files,
    Steam finds work pending and resumes the update -- the manifest says
    "done", the staging area says "mid-download". Every genuinely installed app
    on this machine has an empty (4 KB) staging dir, so matching that is what
    "installed" actually looks like on disk.

    Only ever discards Steam's own staging copies, never `common/` content.
    """
    downloading = library.steamapps / "downloading"
    staged = downloading / str(appid)
    freed = 0
    if staged.is_dir():
        freed = sum(f.stat().st_size for f in staged.rglob("*") if f.is_file())
        shutil.rmtree(staged)
        staged.mkdir(parents=True, exist_ok=True)
    for patch in downloading.glob(f"state_{appid}_*.patch"):
        freed += patch.stat().st_size
        patch.unlink()
    return freed


def read_app_state(manifest_path: Path) -> dict:
    """The `AppState` block of a manifest, or an empty dict if unreadable."""
    if not manifest_path.is_file():
        return {}
    data = vdf.parse(manifest_path.read_text())
    app_state = data.get("AppState", {})
    return app_state if isinstance(app_state, dict) else {}


def steam_client_pids() -> list[int]:
    """PIDs of a running Steam client, if any.

    Steam owns appmanifest_*.acf while it runs and rewrites it from its own
    in-memory state, so a manifest patched underneath a live client is simply
    discarded -- which is exactly what happened on the run that prompted all
    this. Matching on the executable path (not a `pgrep -f` pattern) avoids
    matching our own command line.
    """
    pids: list[int] = []
    for entry in PROC_DIR.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            exe = (entry / "exe").resolve()
        except OSError:
            continue
        # Match the client by executable name alone. An earlier version also
        # required "ubuntu12_32" in the path, which silently fails open for a
        # Flatpak install (/app/bin/steam) -- and a guard that quietly stops
        # guarding is worse than no guard. `steamcmd` is a different binary, so
        # it is not matched here.
        if exe.name in ("steam", "steamwebhelper"):
            pids.append(int(entry.name))
    return pids


def check_ready_to_finish(
    install_dir: Path,
    app_state: dict,
    required_depots: set[str],
    expected_build_id: str | None,
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

    cached = discover_cached_depot_manifests(install_dir)

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
            f"{install_dir}/{DEPOTDOWNLOADER_DIR} -- the download did not finish"
        )

    buildid = app_state.get("buildid")
    target = app_state.get("TargetBuildID")
    if not (buildid and buildid != "0") and not (target and target != "0"):
        problems.append(
            "manifest has no usable buildid (both buildid and TargetBuildID are 0) "
            "-- steamcmd never recorded a real build"
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

    # Cache *filenames* are not content. Without this, an install dir holding
    # only `.DepotDownloader/<id>_<id>.manifest` and no game files passes every
    # other check and gets written as StateFlags=4 with SizeOnDisk=0.
    if not measure_content_size(install_dir):
        problems.append(
            f"no game content found under {install_dir} (only depotdownloader "
            "cache files) -- nothing was actually installed"
        )

    pids = steam_client_pids()
    if pids:
        problems.append(
            f"the Steam client is running (pid {', '.join(str(p) for p in pids)}) "
            "and will overwrite the manifest -- close Steam and re-run"
        )

    return problems


def measure_content_size(install_dir: Path) -> int:
    """Bytes of real game content, excluding depotdownloader's own cache/staging.

    `.DepotDownloader/` holds manifests and a staging tree that Steam knows
    nothing about; counting them overstates SizeOnDisk by gigabytes.
    """
    total = 0
    for entry in install_dir.rglob("*"):
        if DEPOTDOWNLOADER_DIR in entry.parts:
            continue
        if entry.is_file() and not entry.is_symlink():
            total += entry.stat().st_size
    return total


def finish_manifest_manually(
    library: SteamLibrary,
    appid: int,
    install_dir: Path,
    now_unix: int,
) -> Path:
    """Patch appmanifest_<appid>.acf to StateFlags=4 using only verified-known values.

    Requires steamcmd to have already written a partial manifest (even a crashed
    run does) -- that's where buildid and SharedDepots come from. This never
    fabricates a manifest from nothing.
    """
    manifest_path = library.steamapps / f"appmanifest_{appid}.acf"
    if not manifest_path.is_file():
        raise RecognizeError(
            f"No existing {manifest_path.name} to finish -- run steamcmd's "
            "app_update at least once first (even a crashed run writes one)."
        )
    data = vdf.parse(manifest_path.read_text())
    app_state = data.get("AppState", {})
    if not isinstance(app_state, dict):
        raise RecognizeError(f"{manifest_path} is not a valid AppState manifest")

    depot_manifests = discover_cached_depot_manifests(install_dir)
    if not depot_manifests:
        raise RecognizeError(
            f"No cached depot manifests found under {install_dir}/{DEPOTDOWNLOADER_DIR}"
        )

    size_on_disk = measure_content_size(install_dir)
    # "0" means "no real build installed yet" (steamcmd/Steam use it as a
    # sentinel) -- a bare `or` treats that non-empty string as truthy and
    # never falls through to TargetBuildID, leaving a stale/wrong buildid.
    existing_buildid = app_state.get("buildid")
    buildid = existing_buildid if existing_buildid and existing_buildid != "0" else None
    buildid = buildid or app_state.get("TargetBuildID") or "0"

    # A shared depot (e.g. Steamworks Common Redistributables) is installed once
    # under its owning app and only referenced here. Listing it in
    # InstalledDepots as though this app owned a copy contradicts SharedDepots.
    shared = app_state.get("SharedDepots")
    shared_ids = set(shared) if isinstance(shared, dict) else set()
    installed_depots = {
        depot_id: {"manifest": manifest_id, "size": "0"}
        for depot_id, manifest_id in depot_manifests.items()
        if depot_id not in shared_ids
    }
    if not installed_depots:
        raise RecognizeError(
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
    _settle_download_counters(app_state)

    _backup_once(manifest_path)
    _write_atomic(manifest_path, vdf.dumps("AppState", app_state))
    return manifest_path


def _backup_once(manifest_path: Path) -> None:
    """Keep the *pristine* manifest, not the previous run's output.

    An unconditional backup means a second run overwrites the original with
    run 1's already-patched file, so the recovery artifact for a 90+ GB install
    is one re-run away from being useless. Only write it if absent.
    """
    backup_path = manifest_path.with_suffix(".acf.bak")
    if not backup_path.exists():
        backup_path.write_text(manifest_path.read_text())


def _write_atomic(path: Path, text: str) -> None:
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


def _settle_download_counters(app_state: dict) -> None:
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
