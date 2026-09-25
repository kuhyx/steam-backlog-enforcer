"""Wraps depotdownloader for the bulk content pull -- this is the fast path.

No `-depot` filter is passed: depotdownloader's own per-depot ownership check
(AccountHasAccess, checked before any key fetch) already skips depots the
account doesn't own and continues with the rest, as long as `-os` is set
correctly. Without `-os`, it defaults to the host OS and can filter out every
real (Windows-tagged) depot, leaving only stray OS-agnostic ones -- that's
what caused the very first "0 bytes from 0 depots" failure this project was
built to avoid.
"""

from __future__ import annotations

import logging
from pathlib import Path

from steam_installer import deps, runlog

DEFAULT_MAX_DOWNLOADS = 32


# depotdownloader's licence check refusing a DLC app. The one failure that is
# expected: most games list DLC the account never bought.
NOT_OWNED_MARKER = "is not available from this account"


def _command(
    appid: int,
    install_dir: Path,
    username: str,
    language: str,
    os_name: str,
    max_downloads: int,
) -> list[str]:
    return [
        deps.depotdownloader_bin(),
        "-app",
        str(appid),
        "-os",
        os_name,
        "-language",
        language,
        "-max-downloads",
        str(max_downloads),
        "-username",
        username,
        "-remember-password",
        "-dir",
        str(install_dir),
    ]


def download(
    appid: int,
    install_dir: Path,
    username: str,
    logger: logging.Logger,
    language: str = "english",
    os_name: str = "windows",
    max_downloads: int = DEFAULT_MAX_DOWNLOADS,
) -> int:
    """Run depotdownloader against `install_dir`, streaming its own progress output live.

    Returns the exit code rather than raising: the caller has to distinguish
    "download failed" from "download fine, manifest step failed" to decide
    whether touching the manifest is safe at all.
    """
    install_dir.mkdir(parents=True, exist_ok=True)
    cmd = _command(appid, install_dir, username, language, os_name, max_downloads)
    returncode, _ = runlog.run_logged(cmd, logger)
    return returncode


def download_dlc(
    dlc_appid: int,
    install_dir: Path,
    username: str,
    logger: logging.Logger,
    language: str = "english",
    os_name: str = "windows",
    max_downloads: int = DEFAULT_MAX_DOWNLOADS,
) -> bool | None:
    """Fetch one DLC app into the game's own `install_dir`.

    Returns True when downloaded, None when the account does not own it, and
    False for any other failure -- which the caller must treat as fatal.
    """
    cmd = _command(dlc_appid, install_dir, username, language, os_name, max_downloads)
    returncode, output = runlog.run_logged(cmd, logger)
    if returncode == 0:
        return True
    return None if NOT_OWNED_MARKER in output else False
