"""External binaries this tool shells out to, and a clear error when they're missing."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from steam_installer import errors

TOOL_HINTS = {
    "depotdownloader": (
        "Run steam_installer/install_deps.sh, "
        "which fetches it from the SteamRE release."
    ),
}


# The copy install_deps.sh manages. Preferred over whatever PATH finds first: each
# depotdownloader binary keeps its remembered login in its own IsolatedStorage
# slot, keyed by its path. With an AUR copy in /usr/bin as well, a terminal run
# (PATH has ~/.local/bin) and a sudo'd run (secure_path does not) used two
# different binaries -- one logged in, one asking for a password nobody was
# there to type.
MANAGED_DEPOTDOWNLOADER = Path.home() / ".local" / "bin" / "depotdownloader"


class DependencyError(errors.InstallerError):
    """A tool this installer shells out to is missing."""


def depotdownloader_bin() -> str:
    """The depotdownloader to run: install_deps.sh's own copy, else PATH's."""
    if os.access(MANAGED_DEPOTDOWNLOADER, os.X_OK):
        return str(MANAGED_DEPOTDOWNLOADER)
    return "depotdownloader"


def missing_tools() -> list[str]:
    """Which required binaries are not on PATH, in the order they'd be used.

    steamcmd is not one of them: app info comes from Steam's own cache and
    the manifest is written by this tool.
    """
    needed = ["depotdownloader"]
    resolved = {"depotdownloader": depotdownloader_bin()}
    return [tool for tool in needed if shutil.which(resolved.get(tool, tool)) is None]


def require() -> None:
    """Fail with the fix when a required tool is missing."""
    missing = missing_tools()
    if missing:
        details = "; ".join(
            f"`{tool}` not found -- {TOOL_HINTS[tool]}" for tool in missing
        )
        raise DependencyError(details)
