"""External binaries this tool shells out to, and a clear error when they're missing."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

TOOL_HINTS = {
    "depotdownloader": "Run ./install.sh, which fetches it from the SteamRE release.",
    "steamcmd": "Run ./install.sh, or: yay -S steamcmd",
}


# The copy install.sh manages. Preferred over whatever PATH finds first: each
# depotdownloader binary keeps its remembered login in its own IsolatedStorage
# slot, keyed by its path. With an AUR copy in /usr/bin as well, a terminal run
# (PATH has ~/.local/bin) and a sudo'd run (secure_path does not) used two
# different binaries -- one logged in, one asking for a password nobody was
# there to type.
MANAGED_DEPOTDOWNLOADER = Path.home() / ".local" / "bin" / "depotdownloader"


class DependencyError(Exception):
    pass


def depotdownloader_bin() -> str:
    """The depotdownloader to run: install.sh's own copy, else PATH's."""
    if os.access(MANAGED_DEPOTDOWNLOADER, os.X_OK):
        return str(MANAGED_DEPOTDOWNLOADER)
    return "depotdownloader"


def missing_tools(*, skip_steamcmd: bool) -> list[str]:
    """Which required binaries are not on PATH, in the order they'd be used."""
    needed = ["depotdownloader"]
    if not skip_steamcmd:
        needed.append("steamcmd")
    resolved = {"depotdownloader": depotdownloader_bin()}
    return [tool for tool in needed if shutil.which(resolved.get(tool, tool)) is None]


def require(*, skip_steamcmd: bool) -> None:
    missing = missing_tools(skip_steamcmd=skip_steamcmd)
    if missing:
        details = "; ".join(
            f"`{tool}` not found -- {TOOL_HINTS[tool]}" for tool in missing
        )
        raise DependencyError(details)
