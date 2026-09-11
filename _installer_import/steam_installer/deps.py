"""External binaries this tool shells out to, and a clear error when they're missing."""

from __future__ import annotations

import shutil

TOOL_HINTS = {
    "depotdownloader": "Run ./install.sh, which fetches it from the SteamRE release.",
    "steamcmd": "Run ./install.sh, or: yay -S steamcmd",
}


class DependencyError(Exception):
    pass


def missing_tools(*, skip_steamcmd: bool) -> list[str]:
    """Which required binaries are not on PATH, in the order they'd be used."""
    needed = ["depotdownloader"]
    if not skip_steamcmd:
        needed.append("steamcmd")
    return [tool for tool in needed if shutil.which(tool) is None]


def require(*, skip_steamcmd: bool) -> None:
    missing = missing_tools(skip_steamcmd=skip_steamcmd)
    if missing:
        details = "; ".join(
            f"`{tool}` not found -- {TOOL_HINTS[tool]}" for tool in missing
        )
        raise DependencyError(details)
