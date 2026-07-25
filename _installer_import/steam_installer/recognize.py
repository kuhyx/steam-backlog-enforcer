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
cache (never guessed), and the real on-disk size via `du`. Steam is left to
self-correct the rest (byte counters, staged-file bookkeeping) on its very
next launch -- confirmed: it did exactly that in practice, cleaning up the
hand-edited fields on its own.
"""

from __future__ import annotations

import re
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from steam_installer import vdf
from steam_installer.library import SteamLibrary

MANIFEST_CACHE_RE = re.compile(r"^(\d+)_(\d+)\.manifest$")


class RecognizeError(Exception):
    pass


@dataclass
class ValidateResult:
    completed: bool
    crashed_on_install_script: bool
    returncode: int


def run_steamcmd_validate(
    appid: int, install_dir: Path, username: str
) -> ValidateResult:
    """Run steamcmd's app_update ... validate. `force_install_dir` must precede `+login`
    (steamcmd itself warns about this ordering).

    Deliberately does NOT capture stdout/stderr: steamcmd prompts for a
    password (and possibly a Steam Guard code) on stdin, and prompt text
    written to a captured/buffered stdout never reaches the terminal --
    the process looks hung with no visible request for input. Output is
    left to inherit the parent's terminal instead, exactly like
    depotdownloader's own interactive login.

    The confirmed steamcmd install-script bug (see module docstring) kills
    the process with SIGSEGV -- Python reports that as returncode -11 on
    POSIX. Checking the signal directly is more reliable than grepping
    captured text for a message string, and doesn't require capturing
    output at all.
    """
    cmd = [
        "steamcmd",
        "+force_install_dir",
        str(install_dir),
        "+login",
        username,
        "+app_update",
        str(appid),
        "validate",
        "+quit",
    ]
    result = subprocess.run(cmd, timeout=3600)
    crashed = result.returncode == -signal.SIGSEGV
    return ValidateResult(
        completed=result.returncode == 0,
        crashed_on_install_script=crashed,
        returncode=result.returncode,
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
    Does nothing if no manifest exists yet -- steamcmd creates one itself in
    that case, with the right installdir since we pass force_install_dir.
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
    manifest_path.write_text(vdf.dumps("AppState", app_state))


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
    )


def discover_cached_depot_manifests(install_dir: Path) -> dict[str, str]:
    """Depot ID -> manifest ID, read from depotdownloader's own local cache filenames."""
    cache_dir = install_dir / ".DepotDownloader"
    found: dict[str, str] = {}
    if not cache_dir.is_dir():
        return found
    for entry in cache_dir.iterdir():
        match = MANIFEST_CACHE_RE.match(entry.name)
        if match:
            depot_id, manifest_id = match.groups()
            found[depot_id] = manifest_id
    return found


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
            f"No cached depot manifests found under {install_dir}/.DepotDownloader"
        )

    size_on_disk = sum(f.stat().st_size for f in install_dir.rglob("*") if f.is_file())
    # "0" means "no real build installed yet" (steamcmd/Steam use it as a
    # sentinel) -- a bare `or` treats that non-empty string as truthy and
    # never falls through to TargetBuildID, leaving a stale/wrong buildid.
    existing_buildid = app_state.get("buildid")
    buildid = existing_buildid if existing_buildid and existing_buildid != "0" else None
    buildid = buildid or app_state.get("TargetBuildID") or "0"

    installed_depots = {
        depot_id: {"manifest": manifest_id, "size": "0"}
        for depot_id, manifest_id in depot_manifests.items()
    }

    app_state["StateFlags"] = "4"
    app_state["installdir"] = install_dir.name
    app_state["LastUpdated"] = str(now_unix)
    app_state["SizeOnDisk"] = str(size_on_disk)
    app_state["StagingSize"] = "0"
    app_state["buildid"] = buildid
    app_state["UpdateResult"] = "0"
    app_state["InstalledDepots"] = installed_depots
    app_state.pop("StagedDepots", None)

    backup_path = manifest_path.with_suffix(".acf.bak")
    backup_path.write_text(manifest_path.read_text())
    manifest_path.write_text(vdf.dumps("AppState", app_state))
    return manifest_path
