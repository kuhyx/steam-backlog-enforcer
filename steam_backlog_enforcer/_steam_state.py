"""Read-only helpers for Steam's on-disk state (install/update progress).

Kept in its own leaf module (no intra-package imports) so both
``game_install`` and ``library_hider`` can use it without forming an import
cycle. ``STEAMAPPS_PATH`` lives here as the single source of truth for the
Steam library location.
"""

from __future__ import annotations

from pathlib import Path
import re

STEAMAPPS_PATH = Path("~/.local/share/Steam/steamapps").expanduser()


def _manifest_transfer_active(manifest: Path) -> bool:
    """Return True if *manifest* shows unfinished download or staging bytes.

    Args:
        manifest: Path to an ``appmanifest_*.acf`` file.

    Returns:
        True if the app still has bytes left to download or stage to disk.
    """
    try:
        content = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    def _field(name: str) -> int:
        match = re.search(rf'"{name}"\s+"(\d+)"', content)
        return int(match.group(1)) if match else 0

    # BytesTo* are the totals for the in-flight update; BytesDownloaded/Staged
    # track progress. Progress strictly below the total means the update (or
    # its on-disk commit) is still running.
    return _field("BytesToDownload") > _field("BytesDownloaded") or _field(
        "BytesToStage"
    ) > _field("BytesStaged")


def steam_update_in_progress() -> bool:
    """Return True if any installed Steam app is mid-update.

    Steam records live transfer progress in each ``appmanifest_*.acf``: a game
    is actively updating while it still has bytes left to download or commit to
    disk. Restarting Steam during that window suspends the transfer and can
    leave a partially-written install — corrupting it. The enforcer checks this
    before bouncing Steam so it never interrupts an in-flight update (the
    failure that corrupted Age of Empires II DE into a deterministic launch
    crash).

    Returns:
        True if at least one appmanifest shows an unfinished download/stage.
    """
    try:
        manifests = list(STEAMAPPS_PATH.glob("appmanifest_*.acf"))
    except OSError:
        return False
    return any(_manifest_transfer_active(m) for m in manifests)
