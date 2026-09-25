"""Read-only questions about whether Steam will see an install as real.

Split on 2026-09-25 (250-line cap): steamcmd's validate run now lives in
:mod:`steamcmd_validate`, every manifest write in :mod:`manifest_write`, and
the preconditions for writing in :mod:`finish_check`. What stays here is the
shared vocabulary they all read: depotdownloader's cache, Steam's staging tree
and client process, and whether a manifest's bookkeeping says "done".
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from steam_installer import vdf
from steam_installer.library import SteamLibrary

MANIFEST_CACHE_RE = re.compile(r"^(\d+)_(\d+)\.manifest$")

# depotdownloader's own cache/staging area lives inside the install dir but is
# not game content -- Steam's SizeOnDisk must not count it.
DEPOTDOWNLOADER_DIR = ".DepotDownloader"

# Module-level so tests can point it at a fake /proc tree.
PROC_DIR = Path("/proc")


class RecognizeError(Exception):
    pass


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
