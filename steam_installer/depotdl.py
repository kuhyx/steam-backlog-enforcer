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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from steam_installer import deps, runlog

if TYPE_CHECKING:
    import logging
    from pathlib import Path

DEFAULT_MAX_DOWNLOADS = 32

# Windows depots only: a game this tool can map to Proton ships no other kind.
OS_NAME = "windows"


# depotdownloader's licence check refusing a DLC app. The one failure that is
# expected: most games list DLC the account never bought.
NOT_OWNED_MARKER = "is not available from this account"


@dataclass(frozen=True)
class Pull:
    """Where and as whom depotdownloader pulls content, and in which language."""

    install_dir: Path
    username: str
    language: str = "english"
    max_downloads: int = DEFAULT_MAX_DOWNLOADS


def _command(appid: int, pull: Pull) -> list[str]:
    return [
        deps.depotdownloader_bin(),
        "-app",
        str(appid),
        "-os",
        OS_NAME,
        "-language",
        pull.language,
        "-max-downloads",
        str(pull.max_downloads),
        "-username",
        pull.username,
        "-remember-password",
        "-dir",
        str(pull.install_dir),
    ]


def download(appid: int, pull: Pull, logger: logging.Logger) -> int:
    """Run depotdownloader against the install dir, streaming its progress live.

    Returns the exit code rather than raising: the caller has to distinguish
    "download failed" from "download fine, manifest step failed" to decide
    whether touching the manifest is safe at all.
    """
    pull.install_dir.mkdir(parents=True, exist_ok=True)
    returncode, _ = runlog.run_logged(_command(appid, pull), logger)
    return returncode


def download_dlc(dlc_appid: int, pull: Pull, logger: logging.Logger) -> bool | None:
    """Fetch one DLC app into the game's own install dir.

    Returns True when downloaded, None when the account does not own it, and
    False for any other failure -- which the caller must treat as fatal.
    """
    returncode, output = runlog.run_logged(_command(dlc_appid, pull), logger)
    if returncode == 0:
        return True
    return None if NOT_OWNED_MARKER in output else False
