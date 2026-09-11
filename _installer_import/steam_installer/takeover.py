"""Adopt content the Steam client already downloaded instead of refetching it.

Steam stages an in-progress download into `steamapps/downloading/<appid>/`,
laid out exactly like the finished game (confirmed on a live BeamNG.drive
staging tree: `Bin64/`, `BinLinux/`, `campaigns/`, `content/`), and commits it
into `steamapps/common/<installdir>/` when it finishes.

This tool exists to make installs faster. Throwing away tens of gigabytes the
user already waited for, to start again from zero, would make it slower. So
when a staged tree exists, hardlink it into the install directory first and
let depotdownloader do the rest.

That works because depotdownloader verifies what is already on disk before
fetching: `ContentDownloader.cs` runs `Util.ValidateSteam3FileChecksums()` on
an existing file and skips it entirely when `neededChunks.Count == 0`. It
needs no prior `.DepotDownloader` state to do this, so adopted files count.

Hardlinks, not moves, and not copies. The staged tree keeps its entries until
`finalize.finish` clears it at the very end, so a failed run still leaves Steam
able to resume its own download -- which a move would destroy. Linking costs no
extra disk, where a copy of a 47 GB tree would need 47 GB.

The two trees share inodes, so depotdownloader patching a partial file in place
(it seeks and writes into the existing file rather than replacing it) rewrites
Steam's copy too. That is not a hazard, it is the point: both names converge on
the same corrected content, so whichever downloader finishes the job, the other
one's view is already right. Steam chunk-validates on resume regardless.

This does mean the staged bytes are not a pristine backup. Nothing is deleted,
but they are not frozen either -- on ext4 there is no reflink to get both.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from steam_installer.library import SteamLibrary


@dataclass(frozen=True)
class Staged:
    appid: int
    staging_dir: Path
    install_dir: Path
    file_count: int
    bytes_staged: int


@dataclass(frozen=True)
class Adoption:
    linked: int
    skipped: int
    failed: int
    bytes_adopted: int


def find_staged(library: SteamLibrary, appid: int, install_dir: Path) -> Staged | None:
    """Steam's in-progress download for `appid`, or None if there isn't one."""
    staging_dir = library.steamapps / "downloading" / str(appid)
    if not staging_dir.is_dir():
        return None
    files = [f for f in staging_dir.rglob("*") if f.is_file() and not f.is_symlink()]
    if not files:
        return None
    return Staged(
        appid=appid,
        staging_dir=staging_dir,
        install_dir=install_dir,
        file_count=len(files),
        bytes_staged=sum(f.stat().st_size for f in files),
    )


def adopt(staged: Staged, logger: logging.Logger) -> Adoption:
    """Hardlink the staged tree into the install directory. Originals survive.

    Never overwrites a file that is already in place: an existing file is
    either content this tool put there or content Steam committed, and
    depotdownloader will hash-check both anyway.
    """
    linked = skipped = failed = 0
    adopted_bytes = 0

    for source in sorted(staged.staging_dir.rglob("*")):
        if not source.is_file() or source.is_symlink():
            continue
        relative = source.relative_to(staged.staging_dir)
        destination = staged.install_dir / relative
        if destination.exists():
            skipped += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, destination)
        except OSError as exc:
            # Not fatal: depotdownloader simply downloads whatever we failed to
            # adopt. Losing a link is slower, never wrong.
            if failed == 0:
                logger.warning("Could not hardlink %s: %s", relative, exc)
            failed += 1
        else:
            linked += 1
            adopted_bytes += source.stat().st_size

    if failed:
        logger.warning("%d staged file(s) could not be adopted.", failed)
    logger.info(
        "Adopted %.2f GB from Steam's staging tree (%d linked, %d already present).",
        adopted_bytes / 1e9,
        linked,
        skipped,
    )
    return Adoption(
        linked=linked, skipped=skipped, failed=failed, bytes_adopted=adopted_bytes
    )
